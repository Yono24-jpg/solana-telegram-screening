"""Upgrade of the existing ALERT ONLY scanner; uses its Telegram and RPC gates."""
import copy
import html
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from signal_quality import snapshot, merge_observations
from screening_rules import address, amount, market, choose_tier, evidence_rejection, social_links, MAX_AGE
from state_store import migrate, already_delivered, sample_performance, performance_summary, HORIZONS
import market_data
import evidence


SOURCES = [('/token-profiles/latest/v1', 'dex_profiles'), ('/token-boosts/latest/v1', 'dex_latest_boosts'),
           ('/token-boosts/top/v1', 'dex_top_boosts'), ('/community-takeovers/latest/v1', 'dex_takeovers'),
           ('/ads/latest/v1', 'dex_ads')]


def checkpoint(state, api, durable=False):
    api.save(state)
    if durable and os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == 'refs/heads/main':
        from persist_state import persist
        merged = persist()
        state.clear(); state.update(merged)


def discover(api, gecko=None):
    gecko = gecko or market_data.GeckoClient(api, {})
    urls = [(api.DEX+p, label) for p, label in SOURCES]
    urls += [(market_data.GECKO+'/networks/solana/new_pools?page='+str(p)+'&include=base_token,quote_token,dex', 'gecko_'+str(p)) for p in (1, 2, 3)]
    def read(item):
        url, label = item
        try: return label, (gecko.request(url) if label.startswith('gecko') else api.request(url))
        except Exception: return label, None
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(read, urls))
    tokens = []; pairs = []; metadata = {}; statuses = {}; native = {}
    for label, data in results:
        valid = isinstance(data, dict) and isinstance(data.get('data'), list) if label.startswith('gecko') else isinstance(data, list)
        statuses[label] = 'ok' if valid else 'unavailable'
        if label.startswith('gecko'):
            native.update({p['pairAddress']:p for p in market_data.gecko_pools(data)})
            for row in data.get('data', []) if isinstance(data, dict) else []:
                a = row.get('attributes', {}).get('address') if isinstance(row, dict) else None
                if address(a) and a not in pairs: pairs.append(a)
        else:
            for row in data if isinstance(data, list) else []:
                if not isinstance(row, dict) or row.get('chainId') != 'solana': continue
                mint = row.get('tokenAddress')
                if not address(mint): continue
                if mint not in tokens: tokens.append(mint)
                metadata.setdefault(mint, []).extend(row.get('links') or [])
    requests = [(api.DEX+'/tokens/v1/solana/'+','.join(tokens[i:i+30]), 'tokens') for i in range(0, min(240, len(tokens)), 30)]
    requests += [(api.DEX+'/latest/dex/pairs/solana/'+','.join(pairs[i:i+20]), 'pairs') for i in range(0, len(pairs), 20)]
    pools = {}; failures = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        for label, data in executor.map(read, requests):
            rows = data if label == 'tokens' and isinstance(data, list) else data.get('pairs', []) if isinstance(data, dict) else []
            if data is None: failures += 1
            for pool in rows or []:
                if not isinstance(pool, dict) or pool.get('chainId') != 'solana' or not address(pool.get('pairAddress')): continue
                token = pool.get('baseToken') or {}; mint = token.get('address')
                if not address(mint): continue
                if label == 'tokens' and mint not in tokens: continue
                if label == 'pairs' and pool['pairAddress'] not in pairs: continue
                info = pool.setdefault('info', {})
                if not isinstance(info, dict): pool['info'] = info = {}
                info['socials'] = (info.get('socials') if isinstance(info.get('socials'), list) else []) + [r for r in metadata.get(mint, []) if isinstance(r, dict)]
                pools[pool['pairAddress']] = pool
    combined = {pair:market_data.select_pool(pools.get(pair), native.get(pair)) for pair in sorted(set(pools)|set(native))}
    return list(combined.values()), {'sources': statuses, 'token_addresses': len(tokens), 'new_pool_addresses': len(pairs),
            'gecko_native_pools':len(native), 'gecko_independent_pools':sum(p.get('dataSource')=='geckoterminal' for p in combined.values()),
            'dex_pool_count':len(pools), 'batch_failures': failures}


def observe(state, pools, now):
    history = merge_observations(state.get('observations', {}), now=now)
    for pool in pools:
        try:
            if not 0 <= now-pool['pairCreatedAt']/1000 <= MAX_AGE: continue
            row = snapshot(pool, now)
            if row is None: continue
            rows = history.setdefault(pool['pairAddress'], [])
            if not rows or now-rows[-1]['t'] >= 60: rows.append(row)
        except (KeyError, TypeError, ValueError): continue
    state['observations'] = merge_observations(history, now=now)


