"""Alert-only screening. Never loads wallet keys or sends transactions."""
import base64, html, json, math, os, struct, time, urllib.request, urllib.error
from pathlib import Path
DEX='https://api.dexscreener.com'
PROGRAM='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
KEYBOARD={'inline_keyboard':[[{'text':'🟢 ON','callback_data':'on'},{'text':'🔴 OFF','callback_data':'off'}]]}
STATE=Path('state.json')

def request(url, data=None):
    raw=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url, data=raw, headers={'Content-Type':'application/json','User-Agent':'SolanaScreening/1.0'})
    with urllib.request.urlopen(req,timeout=18) as r:
        return json.load(r)

def tg(method, **args):
    try:
        result=request('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/'+method,args)
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

def candidate(p, now):
    try:
        created=p['pairCreatedAt']/1000
        lp=p['liquidity']['usd']; volume=p['volume']['m5']
        buys=p['txns']['m5']['buys']; sells=p['txns']['m5']['sells']
        if p['chainId']!='solana' or not p['baseToken']['address'] or not p['pairAddress']: return None
        if not p['baseToken']['symbol'] or not all(numeric(v) for v in (created,lp,volume,buys,sells)): return None
        if not 0<=now-created<=3600 or lp<5000 or volume<500 or buys<5 or sells<0: return None
        if int(buys)!=buys or int(sells)!=sells or buys/max(sells,1)<1.0: return None
        return dict(p,score=0.4*math.log1p(lp)+0.35*math.log1p(volume)+0.25*math.log1p(buys/max(sells,1)))
    except (KeyError,TypeError,ValueError,OverflowError): return None

def market_cap(p):
    value=p.get('marketCap')
    return value if numeric(value) and value>0 else None

def secure(account):
    try:
        if account['owner']!=PROGRAM or account['executable']: return False
        if account['data'][1]!='base64': return False
        b=base64.b64decode(account['data'][0],validate=True)
        return len(b)==82 and b[45]==1 and struct.unpack_from('<I',b,0)[0]==0 and struct.unpack_from('<I',b,46)[0]==0
    except (KeyError,TypeError,ValueError,IndexError): return False

def discover():
    # Keep API recency ordering; alphabetical truncation misses newer tokens.
    addresses=list()
    seen=set()
    for endpoint in ['/token-profiles/latest/v1','/token-boosts/latest/v1','/token-boosts/top/v1']:
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
    print(f'DISCOVERY addresses={len(addresses)} pools={len(pools)}')
    return pools

def scan(state, chat):
    selected={}
    stats={'pools_seen':0,'market_rejected':0,'already_sent':0,'security_rejected':0,'market_expired':0,'refresh_rejected':0,'refresh_error':0}
    for p in discover():
        stats['pools_seen']+=1
        c=candidate(p,time.time())
        if c:
            mint=c['baseToken']['address']
            if mint not in selected or selected[mint]['score']<c['score']: selected[mint]=c
        else: stats['market_rejected']+=1
    ranked=sorted(selected.values(),key=lambda p:p['score'],reverse=True)
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
    for p,a in zip(ranked,accounts):
        mint=p['baseToken']['address']
        if mint in state['sent']:
            stats['already_sent']+=1;continue
        if not secure(a):
            stats['security_rejected']+=1;continue
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
        symbol=html.escape(p['baseToken']['symbol'][:40]); age=int(time.time()-p['pairCreatedAt']/1000)
        text=(f'🔎 <b>KANDIDAT SOLANA | {symbol}</b>\n'
              '━━━━━━━━━━━━━━━━━━\n'
              f'⏱ Umur pool: <b>{age//60} menit</b>\n'
              f"💰 Market cap: <b>${market_cap(p):,.0f}</b>\n"
              f"💧 Likuiditas: <b>${p['liquidity']['usd']:,.0f}</b>\n"
              f"📊 Volume 5m: <b>${p['volume']['m5']:,.0f}</b>\n"
              f"🟢 BUY / 🔴 SELL (5m): <b>{p['txns']['m5']['buys']} / {p['txns']['m5']['sells']}</b>\n"
              '━━━━━━━━━━━━━━━━━━\n'
              '🛡 <b>KEAMANAN</b>\n'
              '✅ Mint authority: nonaktif\n'
              '✅ Freeze authority: nonaktif\n'
              '⚠️ Top 10 holder: cek manual\n'
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
    chat=os.environ['TELEGRAM_CHAT_ID']
    state=json.loads(STATE.read_text()) if STATE.exists() else {'enabled':False,'offset':0,'sent':{},'initialized':False}
    tg('getMe')
    group=tg('getChat',chat_id=chat)
    if group['type'] not in ('group','supergroup','channel'):
        print('TELEGRAM_ERROR reason=unsupported_destination_type')
        raise RuntimeError('Destination must be a Telegram group or channel')
    print('TELEGRAM_DESTINATION_OK type='+group['type'])
    chat=group['id']
    if not state['initialized']:
        msg=tg('sendMessage',chat_id=chat,text='✅ Bot screening tersambung. Pool maksimal 1 jam; maksimal 5 token per scan. Klik ON untuk mulai. Tanpa trading otomatis.',reply_markup=KEYBOARD)
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
    state['sent']={k:v for k,v in state['sent'].items() if time.time()-v<86400}
    save(state)
    if state['enabled']: scan(state,chat)
    else: print('SCREENING_OFF')

if __name__=='__main__':
    try: main()
    except Exception:
        # Exception URLs can contain bot credentials: never log them.
        print('RUN_FAILED: check secret configuration, Telegram access and API availability');raise SystemExit(1)
