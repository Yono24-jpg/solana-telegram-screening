"""Alert-only screening. Never loads wallet keys or sends transactions."""
import base64, html, json, math, os, struct, time, urllib.request, urllib.error
from pathlib import Path
from signal_quality import observe, assess, merge_observations
DEX='https://api.dexscreener.com'
PROGRAM='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
KEYBOARD={'inline_keyboard':[[{'text':'🟢 ON','callback_data':'on'},{'text':'🔴 OFF','callback_data':'off'}]]}
STATE=Path('state.json')
MIN_POOL_AGE=300
MAX_POOL_AGE=18000
MIN_LIQUIDITY=10000
MIN_VOLUME_5M=1500
MIN_BUYS_5M=12
MIN_BUY_SELL_RATIO=1.5
REQUEST_DEADLINE=None

def request(url, data=None):
    remaining=18 if REQUEST_DEADLINE is None else REQUEST_DEADLINE-time.monotonic()
    if remaining<=0: raise TimeoutError('Scan time budget exhausted')
    raw=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url, data=raw, headers={'Content-Type':'application/json','User-Agent':'SolanaScreening/1.0'})
    with urllib.request.urlopen(req,timeout=min(8,remaining)) as r:
        return json.load(r)

def tg(method, **args):
    try:
        for attempt in range(3):
            try:
                result=request('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/'+method,args)
                break
            except urllib.error.HTTPError as temporary:
                if temporary.code not in (500,502,503,504) or attempt==2 or method=='sendMessage':
                    raise
                print(f'TELEGRAM_TEMPORARY_ERROR method={method} http={temporary.code} retry={attempt+1}')
                time.sleep(2*(attempt+1))
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as temporary:
                if attempt==2 or method=='sendMessage':
                    raise
                print(f'TELEGRAM_TEMPORARY_TRANSPORT_ERROR method={method} retry={attempt+1}')
                time.sleep(2*(attempt+1))
    except urllib.error.HTTPError as error:
        reason='unclassified'
        try:
            description=json.loads(error.read()).get('description','').lower()
            for phrase in ('chat not found','unauthorized','not found','bot was kicked','bot is not a member','not enough rights','need administrator rights','chat_write_forbidden','group chat was upgraded','webhook is active','terminated by other getupdates','too many requests'):
                if phrase in description:
                    reason=phrase.replace(' ','_');break
        except Exception: pass
        print(f'TELEGRAM_ERROR method={method} http={error.code} reason={reason}')
        raise RuntimeError('Telegram request failed') from None
    except Exception:
        print(f'TELEGRAM_ERROR method={method} reason=transport_or_invalid_configuration')
        raise RuntimeError('Telegram request failed') from None
    print(f'TELEGRAM_API_OK method={method}')
    if not result.get('ok'): raise RuntimeError('Telegram rejected '+method)
    return result['result']