def refresh(pair, mint, api, gecko=None):
    return market_data.refresh_pool(pair, mint, api, gecko or market_data.GeckoClient(api, {}))


def followup(state, pools, api, now, gecko=None):
    current = {(p.get('pairAddress'), (p.get('baseToken') or {}).get('address')):p for p in pools if isinstance(p, dict)}
    due = [r for r in state['performance'].values() if any(str(h) not in r.get('samples', {}) and now >= r['at']+h for h in HORIZONS)]
    for record in sorted(due, key=lambda r:r.get('last_observed_at', 0))[:30]:
        if api.REQUEST_DEADLINE and time.monotonic() >= api.REQUEST_DEADLINE-20: break
        pool = current.get((record['pair'], record['mint']))
        if pool is None:
            try: pool = refresh(record['pair'], record['mint'], api, gecko)
            except Exception: pool = {}
        price = amount(pool.get('priceUsd'))
        sample_performance(record, price, time.time())


def cached(state, key, now, ttl, read):
    old = state['evidence_cache'].get(key)
    if old and 0 <= now-old['at'] <= ttl: return copy.deepcopy(old['value'])
    result = read()
    state['evidence_cache'][key] = {'at': now, 'value': copy.deepcopy(result)}
    return result


def render(pool, m, sec, social, buyers, mint_age, tier):
    esc = lambda value: html.escape(str(value), quote=True)
    mint = pool['baseToken']['address']; symbol = esc(pool['baseToken'].get('symbol', '?')[:32])
    name = esc(pool['baseToken'].get('name', symbol)[:60]); pair = pool['pairAddress']
    community_score = str(social['score'])+'/100' if social.get('score') is not None else 'belum cukup data'
    token_age = f"{mint_age['age_seconds']/60:.0f} menit (inisialisasi mint terverifikasi)" if mint_age.get('verified') else 'belum terverifikasi'
    unique = str(buyers['unique_buyers'])+' alamat unik pada sampel 5m' if buyers.get('unique_buyers') is not None else 'belum terverifikasi'
    growth = m.get('growth')
    momentum = (f"Volume {growth['volume']:.2f}×; BUY {growth['buys']:.2f}×; transaksi {growth['transactions']:.2f}× vs {growth['minutes']:.0f} menit lalu"
                if growth else 'Menunggu observasi kedua untuk membuktikan percepatan')
    risks = list(sec.get('risks', []))+list(social.get('risks', []))+list(buyers.get('risks', []))
    if m.get('cap_basis') == 'fdv_proxy': risks.insert(0,'Market cap belum tersedia; FDV hanya perkiraan valuasi terdilusi')
    if m.get('age_conflict'): risks.insert(0,'Waktu pembuatan pool berbeda antar penyedia')
    if not mint_age.get('verified'): risks.append('Pool baru dapat berisi token lama')
    elif mint_age.get('age_seconds', 0) > MAX_AGE: risks.append('Mint berumur lebih dari 24 jam; yang baru hanya pool')
    if not social.get('complete'): risks.append('Verifikasi komunitas belum lengkap')
    if not buyers.get('strong'): risks.append('Bukti keragaman pembeli belum cukup')
    risks += ['Alamat unik dan anggota komunitas bukan bukti manusia nyata', 'Kunci LP dan kemampuan jual setiap wallet belum terjamin']
    links = [f'<a href="https://dexscreener.com/solana/{pair}">DexScreener</a>', f'<a href="https://axiom.trade/t/{mint}">Axiom</a>']
    for platform, label in [('x', 'X'), ('telegram', 'Telegram')]:
        link = social.get('verified_links', {}).get(platform)
        if link: links.append(f'<a href="{esc(link)}">{label}</a>')
    missing = [label+' belum terverifikasi' for k, label in [('x','X'),('telegram','Telegram')] if k not in social.get('verified_links', {})]
    intro = 'Pantauan awal; verifikasi belum lengkap.' if tier == 'EARLY WATCH' else 'Lolos seluruh gerbang bukti v2; bukan jaminan keuntungan.'
    top = sec.get('top10_accounts_pct')
    valuation = ('FDV (MC belum tersedia)' if m.get('cap_basis') == 'fdv_proxy' else 'MC')
    return (f'🔎 <b>{tier} | {symbol}</b>\n{name}\n{intro}\n'
            f'⏱ Pool: <b>{m["age_seconds"]/60:.0f} menit</b> | Mint: {token_age}\n'
            f'💧 LP ${m["lp"]:,.0f} | {valuation} ${m["cap"]:,.0f}\n'
            f'📊 Volume 5m ${m["volume"]:,.0f} | BUY/SELL {m["buys"]}/{m["sells"]}\n'
            f'👥 Pembeli: {unique}\n'
            f'🎯 Market {m["score"]}/100 | Keamanan {sec["score"]}/100 | Komunitas {community_score}\n'
            f'📈 Harga 5m {m["m5"]:+.1f}%\n<b>Alasan</b>: {momentum}\n'
            f'• Tekanan BUY {100*m["buys"]/(m["buys"]+m["sells"]):.1f}%; mint/freeze nonaktif.\n'
            + (f'• 10 akun token terbesar {top:.2f}% (termasuk vault; bukan 10 pemilik).\n' if top is not None else '')
            + '<b>Risiko</b>:\n'+'\n'.join('• '+esc(r) for r in risks[:7])
            + f'\n📋 <code>{mint}</code>\n'+' | '.join(links)
            + ('\n'+ '; '.join(missing) if missing else '')
            + '\nSumber pasar: '+esc(pool.get('dataSource','dexscreener'))
            + '\nALERT ONLY • Tidak ada transaksi otomatis. Skor bukan probabilitas profit.')


