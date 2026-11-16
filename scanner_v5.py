"""MAIL Global Intelligence v5. ALERT ONLY, strict security across every hunter mode."""
import html
import json
import os
from pathlib import Path
import time
import uuid
import copy
import evidence
import global_intelligence as intelligence
import hunter_memory
import hunter_modes
import market_data
import scanner_v2 as legacy
import security_v3
import social_intelligence
import token_extensions
from signal_quality import snapshot,merge_observations
from state_store import migrate,already_delivered


def render(pool,m,sec,social,buyers,creation,tier):
    esc=lambda x:html.escape(str(x),quote=True)
    n=pool['_narrative_v3']; safety=pool['_security_v3']; mint=pool['baseToken']['address']; pair=pool['pairAddress']
    sources='\n'.join('• <a href="'+esc(a['url'])+'">'+esc(a['publisher'])+'</a>: '+esc(a['title'][:100]) for a in n['sources'][:2])
    scores=' | '.join(k+': '+('belum terukur' if v is None else str(v)+'/100') for k,v in pool['_scores_v5'].items())
    return (f'🔎 <b>MAIL AI Narrative Hunter v5.0</b>\n{esc(pool["baseToken"].get("name","?"))}\n'
            f'Mode: {esc(", ".join(m["modes"]))}\nUmur pool {m["age_seconds"]/60:.1f} menit\n'
            f'MC ${m["cap"]:,.0f} | LP ${m["lp"]:,.0f}\nVolume 1h ${pool["volume"]["h1"]:,.0f}\n'
            f'BUY/SELL 5m {m["buys"]}/{m["sells"]} ({m["buys"]/max(m["sells"],1):.2f}×)\n'
            f'{esc(scores)}\nNarasi: {esc(n["reason"])}\n{sources}\n'
            'Risiko: '+esc('; '.join(safety['risks']))+
            f'\nCA: <code>{esc(mint)}</code>\n<a href="https://dexscreener.com/solana/{esc(pair)}">DexScreener</a> | '
            f'<a href="https://axiom.trade/t/{esc(mint)}">Axiom</a>\n'
            'ALERT ONLY. Skor menentukan prioritas, bukan peluang profit atau jaminan aman.')