def numeric(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def market_rejection(p, now):
    if not isinstance(p,dict): return 'invalid_identity'
    try:
        identity=(p['baseToken']['address'],p['pairAddress'])
        if (p['chainId']!='solana' or not all(isinstance(x,str) and x and len(x)<=64 and x.isascii() and x.isalnum() for x in identity)
                or not isinstance(p['baseToken']['symbol'],str) or not p['baseToken']['symbol']):
            return 'invalid_identity'
        if not numeric(p['pairCreatedAt']): return 'missing_metrics'
        created=p['pairCreatedAt']/1000
        lp=p['liquidity']['usd']; volume=p['volume']['m5']
        buys=p['txns']['m5']['buys']; sells=p['txns']['m5']['sells']
        if not all(numeric(v) for v in (created,lp,volume,buys,sells)):
            return 'missing_metrics'
        if not MIN_POOL_AGE<=now-created<=MAX_POOL_AGE: return 'age'
        if lp<MIN_LIQUIDITY: return 'liquidity'
        if volume<MIN_VOLUME_5M: return 'volume_5m'
        if buys<MIN_BUYS_5M or sells<0 or int(buys)!=buys or int(sells)!=sells: return 'transactions_5m'
        if buys/max(sells,1)<MIN_BUY_SELL_RATIO: return 'buy_sell_ratio'
        return None
    except (KeyError,TypeError,ValueError,OverflowError,ZeroDivisionError):
        return 'missing_metrics'

def candidate(p, now):
    if market_rejection(p,now) is not None: return None
    try:
        lp=p['liquidity']['usd']; volume=p['volume']['m5']
        buys=p['txns']['m5']['buys']; sells=p['txns']['m5']['sells']
        return dict(p,score=0.4*math.log1p(lp)+0.35*math.log1p(volume)+0.25*math.log1p(buys/max(sells,1)))
    except (KeyError,TypeError,ValueError,OverflowError): return None

def crash_risk_reason(p):
    """Reject sharply falling or unverified momentum immediately before alert."""
    try:
        changes=p['priceChange']
        m5=changes['m5']
        h1=changes['h1']
        if not numeric(m5) or not numeric(h1):
            return 'unverified_price_change'
        if m5 < -15 or h1 < -30:
            return 'rapid_price_drop'
        # Avoid chasing tokens already pumping sharply before alert.
        if m5 > 25 or h1 > 80:
            return 'already_pumped'
        return None
    except (KeyError, TypeError, ValueError):
        return 'unverified_price_change'

def market_cap(p):
    value=p.get('marketCap')
    return value if numeric(value) and value>0 else None

def liquidity_risk_reason(p):
    """Conservative liquidity depth check, not verification of LP lock."""
    try:
        lp=p['liquidity']['usd']
        cap=market_cap(p)
        if not numeric(lp) or cap is None:
            return 'unverified_liquidity_or_cap'
        if lp < MIN_LIQUIDITY:
            return 'low_liquidity'
        if lp / cap < 0.08:
            return 'thin_liquidity_relative_to_cap'
        return None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 'unverified_liquidity_or_cap'

def rugcheck_risk_reason(report):
    """Reject provider danger flags; missing evidence fails closed."""
    if not isinstance(report,dict) or not isinstance(report.get('risks'),list):
        return 'unverified_risk_report'
    for risk in report['risks']:
        if not isinstance(risk,dict) or not isinstance(risk.get('level'),str):
            return 'unverified_risk_report'
        if risk['level'].lower() in ('danger','critical'):
            return 'danger_risk_flag'
    score=report.get('score_normalised')
    if not numeric(score) or not 0<=score<=100:
        return 'unverified_risk_score'
    if score>=60:
        return 'high_risk_score'
    return None

def token2022_extension_ids(data):
    """Inspect canonical Token-2022 mint TLV; malformed layouts fail closed."""
    if len(data)==82: return []
    if len(data)<166 or any(data[82:165]) or data[165]!=1:
        raise ValueError('invalid_token2022_mint_layout')
    ids=[]
    pos=166
    while pos<len(data):
        if len(data)-pos<4:
            raise ValueError('truncated_extension_header')
        kind,size=struct.unpack_from('<HH',data,pos)
        pos+=4
        if kind==0:
            if size!=0 or any(data[pos:]):
                raise ValueError('invalid_extension_padding')
            break
        if size>len(data)-pos:
            raise ValueError('invalid_extension')
        if kind==18 and size!=64:
            raise ValueError('invalid_metadata_pointer')
        if kind==19 and size<64:
            raise ValueError('invalid_token_metadata')
        ids.append(kind)
        pos+=size
    if len(ids)!=len(set(ids)):
        raise ValueError('duplicate_extension')
    return ids

def security_reason(account):
    """Fail closed, but distinguish missing RPC accounts from unsafe mint authority."""
    if account is None: return 'account_missing'
    try:
        owner=account['owner']
        if owner not in (PROGRAM,TOKEN_2022): return 'unsupported_token_program'
        if account['executable']: return 'executable_account'
        if account['data'][1]!='base64': return 'unsupported_encoding'
        b=base64.b64decode(account['data'][0],validate=True)
        # Token-2022 extensions may alter transfer rules, fees, or delegate powers.
        # Only accept an extension-free, canonical 82-byte mint account.
        if owner==TOKEN_2022:
            try:
                extension_ids=token2022_extension_ids(b)
            except ValueError:
                return 'token2022_invalid_extension_layout'
            # Only metadata-only extensions: no transfer hooks, fees or delegates.
            if any(kind not in (18,19) for kind in extension_ids):
                return 'token2022_extensions_unverified'
        elif len(b)!=82: return 'invalid_mint_layout'
        if b[45]!=1: return 'uninitialized_mint'
        if struct.unpack_from('<I',b,0)[0]!=0: return 'mint_authority_active'
        if struct.unpack_from('<I',b,46)[0]!=0: return 'freeze_authority_active'
        return None
    except (KeyError,TypeError,ValueError,IndexError,struct.error):
        return 'invalid_rpc_account'

def secure(account):
    return security_reason(account) is None

def discover():
    # Keep API recency ordering; alphabetical truncation misses newer tokens.
    addresses=list()
    seen=set()
    for endpoint in ['/token-profiles/latest/v1','/token-boosts/latest/v1','/token-boosts/top/v1','/community-takeovers/latest/v1','/ads/latest/v1']:
        try:
            rows=request(DEX+endpoint)
            if isinstance(rows,list):
                for row in rows:
                    if not isinstance(row,dict): continue
                    mint=row.get('tokenAddress')
                    if row.get('chainId')=='solana' and isinstance(mint,str) and mint and mint not in seen:
                        seen.add(mint)
                        addresses.append(mint)
        except Exception: print('Discovery source unavailable; skipped endpoint='+endpoint)
    pools=[]
    for i in range(0,min(len(addresses),240),30):
        try:
            data=request(DEX+'/tokens/v1/solana/'+','.join(addresses[i:i+30]))
            if isinstance(data,list): pools.extend(data)
        except Exception: print('Pool batch unavailable; skipped')
    # Free new-pool feed: GeckoTerminal, then normalize through DexScreener.
    # Failure of this optional feed never bypasses market/security checks.
    gecko_pairs=[]
    seen_gecko=set()
    pages_ok=0
    for page in (1,2,3):
        try:
            feed=request(f'https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page={page}')
            if not isinstance(feed,dict) or not isinstance(feed.get('data'),list):
                raise ValueError('Invalid Gecko pool feed')
            pages_ok+=1
            for item in feed['data']:
                if not isinstance(item,dict): continue
                attrs=item.get('attributes') or {}
                address=attrs.get('address') if isinstance(attrs,dict) else None
                if isinstance(address,str) and address and address not in seen_gecko:
                    seen_gecko.add(address)
                    gecko_pairs.append(address)
        except Exception:
            print(f'GECKO_DISCOVERY_UNAVAILABLE page={page}')
    added=0
    batch_failures=0
    for i in range(0,len(gecko_pairs),20):
        batch=gecko_pairs[i:i+20]
        try:
            data=request(DEX+'/latest/dex/pairs/solana/'+','.join(batch))
            if not isinstance(data,dict): raise ValueError('Invalid DexScreener pair response')
            for pool in data.get('pairs') or []:
                if (isinstance(pool,dict) and pool.get('chainId')=='solana'
                        and pool.get('pairAddress') in batch):
                    pools.append(pool)
                    added+=1
        except Exception:
            batch_failures+=1
    # A missing 5m field must never be treated as zero or as a passing metric.
    # Report missing keys separately to distinguish feed coverage from weak markets.
    missing_counts={}
    for pool in pools:
        if not isinstance(pool,dict): continue
        for name,keys in (('created',('pairCreatedAt',)),('liquidity',('liquidity','usd')),('volume_5m',('volume','m5')),('buys_5m',('txns','m5','buys')),('sells_5m',('txns','m5','sells'))):
            value=pool
            for key in keys:
                value=value.get(key) if isinstance(value,dict) else None
            if not numeric(value):
                missing_counts[name]=missing_counts.get(name,0)+1
    print('DISCOVERY_MISSING_FIELDS '+json.dumps(missing_counts,sort_keys=True))
    print(f'GECKO_DISCOVERY pools={len(gecko_pairs)} normalized={added} pages_ok={pages_ok} batch_failures={batch_failures}')
    print(f'DISCOVERY addresses={len(addresses)} pools={len(pools)}')
    return pools

def holder_concentration(mint):
    """Conservative concentration gate: top token accounts, not distinct wallets."""
    rpc=os.environ.get('SOLANA_RPC_URL') or 'https://api.mainnet-beta.solana.com'
    def call(method,params):
        for attempt in range(3):
            try:
                result=request(rpc,{'jsonrpc':'2.0','id':1,'method':method,'params':params})
                if not isinstance(result,dict) or 'error' in result: raise ValueError('holder RPC error')
                return result['result']['value']
            except urllib.error.HTTPError as error:
                if error.code!=429 or attempt==2: raise
                print('HOLDER_RPC_RATE_LIMIT retry='+str(attempt+1))
                time.sleep(2*(attempt+1))
    supply=call('getTokenSupply',[mint,{'commitment':'confirmed'}])
    largest=call('getTokenLargestAccounts',[mint,{'commitment':'confirmed'}])
    total=int(supply['amount'])
    if total<=0 or not isinstance(largest,list) or len(largest)<10:
        raise ValueError('insufficient holder data')
    amounts=[int(a['amount']) for a in largest[:10]]
    if any(x<0 for x in amounts): raise ValueError('invalid holder balances')
    pct=100*sum(amounts)/total
    if not 0<=pct<=100.000001: raise ValueError('invalid holder concentration')
    return pct

def refresh_watchlist(pools, state, now):
    """Keep observing new pools after they leave the latest-discovery pages."""
    history=merge_observations(state.get('observations',{}),now=now)
    present={p.get('pairAddress') for p in pools if isinstance(p,dict) and isinstance(p.get('pairAddress'),str)}
    watched=[pair for pair,rows in history.items() if pair not in present
             and pair.isascii() and pair.isalnum() and len(pair)<=64][:80]
    refreshed=[]
    for i in range(0,len(watched),20):
        batch=watched[i:i+20]
        try:
            response=request(DEX+'/latest/dex/pairs/solana/'+','.join(batch))
            for pool in response.get('pairs') or []:
                if (isinstance(pool,dict) and pool.get('chainId')=='solana'
                        and pool.get('pairAddress') in batch):
                    refreshed.append(pool)
        except Exception:
            print('WATCHLIST_BATCH_UNAVAILABLE')
    print(f'WATCHLIST_REFRESH requested={len(watched)} received={len(refreshed)}')
    return pools+refreshed

def scan(state, chat):
    selected={}
    stats={'pools_seen':0,'market_rejected':0,'already_sent':0,'security_rejected':0,'market_expired':0,'refresh_rejected':0,'refresh_error':0}
    pools=refresh_watchlist(discover(),state,time.time())
    observe(state,pools,time.time())
    save(state)
    for p in pools:
        stats['pools_seen']+=1
        # Sent tokens must not consume any of the 30 security-check slots.
        if isinstance(p,dict) and isinstance(p.get('baseToken'),dict):
            mint=p['baseToken'].get('address')
            if isinstance(mint,str) and mint in state['sent']:
                stats['already_sent']+=1
                continue
        c=candidate(p,time.time())
        if c:
            cheap_reason=liquidity_risk_reason(c) or crash_risk_reason(c)
            quality_reason,quality=assess(c,state['observations'],time.time())
            rejection=cheap_reason or quality_reason
            if rejection:
                stats['quality_'+rejection]=stats.get('quality_'+rejection,0)+1
                continue
            c['quality']=quality
            mint=c['baseToken']['address']
            if mint not in selected or selected[mint]['quality']['score']<quality['score']: selected[mint]=c
        else:
            stats['market_rejected']+=1
            reason=market_rejection(p,time.time()) or 'unknown_market'
            stats['market_'+reason]=stats.get('market_'+reason,0)+1
    ranked=sorted(selected.values(),key=lambda p:p['quality']['score'],reverse=True)
    # Explicitly show how many market-qualified mints use a supported token
    # program. Never downgrade the token-program requirement to boost alerts.
    print(f'MARKET_QUALIFIED unique_mints={len(ranked)}')
    sent=0
    # Check only bounded candidates, but never fill slots using unverified data.
    ranked=ranked[:30]
    if not ranked:
        print(f'SCAN candidates=0 sent=0 diagnostics={json.dumps(stats,sort_keys=True)}'); return
    try:
        result=request((os.environ.get('SOLANA_RPC_URL') or 'https://api.mainnet-beta.solana.com'),{'jsonrpc':'2.0','id':1,'method':'getMultipleAccounts','params':[[p['baseToken']['address'] for p in ranked],{'encoding':'base64','commitment':'confirmed'}]})
        accounts=result['result']['value']
        if len(accounts)!=len(ranked): raise ValueError('Incomplete RPC data')
    except Exception:
        print(f'Security unavailable: all candidates discarded diagnostics={json.dumps(stats,sort_keys=True)}');return
    # Diagnose market-qualified token identity without exposing wallet secrets.
    # A non-SPL owner remains a hard rejection, never an allowlist bypass.
    owner_counts={}
    for p,a in zip(ranked,accounts):
        owner=a.get('owner','missing_owner') if isinstance(a,dict) else 'missing_account'
        owner_counts[owner]=owner_counts.get(owner,0)+1
    print('SECURITY_OWNER_PROGRAMS '+json.dumps(owner_counts,sort_keys=True))
    holder_rpc_rate_limited=False
    for p,a in zip(ranked,accounts):
        if REQUEST_DEADLINE is not None and time.monotonic()>=REQUEST_DEADLINE:
            stats['time_budget_exhausted']=1
            break
        mint=p['baseToken']['address']
        if mint in state['sent']:
            stats['already_sent']+=1;continue
        reason=security_reason(a)
        if reason is not None:
            stats['security_rejected']+=1
            stats['security_'+reason]=stats.get('security_'+reason,0)+1
            continue
        # A provider-wide HTTP 429 is not a token-specific failure. Stop
        # requesting holder data this scan; reject every unverified candidate.
        if holder_rpc_rate_limited:
            stats['holder_rate_limited_skipped']=stats.get('holder_rate_limited_skipped',0)+1
            print('HOLDER_GATE_UNAVAILABLE mint='+mint+' reason=rpc_rate_limit_circuit_open')
            continue
        try:
            top_accounts_pct=holder_concentration(mint)
        except urllib.error.HTTPError as error:
            print('HOLDER_GATE_DIAGNOSTIC type=HTTPError http='+str(error.code))
            stats['holder_unavailable']=stats.get('holder_unavailable',0)+1
            if error.code==429:
                holder_rpc_rate_limited=True
                print('HOLDER_RPC_CIRCUIT_OPEN: remaining candidates fail closed this scan')
            print('HOLDER_GATE_UNAVAILABLE mint='+mint)
            continue
        except Exception as error:
            print('HOLDER_GATE_DIAGNOSTIC type='+type(error).__name__)
            stats['holder_unavailable']=stats.get('holder_unavailable',0)+1
            print('HOLDER_GATE_UNAVAILABLE mint='+mint)
            continue
        if top_accounts_pct>30:
            stats['holder_over_30']=stats.get('holder_over_30',0)+1
            print('HOLDER_GATE_REJECT mint='+mint+' top10_accounts_pct='+str(round(top_accounts_pct,2)))
            continue
        if not candidate(p,time.time()):
            stats['market_expired']+=1;continue
        # Refresh market metrics immediately before sending.
        try:
            latest=request(DEX+'/latest/dex/pairs/solana/'+p['pairAddress'])['pairs']
            fresh=next(x for x in latest if x['pairAddress']==p['pairAddress'] and x['baseToken']['address']==mint)
            p=candidate(fresh,time.time())
            if p is not None and (market_cap(p) is None):
                stats['refresh_rejected']+=1;continue
            if not p:
                stats['refresh_rejected']+=1;continue
        except Exception:
            stats['refresh_error']+=1;continue
        lp_reason=liquidity_risk_reason(p)
        if lp_reason:
            stats['liquidity_'+lp_reason]=stats.get('liquidity_'+lp_reason,0)+1
            print('LIQUIDITY_GATE_REJECT mint='+mint+' reason='+lp_reason)
            continue
        try:
            risk_report=request('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report/summary')
            risk_reason=rugcheck_risk_reason(risk_report)
        except Exception:
            risk_reason='risk_provider_unavailable'
        if risk_reason:
            stats['rugcheck_'+risk_reason]=stats.get('rugcheck_'+risk_reason,0)+1
            print('RUGCHECK_GATE_REJECT mint='+mint+' reason='+risk_reason)
            continue
        crash_reason=crash_risk_reason(p)
        if crash_reason:
            stats['momentum_'+crash_reason]=stats.get('momentum_'+crash_reason,0)+1
            print('MOMENTUM_GATE_REJECT mint='+mint+' reason='+crash_reason)
            continue
        # Slow holder/risk requests must not let an expired pool reach Telegram.
        if candidate(p,time.time()) is None:
            stats['market_expired']+=1
            continue
        quality_reason,quality=assess(p,state['observations'],time.time())
        if quality_reason:
            stats['quality_'+quality_reason]=stats.get('quality_'+quality_reason,0)+1
            continue
        holder_info=f'📊 10 akun token terbesar: <b>{top_accounts_pct:.2f}%</b> (bukan Top 10 wallet)\n'
        symbol=html.escape(p['baseToken']['symbol'][:40]); age=int(time.time()-p['pairCreatedAt']/1000)
        text=(f'🔎 <b>KANDIDAT AWAL SOLANA | {symbol}</b>\n'
              '━━━━━━━━━━━━━━━━━━\n'
              f"🎯 Skor filter: <b>{quality['score']:.0f}/100</b> (bukan probabilitas untung)\n"
              f'⏱ Umur pool: <b>{age//60} menit</b>\n'
              'ℹ️ Umur mint belum diverifikasi; pool baru bisa berisi token lama.\n'
              f"💰 Market cap: <b>${market_cap(p):,.0f}</b>\n"
              f"💧 Likuiditas: <b>${p['liquidity']['usd']:,.0f}</b>\n"
              f"📊 Volume 5m: <b>${p['volume']['m5']:,.0f}</b>\n"
              f"🟢 BUY / 🔴 SELL (5m): <b>{p['txns']['m5']['buys']} / {p['txns']['m5']['sells']}</b>\n"
              '━━━━━━━━━━━━━━━━━━\n'
              '📈 <b>ALASAN LOLOS</b>\n'
              f"• Porsi transaksi BUY: <b>{quality['buy_share']:.1f}%</b>\n"
              f"• Volume 5m: <b>{quality['volume_growth']:.2f}×</b> dibanding {quality['comparison_minutes']:.0f} menit lalu\n"
              f"• Likuiditas tersisa: <b>{quality['liquidity_retention']:.1f}%</b> dari pembanding\n"
              f"• Harga 5m / 1j: <b>{quality['m5']:+.1f}% / {quality['h1']:+.1f}%</b>\n"
              '━━━━━━━━━━━━━━━━━━\n'
              '🛡 <b>KEAMANAN</b>\n'
              '✅ Mint authority: nonaktif\n'
              '✅ Freeze authority: nonaktif\n'
              '✅ Tidak ada flag bahaya dari pemeriksaan RugCheck\n'
              f'{holder_info}'
              '⚠️ Top 10 wallet: cek manual\n'
              '━━━━━━━━━━━━━━━━━━\n'
              '📋 <b>MINT (ketuk untuk salin)</b>\n'
              f'<code>{html.escape(mint)}</code>\n'
              '━━━━━━━━━━━━━━━━━━\n'
              '🔗 <b>BUKA CHART</b>\n'
              f'<a href="https://dexscreener.com/solana/{p["pairAddress"]}">📈 DexScreener</a>  |  '
              f'<a href="https://axiom.trade/t/{mint}">⚡ Axiom</a>\n\n'
              '⚠️ Kandidat lolos filter, bukan jaminan aman atau profit.')
        # Do not retry ambiguous send failures: avoid duplicate delivery.
        msg=tg('sendMessage',chat_id=chat,text=text,parse_mode='HTML',reply_markup=KEYBOARD,disable_web_page_preview=True)
        state['sent'][mint]=int(time.time()); save(state)
        print('TELEGRAM_SENT message_id='+str(msg['message_id']))
        sent+=1
        if sent==5: break
    print(f'SCAN checked={len(ranked)} sent={sent} diagnostics={json.dumps(stats,sort_keys=True)}')

def save(state):
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.replace(STATE)

def main():
    global REQUEST_DEADLINE
    # Bound network work so repeated scans leave time for state persistence.
    REQUEST_DEADLINE=time.monotonic()+30
    chat=os.environ['TELEGRAM_CHAT_ID']
    state=json.loads(STATE.read_text()) if STATE.exists() else {'enabled':False,'offset':0,'sent':{},'initialized':False}
    identity=tg('getMe')
    username=identity.get('username','')
    if isinstance(username,str) and username.replace('_','').isalnum():
        print('TELEGRAM_BOT username=@'+username)
    group=tg('getChat',chat_id=chat)
    if group['type'] not in ('group','supergroup','channel'):
        print('TELEGRAM_ERROR reason=unsupported_destination_type')
        raise RuntimeError('Destination must be a Telegram group or channel')
    print('TELEGRAM_DESTINATION_OK type='+group['type'])
    chat=group['id']
    if not state['initialized']:
        msg=tg('sendMessage',chat_id=chat,text='✅ Scanner pool baru Solana tersambung. Umur pool 1 menit–24 jam; prioritas 1–60 menit. EARLY WATCH dan STRONG SIGNAL; maksimal 5 kandidat per scan. Klik ON untuk mulai. Tanpa trading otomatis.',reply_markup=KEYBOARD)
        print('TELEGRAM_TEST_OK message_id='+str(msg['message_id']))
        state['initialized']=True;save(state)
    updates=tg('getUpdates',offset=state['offset'],timeout=0,allowed_updates=['callback_query'])
    for u in updates:
        q=u.get('callback_query',{});message=q.get('message',{})
        if str(message.get('chat',{}).get('id'))==str(chat) and q.get('data') in ('on','off'):
            member=tg('getChatMember',chat_id=chat,user_id=q['from']['id'])
            if member.get('status') in ('creator','administrator'):
                requested=q['data']=='on'
                if state['enabled']!=requested:
                    state['enabled']=requested;save(state)
                    tg('sendMessage',chat_id=chat,text='🟢 Screening ON' if requested else '🔴 Screening OFF',reply_markup=KEYBOARD)
            try: tg('answerCallbackQuery',callback_query_id=q['id'])
            except Exception: pass
        state['offset']=u['update_id']+1;save(state)
    state['sent']={k:v for k,v in state['sent'].items() if isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=time.time()-v<172800}
    save(state)
    if state['enabled']:
        # Keep the original scan() for rollback and its regression tests.
        # Telegram control latency must not consume the market-evidence budget.
        import sys
        from scanner_v2 import run
        REQUEST_DEADLINE=time.monotonic()+100
        run(state,chat,sys.modules[__name__])
    else: print('SCREENING_OFF')

if __name__=='__main__':
    try: main()
    except Exception:
        # Exception URLs can contain bot credentials: never log them.
        print('RUN_FAILED: check secret configuration, Telegram access and API availability');raise SystemExit(1)