def deliver(state, api, chat, pool, m, sec, social, buyers, mint_age, tier):
    now = time.time(); mint = pool['baseToken']['address']; key = mint+':'+tier
    if already_delivered(state, mint, tier, now): return False
    reservation = uuid.uuid4().hex
    state['delivery'][key] = {'at': now, 'updated': now, 'status': 'pending', 'reservation': reservation}
    # Persist intent before network send: a killed runner never blindly retries the message.
    checkpoint(state, api, durable=True)
    if state['delivery'].get(key, {}).get('reservation') != reservation or state.get('enabled') is False: return False
    try:
        result = api.tg('sendMessage', chat_id=chat, text=render(pool, m, sec, social, buyers, mint_age, tier),
                        parse_mode='HTML', disable_web_page_preview=True, reply_markup=api.KEYBOARD)
        if not isinstance(result.get('message_id'), int) or result.get('chat', {}).get('id') != chat:
            raise ValueError('delivery_not_verified')
    except Exception:
        state['delivery'][key].update(status='unknown', updated=time.time())
        checkpoint(state, api, durable=True)
        print('DELIVERY_UNKNOWN no_automatic_retry=1')
        return False
    state['delivery'][key].update(status='sent', message_id=result['message_id'], updated=time.time())
    state['performance'][key] = {'at': now, 'updated': now, 'mint': mint, 'pair': pool['pairAddress'],
                                 'tier': tier, 'price': m['price'], 'samples': {}}
    checkpoint(state, api, durable=True)
    print('TELEGRAM_SIGNAL_OK tier='+tier.replace(' ', '_')+' message_id='+str(result['message_id']))
    return True


