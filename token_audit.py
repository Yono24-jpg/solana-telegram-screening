"""Read-only real-token audit. Never imports a delivery path or sends Telegram messages."""
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import bot
import evidence
import market_data
import narrative_v3
import screening_rules
import security_v3
import scanner_v2
import vault_checks

TARGETS = [
    ('Anthropic Inu','GgDHtSGcXn5YrADnpsQSVHFAa5xLwVEuD7FWeRgvpump'),
    ('GRAND THEFT CRYPTO (FiveM)','2YxbK7V6ZTKSxcavk3V4kFzdtZ4uywhhoyuSxapjpump'),
    ('Cyber Dacity Coin','C5X8tVbt8cGw7iaaEuAVGTxFVZ4uSjscmiUbVpVwpump'),
    ('rockstar','9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump'),
]
QUERIES=['Anthropic Inu','GRAND THEFT CRYPTO','FiveM','Cyber Dacity Coin','Rockstar']


def safe_call(fn):
    try:return {'status':'observed','value':fn()}
    except security_v3.EvidenceMissing as error:return {'status':'unavailable','reason':str(error)}
    except Exception:return {'status':'unavailable','reason':'provider_unavailable'}


def all_market_checks(pool, now):
    get=market_data.get;number=screening_rules.number
    age=(now-pool['pairCreatedAt']/1000) if number(pool.get('pairCreatedAt')) else None
    cap=pool.get('marketCap');lp=get(pool,'liquidity.usd');vol=get(pool,'volume.h1')
    buy=get(pool,'txns.m5.buys');sell=get(pool,'txns.m5.sells')
    ratio=buy/max(sell,1) if number(buy) and number(sell) and buy>=0 and sell>=0 else None
    def check(value,ok):return {'value':value,'status':'missing' if value is None else ('pass' if ok else 'reject')}
    result={'age_seconds':check(age,number(age) and 60<=age<=86400),
            'market_cap':check(cap,number(cap) and 20000<=cap<=500000),
            'liquidity':check(lp,number(lp) and lp>=10000),
            'volume_h1':check(vol,number(vol) and vol>=5000),
            'buy_sell_ratio_m5':check(ratio,number(ratio) and ratio>=1.5),
            'buys_m5':buy,'sells_m5':sell,'priority_1_60m':number(age) and 60<=age<=3600,
            'price_change':pool.get('priceChange'),'fdv':pool.get('fdv')}
    changes=pool.get('priceChange') or {}
    result['anti_chase']={'m5_0_to_25':check(changes.get('m5'),number(changes.get('m5')) and 0<=changes['m5']<=25),'h1_minus15_to80':check(changes.get('h1'),number(changes.get('h1')) and -15<=changes['h1']<=80),'h24_at_most_200':check(changes.get('h24'),number(changes.get('h24')) and changes['h24']<=200)}
    return result


def audit_one(name,mint,pool,state,feed,baseline,searches,gecko):
    now=time.time();bot.REQUEST_DEADLINE=time.monotonic()+130
    result={'name':name,'mint':mint,'at':now,'in_original_discovery':mint in baseline,
            'name_search_candidates':[p for rows in searches.values() for p in rows if market_data.get(p,'baseToken.address')==mint]}
    if pool is None:
        result['status']='market_pool_unavailable';return result
    pair=pool['pairAddress']
    result['pair']=pair;result['dex_snapshot']=copy.deepcopy(pool)
    gp=safe_call(lambda:market_data.gecko_pools(gecko.request(market_data.GECKO+'/networks/solana/pools/'+pair+'?include=base_token,quote_token,dex')))
    result['gecko_snapshot']=gp
    native=next((p for p in gp.get('value',[]) if p.get('pairAddress')==pair and market_data.get(p,'baseToken.address')==mint),None)
    selected=market_data.select_pool(pool,native)
    selected_rows,hydration=market_data.hydrate_incomplete([selected],bot,gecko,time.time(),limit=1)
    selected=selected_rows[0];result['target_hydration']=hydration;result['selected_snapshot']=selected
    result['market']=all_market_checks(selected,now)
    result['market_gate']=narrative_v3.market_gate(selected,now)
    result['momentum']=screening_rules.market(selected,state.get('observations',{}),now)
    result['narrative']=narrative_v3.match(selected,feed,now)
    account=safe_call(lambda:evidence.rpc(bot,'getAccountInfo',[mint,{'encoding':'base64','commitment':'finalized'}])['value'])
    sec=None
    if account.get('status')=='observed':
        try:
            a=account['value'];raw=vault_checks.raw_data(a)
            result['onchain_mint']={'program':a['owner'],'mint_authority_revoked':struct.unpack_from('<I',raw,0)[0]==0,
                'freeze_authority_revoked':struct.unpack_from('<I',raw,46)[0]==0,'supply_raw':struct.unpack_from('<Q',raw,36)[0],
                'decimals':raw[44],'mint_initialized':raw[45]==1,'legacy_security_reason':bot.security_reason(a)}
            result['holders']=safe_call(lambda:vault_checks.concentration(selected,a,bot,evidence.rpc))
        except Exception:result['onchain_mint']={'status':'unavailable'}
    else:result['onchain_mint']={'status':'unavailable'}
    result['base_security']=safe_call(lambda:evidence.security(mint,bot,time.time(),pool=selected))
    full=safe_call(lambda:bot.request('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report'))
    if full.get('status')=='observed' and isinstance(full.get('value'),dict):
        r=full['value'];result['full_report_gate']=security_v3.report_gate(r,selected)
        result['risk_report']={k:r.get(k) for k in ('mint','tokenProgram','creator','creatorBalance','token','mintAuthority','freezeAuthority','risks','score_normalised','insiderNetworks','graphInsidersDetected','detectedAt','rugged','markets','lockerScanStatus')}
        result['developer']=safe_call(lambda:security_v3.developer_check(r,bot,time.time()))
    else:result['risk_report']={'status':'unavailable'}
    trades=safe_call(lambda:gecko.request(market_data.GECKO+'/networks/solana/pools/'+pair+'/trades'))
    result['trade_feed']={'status':trades['status'],'count':len(trades.get('value',{}).get('data',[])), 'attribute_keys':list((trades.get('value',{}).get('data') or [{}])[0].get('attributes',{}))}
    result['buyers']=screening_rules.trade_evidence(trades.get('value'),mint,time.time())
    result['sell_bundle_sample']=safe_call(lambda:security_v3.transaction_sample(selected,result['buyers'],bot,time.time()))
    if result['base_security'].get('status')=='observed':
        result['v3_security']=security_v3.inspect(selected,result['base_security']['value'],result['buyers'],bot,time.time())
    else:result['v3_security']={'complete':False,'reject':'base_security_unavailable'}
    result['eligible_based_on_audited_gates']=not result.get('market_gate') and not result.get('momentum',{}).get('reject') and not result.get('narrative',{}).get('reject') and result.get('v3_security',{}).get('complete') is True
    result['production_delivery_not_evaluated']=True
    result['note']='Read-only audit; every gate is reported independently, including gates production skips after an earlier rejection. No alert sent.'
    return result