def health(state,api,chat,report):
    now=time.time(); migrate(state,now)
    recent=[r for k,r in state['delivery'].items() if k.startswith('health:') and 0<=now-r.get('at',0)<21600]
    if recent: return {'status':'not_due'}
    key='health:'+str(int(now//21600)); claim=uuid.uuid4().hex
    state['delivery'][key]={'at':now,'updated':now,'status':'pending','reservation':claim}
    legacy.checkpoint(state,api,durable=True)
    if state['delivery'].get(key,{}).get('reservation')!=claim: return {'status':'already_reserved'}
    rejects=', '.join(k+': '+str(v) for k,v in sorted(report.get('rejected',{}).items(),key=lambda x:-x[1])[:6]) or 'tidak ada / scanner OFF'
    ai=report.get('narrative',{}).get('ai',{})
    text=(f'🩺 MAIL Hunter v5.0 — laporan kesehatan 6 jam\n'
          f'Scanner: {"ON" if state.get("enabled") else "OFF"} | {report.get("health","unknown")}\n'
          f'Pool: {report.get("seen",0)} | Kandidat terkirim: {report.get("sent",0)}\n'
          f'Penolakan: {rejects}\nAI: {ai.get("status","unavailable")} | Model: {ai.get("model_used") or "tidak digunakan"}\n'
          f'Run: {os.environ.get("GITHUB_RUN_ID","local")}\n'
          'Cakupan: sampel berita global; akses sosial terbatas. Data keamanan penting yang kosong menyebabkan penolakan. ALERT ONLY.')
    try:
        response=api.tg('sendMessage',chat_id=chat,text=text,reply_markup=api.KEYBOARD,disable_web_page_preview=True)
        if not isinstance(response.get('message_id'),int) or response.get('chat',{}).get('id')!=chat: raise ValueError('unverified_delivery')
        state['delivery'][key].update(status='sent',message_id=response['message_id'],updated=time.time())
        out={'status':'sent','message_id':response['message_id']}
        print('TELEGRAM_HEALTH_OK message_id='+str(response['message_id']))
    except Exception:
        state['delivery'][key].update(status='unknown',updated=time.time()); out={'status':'unknown_no_retry'}
    legacy.checkpoint(state,api,durable=True)
    return out


def observe(state,pools,now):
    history=merge_observations(state.get('observations',{}),now=now)
    for p in pools:
        try:
            if not 0<=now-p['pairCreatedAt']/1000<=hunter_modes.MAX_AGE: continue
            row=snapshot(p,now)
            if row:
                rows=history.setdefault(p['pairAddress'],[])
                if not rows or now-rows[-1]['t']>=60: rows.append(row)
        except (KeyError,TypeError,ValueError): continue
    state['observations']=merge_observations(history,now=now)


def run(state,chat,api,dry_run=False):
    now=time.time(); migrate(state,now)
    report={'version':'5.0','at':now,'mode':'ALERT ONLY','seen':0,'sent':0,'rejected':{},'candidates':[],
            'security_checks':[],'trigger':os.environ.get('GITHUB_EVENT_NAME','local'),'run_id':os.environ.get('GITHUB_RUN_ID'),
            'capabilities':{'images':'not_available','influencer_pfp':'not_available_without_account_access',
                'x_reads_enabled':os.environ.get('X_READS_ENABLED')=='1' and bool(os.environ.get('X_BEARER_TOKEN')),
                'whales':'large provider-reported trades; not attributed identities or full wallet tracking', 'organic_vs_paid':'paid boosts observed; organic unproven',
                'memory':'bounded 1500 decisions / 90 days, artifact retention 14 days', 'historical_profit_backtest':'unvalidated'}}
    if state.get('enabled') is False:
        report.update(health='paused'); report['health_notification']={'status':'read_only'} if dry_run else health(state,api,chat,report); write_report(state,api,report); return report
    feed=intelligence.collect(api,state,now)
    report['narrative']={k:v for k,v in feed.items() if k!='articles'}
    gecko=market_data.GeckoClient(api,state)
    pools,report['discovery']=legacy.discover(api,gecko)
    found=intelligence.search_pools(api,feed,time.time()); report['discovery']['dynamic_search_pools']=len(found)
    social_pools,report['social_discovery']=social_intelligence.discover_contracts(api,feed,time.time())
    pools=market_data.merge_pools(pools+found+social_pools)
    pools,report['market_hydration']=market_data.hydrate_incomplete(pools,api,gecko,time.time())
    pools=market_data.refresh_watchlist(pools,state,api,gecko,time.time(),max_age=hunter_modes.MAX_AGE)
    observe(state,pools,time.time())
    # Bounded evaluations, including rejected cases. No invented horizon prices.
    evaluation_deadline=min(api.REQUEST_DEADLINE or float('inf'),time.monotonic()+20)
    hunter_memory.followup(state,pools,api,gecko,evaluation_deadline)
    # Continue existing signal evaluation after the version upgrade.
    old_deadline=api.REQUEST_DEADLINE
    api.REQUEST_DEADLINE=min(old_deadline or float('inf'),time.monotonic()+10)
    try: legacy.followup(state,pools,api,time.time(),gecko)
    finally: api.REQUEST_DEADLINE=old_deadline
    ranked={}; archives=[]
    def reject(reason): report['rejected'][reason]=report['rejected'].get(reason,0)+1
    for pool in pools:
        report['seen']+=1
        n=intelligence.match(pool,feed,time.time()); m=hunter_modes.assess(pool,state['observations'],time.time(),n)
        reason=m.get('reject')
        # Archive a representative, bounded sample of rejects and all market/narrative candidates.
        if len(archives)<30 or not reason:
            archives.append({'observed_at':time.time(),'pool':copy.deepcopy(pool),'articles':n.get('sources',[]),
                             'decision':reason or 'awaiting_security'})
            hunter_memory.record(state,pool,n,reason or 'awaiting_security',time.time())
        if reason: reject(reason); continue
        mint=pool['baseToken']['address']
        if mint not in ranked or m['score']>ranked[mint][1]['score']: ranked[mint]=(pool,m,n)
    for pool,m,n in sorted(ranked.values(),key=lambda r:(not r[1]['priority'],-r[1]['score']))[:6]:
        if api.REQUEST_DEADLINE and time.monotonic()>=api.REQUEST_DEADLINE-25:
            report['budget_exhausted']=True; break
        mint=pool['baseToken']['address']; pair=pool['pairAddress']
        if any(k.startswith(mint+':') for k in state['delivery']) or already_delivered(state,mint,'GLOBAL SIGNAL',time.time()): continue
        sec=evidence.security(mint,api,time.time(),pool=pool,mint_validator=token_extensions.audit)
        summary={'mint':mint,'pair':pair,'extensions':sec.get('extensions'), 'base_rejection':sec.get('reject')}
        report['security_checks'].append(summary)
        if sec.get('reject') or not sec.get('complete'):
            reason=sec.get('reject') or 'base_security_incomplete'; reject(reason); hunter_memory.record(state,pool,n,reason,time.time()); continue
        buyers=evidence.buyers(pool,api,time.time(),gecko)
        safety=security_v3.inspect(pool,sec,buyers,api,time.time(),extension_proof=sec.get('extensions'))
        safety['observed_at']=time.time()
        summary['security']=safety
        summary['large_trade_sample']=[{k:r.get(k) for k in ('signature','wallet','kind','usd')} for r in buyers.get('transactions',[]) if (r.get('usd') or 0)>=10000][:10]
        summary['buyers']=social_intelligence.observe_buyers(state,mint,buyers,time.time())
        if safety.get('reject') or not safety.get('complete'):
            reason=safety.get('reject') or 'security_incomplete';reject(reason);hunter_memory.record(state,pool,n,reason,time.time(),safety);continue
        social=evidence.community(pool,api,time.time())
        public=social_intelligence.sample(api,n['label'],mint,time.time())
        signals=social_intelligence.observe(state,mint,social,public,pool,time.time())
        n['virality_score']=signals.get('virality_score')
        # Same mint/pair fresh quote must still satisfy every market/narrative gate.
        try: fresh=legacy.refresh(pair,mint,api,gecko)
        except Exception: reject('refresh_unavailable');continue
        n2=intelligence.match(fresh,feed,time.time()); n2['virality_score']=n['virality_score']
        m=hunter_modes.assess(fresh,state['observations'],time.time(),n2)
        if m.get('reject'): reject(m['reject']);continue
        # Reject quote metadata changes rather than attaching stale community evidence.
        from screening_rules import social_links
        fresh_links,conflicts=social_links(fresh)
        if conflicts or any(v and v!=social.get('metadata_links',{}).get(k) for k,v in fresh_links.items()): reject('community_metadata_changed');continue
        if social.get('risks'): reject('community_risk_flag');continue
        fresh['_narrative_v3']=n2; fresh['_security_v3']=safety
        fresh['_scores_v5']=hunter_modes.scores(n2,m,safety,social,buyers)
        report['candidates'].append({'mint':mint,'modes':m['modes'],'scores':fresh['_scores_v5'],'social_sample':signals})
        archives.append({'observed_at':time.time(),'pool':copy.deepcopy(fresh), 'articles':n2.get('sources',[]),
                         'security_observed_at':safety['observed_at'],'security':safety,'decision':'gates_passed'})
        if not dry_run and legacy.deliver(state,api,chat,fresh,m,sec,social,buyers,{},'GLOBAL SIGNAL',renderer=render):
            report['sent']+=1; hunter_memory.record(state,fresh,n2,'accepted',time.time(),safety)
    report['health']='degraded' if not pools or any(s!='ok' for s in report['discovery']['sources'].values()) or any(s!='ok' for s in feed['sources'].values()) else 'ok'
    report['gecko_budget_limited']=gecko.limited
    report['memory_records']=len(state.get('memory_v5',{}))
    report['evaluations']={str(h):sum(str(h) in r.get('samples',{}) for r in state.get('memory_v5',{}).values()) for h in (300,900,3600,86400)}
    report['health_notification']={'status':'read_only'} if dry_run else health(state,api,chat,report)
    Path('reports').mkdir(exist_ok=True)
    Path('reports/point-in-time-v5.json').write_text(json.dumps(archives,ensure_ascii=False,indent=2))
    Path('reports/performance.json').write_text(json.dumps({'note':'Observed prices only, not executed profit; excludes fees/slippage.','signals':state['performance']},indent=2))
    Path('reports/memory-v5.json').write_text(json.dumps(state.get('memory_v5',{}),indent=2))
    Path('reports/backtest-v5.json').write_text(json.dumps(hunter_memory.replay(sorted(archives,key=lambda a:a['observed_at'])),indent=2))
    write_report(state,api,report)
    return report


def write_report(state,api,report):
    state['last_scan']=report
    state.setdefault('scan_history',[]).append({k:report.get(k) for k in ('at','trigger','run_id','seen','sent')})
    legacy.checkpoint(state,api,durable=True)
    Path('reports').mkdir(exist_ok=True)
    Path('reports/latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write('\n### MAIL Hunter v5.0 — ALERT ONLY\n\n'+f'Pool: {report["seen"]}; alerts: {report["sent"]}; health: {report["health"]}.\n\nPenolakan: '+json.dumps(report['rejected'])+'\n')
    print('SCANNER_V5 '+json.dumps(report,ensure_ascii=False,sort_keys=True))