def run(state, chat, api):
    now = time.time(); migrate(state, now)
    report = {'version': '2.1', 'at': now, 'mode': 'ALERT ONLY', 'seen': 0, 'sent': 0, 'rejected': {}, 'candidates': [], 'missing_fields':{},
              'capabilities': {'x_bearer_configured': bool(os.environ.get('X_BEARER_TOKEN')), 'x_reads_enabled': os.environ.get('X_READS_ENABLED') == '1'}}
    gecko = market_data.GeckoClient(api, state)
    pools, discovery = discover(api, gecko); report['discovery'] = discovery
    pools = market_data.refresh_watchlist(pools, state, api, gecko, time.time())
    # Record eligible early observations even before safety data is available.
    observe(state, pools, time.time()); checkpoint(state, api)
    original_deadline = api.REQUEST_DEADLINE
    api.REQUEST_DEADLINE = min(original_deadline, time.monotonic()+35) if original_deadline else time.monotonic()+35
    try:
        followup(state, pools, api, time.time(), gecko)
    finally:
        api.REQUEST_DEADLINE = original_deadline
    chosen = {}
    for pool in pools:
        report['seen'] += 1
        m = market(pool, state['observations'], time.time())
        if m.get('reject'):
            reason = m['reject']; report['rejected'][reason] = report['rejected'].get(reason, 0)+1
            if reason == 'missing_market_data':
                for field in market_data.missing_fields(pool): report['missing_fields'][field] = report['missing_fields'].get(field,0)+1
            continue
        mint = pool['baseToken']['address']
        if mint not in chosen or m['score'] > chosen[mint][1]['score']: chosen[mint] = (pool, m)
    ranked = sorted(chosen.values(), key=lambda item:(not item[1]['priority'], -item[1]['score']))
    for pool, m in ranked[:6]:
        if api.REQUEST_DEADLINE and time.monotonic() >= api.REQUEST_DEADLINE-12:
            report['budget_exhausted'] = True; break
        mint = pool['baseToken']['address']; pair = pool['pairAddress']
        if already_delivered(state, mint, 'STRONG SIGNAL', time.time()): continue
        # Already-watched tokens get expensive checks only when market conditions can promote them.
        if already_delivered(state, mint, 'EARLY WATCH', time.time()) and not m['strong']: continue
        sec = evidence.security(mint, api, time.time())
        if sec['reject']:
            reason = sec['reject']; report['rejected'][reason] = report['rejected'].get(reason, 0)+1; continue
        metadata_key = hashlib.sha256(json.dumps(social_links(pool), sort_keys=True).encode()).hexdigest()[:16]
        social = cached(state, 'social:'+mint+':'+metadata_key, time.time(), 900, lambda:evidence.community(pool, api, time.time()))
        creation = cached(state, 'mint:'+mint, time.time(), 3600, lambda:evidence.mint_creation(mint, api, time.time()))
        if creation.get('verified'): creation['age_seconds'] = time.time()-creation['created_at']
        buyers = evidence.buyers(pool, api, time.time(), gecko)
        try:
            fresh = refresh(pair, mint, api, gecko)
            # Carry observed cross-source conflicts into the final decision.
            for flag in ('identityConflict','ageConflict'):
                if pool.get(flag): fresh[flag] = True
            # Social fields may be absent from a single-pair refresh; the inspected evidence remains timestamped.
            m = market(fresh, state['observations'], time.time())
            fresh_links, fresh_conflicts = social_links(fresh)
            if fresh_conflicts or any(v and v != social['metadata_links'].get(k) for k,v in fresh_links.items()):
                social = {'score':None, 'complete':False, 'risks':['Metadata komunitas berubah saat pemeriksaan'], 'metadata_links':fresh_links, 'verified_links':{}, 'x':{'status':'metadata_changed'}, 'telegram':{'status':'metadata_changed'}}
            pool = fresh
        except Exception:
            report['rejected']['refresh_unavailable'] = report['rejected'].get('refresh_unavailable', 0)+1; continue
        tier = choose_tier(m, sec, social, buyers, creation)
        reason = evidence_rejection(m, sec, buyers, creation)
        if reason: report['rejected'][reason] = report['rejected'].get(reason,0)+1
        summary = {'mint': mint, 'tier': tier, 'market_score': m.get('score'), 'security_score': sec['score'],
                   'community_score': social['score'], 'x_status': social['x']['status'],
                   'telegram_status': social['telegram']['status'], 'unique_buyers': buyers.get('unique_buyers'),
                   'mint_age_status': creation['status'], 'rejection':reason,
                   'cap_basis':m.get('cap_basis'), 'market_source':pool.get('dataSource','dexscreener')}
        report['candidates'].append(summary)
        if tier and deliver(state, api, chat, pool, m, sec, social, buyers, creation, tier):
            report['sent'] += 1
            if report['sent'] >= 5: break
    report['watchlist_size'] = len(state.get('pool_watchlist',{})); report['gecko_budget_limited'] = gecko.limited
    report['health'] = 'degraded' if not pools or any(v!='ok' for v in discovery.get('sources',{}).values()) else 'ok'
    previous = state.get('last_scan',{}).get('at')
    if isinstance(previous,(int,float)) and now >= previous: report['seconds_since_previous_scan'] = round(now-previous)
    state['last_scan'] = report; migrate(state, time.time()); checkpoint(state, api, durable=True)
    Path('reports').mkdir(exist_ok=True)
    Path('reports/latest.json').write_text(json.dumps(report, indent=2))
    Path('reports/performance.json').write_text(json.dumps({'note':'Observed price changes; not executed profit; excludes fees/slippage.', 'summary':performance_summary(state), 'signals':state['performance']}, indent=2))
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path,'a',encoding='utf-8') as output:
            output.write(f'\n### Scanner v2.1 — ALERT ONLY\n\nPool diperiksa: {report["seen"]}. Alert baru: {report["sent"]}. Kondisi data: {report["health"]}.\n\n')
            output.write('Penolakan: `'+json.dumps(report['rejected'],sort_keys=True)+'`.\n\n')
            output.write('Data kosong: `'+json.dumps(report['missing_fields'],sort_keys=True)+'`.\n\n')
            output.write('Performa ini pengamatan harga, bukan laba transaksi. '+json.dumps(performance_summary(state))+'\n')
    print('SCANNER_V2 '+json.dumps(report, sort_keys=True))