class AuditGecko(market_data.GeckoClient):
    def request(self,url):
        while True:
            calls=[t for t in self.state.get('gecko_requests',[]) if 0<=time.time()-t<60]
            if len(calls)<9:break
            delay=min(50,max(1,61-(time.time()-min(calls))))
            print('AUDIT_FREE_FEED_COOLDOWN seconds='+str(round(delay)),flush=True)
            time.sleep(delay)
        return super().request(url)


def main():
    state=json.loads(Path('state.json').read_text());now=time.time();bot.REQUEST_DEADLINE=time.monotonic()+100
    gecko=AuditGecko(bot,{})
    original,discovery=scanner_v2.discover(bot,gecko)
    feed=narrative_v3.collect(bot,copy.deepcopy(state),now);feed=dict(feed);feed['_prepared_trends']=narrative_v3.trends(feed,now)
    original+=narrative_v3.search_pools(bot,feed,now)
    original,hydration=market_data.hydrate_incomplete(original,bot,gecko,time.time())
    original=market_data.refresh_watchlist(original,copy.deepcopy(state),bot,gecko,time.time())
    baseline={market_data.get(p,'baseToken.address') for p in original}
    searches={}
    for query in QUERIES:
        bot.REQUEST_DEADLINE=time.monotonic()+20
        d=safe_call(lambda:bot.request(bot.DEX+'/latest/dex/search?'+urlencode({'q':query})))
        searches[query]=[p for p in d.get('value',{}).get('pairs',[]) if p.get('chainId')=='solana']
    report={'at':now,'mode':'READ ONLY / NO TELEGRAM / NO TRANSACTIONS','run_id':os.environ.get('GITHUB_RUN_ID'),
            'discovery':discovery,'hydration':hydration,'baseline_mints':sorted(x for x in baseline if isinstance(x,str)),
            'search_candidates':searches,'narrative_sources':feed['sources'],'trends':feed['_prepared_trends'],'tokens':[]}
    for name,mint in TARGETS:
        bot.REQUEST_DEADLINE=time.monotonic()+30
        payload=safe_call(lambda:bot.request(bot.DEX+'/tokens/v1/solana/'+mint))
        pools=[p for p in payload.get('value',[]) if p.get('chainId')=='solana' and market_data.get(p,'baseToken.address')==mint]
        pool=max(pools,key=lambda p:screening_rules.amount(market_data.get(p,'liquidity.usd')) or 0) if pools else None
        row=audit_one(name,mint,pool,state,feed,baseline,searches,gecko)
        report['tokens'].append(row)
        Path('reports').mkdir(exist_ok=True);Path('reports/real-token-audit.json').write_text(json.dumps(report,indent=2))
        components={'name':name,'trade_feed':row.get('trade_feed'),'holders':row.get('holders'),'developer':row.get('developer'),'sell_bundle_sample':row.get('sell_bundle_sample'),'buyers':{k:v for k,v in row.get('buyers',{}).items() if k!='transactions'},'risk_report':{k:v for k,v in row.get('risk_report',{}).items() if k!='markets'},'pool_lock':[m for m in row.get('risk_report',{}).get('markets',[]) or [] if m.get('pubkey')==row.get('pair')]}
        print('AUDIT_COMPONENTS '+json.dumps(components),flush=True)
        print('REAL_TOKEN_AUDIT '+json.dumps({k:row.get(k) for k in ('name','mint','pair','in_original_discovery','market','market_gate','momentum','narrative','onchain_mint','full_report_gate','v3_security')}),flush=True)
    print('REAL_TOKEN_AUDIT_DONE count='+str(len(report['tokens'])),flush=True)

if __name__=='__main__':main()
