"""Dynamic real trending-token audit; no Telegram delivery or production mutation."""
import json
from pathlib import Path
import time
import bot
import data_intelligence as di
import evidence
import global_intelligence
import hunter_modes
import market_data
import security_v3
import token_extensions
from v5_live_audit import ReadOnlyAPI


def run():
    state=json.loads(Path('state.json').read_text());api=ReadOnlyAPI();api.REQUEST_DEADLINE=time.monotonic()+150
    bot.REQUEST_DEADLINE=api.REQUEST_DEADLINE
    providers=di.Client(api,state);api.DATA_INTELLIGENCE=providers
    trends=providers.trending()
    # Dynamic ranking includes large mature coins and smaller eligible narratives.
    low=[r for r in trends if (di.amount(r.get('mcap')) or float('inf'))<=5000000]
    chosen=list({r['id']:r for r in trends[:2]+low[:4]+trends[2:6]}.values())[:6]
    expected={r['id'] for r in chosen};pools=[]
    if expected:
        try:
            raw=api.request(api.DEX+'/tokens/v1/solana/'+','.join(sorted(expected)))
            if isinstance(raw,list):pools=[p for p in raw if isinstance(p,dict) and p.get('chainId')=='solana' and (p.get('baseToken') or {}).get('address') in expected]
        except Exception:pass
    gecko=market_data.GeckoClient(api,state)
    missing=[r for r in chosen if not any(p['baseToken']['address']==r['id'] for p in pools)]
    pair_map={r.get('firstPool',{}).get('id'):r['id'] for r in missing if di.address(r.get('firstPool',{}).get('id'))}
    if pair_map:
        try:
            rows=market_data.gecko_pools(gecko.request(market_data.GECKO+'/networks/solana/pools/multi/'+','.join(pair_map)+'?include=base_token,quote_token,dex'))
            pools+=[p for p in rows if p['pairAddress'] in pair_map and p['baseToken']['address']==pair_map[p['pairAddress']]]
        except Exception:pass
    providers.enrich(pools)
    rows=[];now=time.time();feed=state.get('global_feed_v5',{})
    if 'trends' not in feed:feed={'trends':global_intelligence.trends(feed.get('articles',[]),{},now)}
    for token in chosen:
        mint=token['id'];available=[p for p in pools if p['baseToken']['address']==mint]
        pool=max(available,key=lambda p:market_data.get(p,'liquidity.usd') or 0) if available else None
        row={'mint':mint,'name':token.get('name'),'symbol':token.get('symbol'),'trending_provider':'Jupiter toptrending/5m',
             'token_reference':{k:token.get(k) for k in ('mcap','fdv','circSupply','totalSupply','organicScore','holderCount','updatedAt')},
             'verified_alert':False,'security_complete':False}
        if pool:
            n=global_intelligence.match(pool,feed,now);m=hunter_modes.assess(pool,state.get('observations',{}),now,n)
            row.update(pair=pool['pairAddress'],market_cap=pool.get('marketCap'),liquidity=market_data.get(pool,'liquidity.usd'),
                       pool_age_seconds=now-pool['pairCreatedAt']/1000 if di.number(pool.get('pairCreatedAt')) else None,
                       market_rejection=m.get('reject'),missing_fields=market_data.v3_missing_fields(pool),
                       narrative_rejection=n.get('reject'),narrative=n.get('label'))
            try:
                raw=providers.rugcheck(mint);row['provider_security_rejection']=security_v3.report_gate(raw,pool,(token_extensions.CLASSIC,token_extensions.TOKEN2022))
                row['insider_coverage']={k:raw.get(k) for k in ('graphInsidersDetected','insiderNetworks','rugged','score_normalised')}
            except Exception:row['provider_security_rejection']='full_report_unavailable'
        else:row['market_rejection']='same_mint_pool_snapshot_unavailable'
        # Independently inspect mint even when market gates already reject.
        try:
            account=evidence.rpc(api,'getAccountInfo',[mint,{'encoding':'base64','commitment':'finalized'}])['value']
            row['mint_audit']=token_extensions.audit(account,mint)
        except Exception:row['mint_audit']={'complete':False,'reject':'rpc_mint_unavailable'}
        row['reason']=row.get('market_rejection') or row.get('provider_security_rejection') or 'full_trade_holder_funding_checks_not_completed'
        row['tier']='NARRATIVE WATCH' if row.get('narrative') and not row.get('narrative_rejection') else 'REJECTED'
        rows.append(row)
    report={'at':time.time(),'mode':'READ ONLY; no delivery; no historical safety reconstruction',
            'access':providers.credentials(),'provider_status':providers.status,'trending_count':len(trends),'tokens':rows,
            'historical_filter_review':di.history_review(state,time.time()),'thresholds_changed':False}
    Path('reports').mkdir(exist_ok=True);Path('reports/data-intelligence-real-tokens.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('DATA_INTELLIGENCE_AUDIT '+json.dumps(report,ensure_ascii=False))
    return report


if __name__=='__main__':run()
