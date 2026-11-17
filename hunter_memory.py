"""Bounded forward observations and strict point-in-time replay, never filter self-relaxation."""
import copy
import time
from screening_rules import amount
from state_store import sample_performance, HORIZONS
import hunter_modes
import global_intelligence

CAPACITY=1500
RETENTION=90*86400


def record(state, pool, narrative, decision, now, safety=None):
    mint=(pool.get('baseToken') or {}).get('address'); pair=pool.get('pairAddress'); price=amount(pool.get('priceUsd'))
    if not mint or not pair or price is None or price<=0: return
    records=state.setdefault('memory_v5',{})
    # One sampled rejection per pool per 6 hours, plus each real accepted decision.
    key=pair+':'+str(int(now//21600))
    old=records.get(key)
    if not old or decision=='accepted':
        records[key]={'at':now,'updated':now,'mint':mint,'pair':pair,'price':price,'samples':{},
                      'decision':decision,'initial_decision':decision,'initial_liquidity_usd':amount((pool.get('liquidity') or {}).get('usd')),'narrative':narrative.get('label'), 'safety_complete':bool((safety or {}).get('complete')),
                      'initial_safety_complete':bool((safety or {}).get('complete')),
                      'market_cap_at_observation':amount(pool.get('marketCap')),
                      'pool_age_at_observation':now-pool['pairCreatedAt']/1000 if amount(pool.get('pairCreatedAt')) is not None else None}
    elif old:
        old.update(decision=decision,updated=now,safety_complete=bool((safety or {}).get('complete')))
    state['memory_v5']=dict(sorted(((k,v) for k,v in records.items() if 0<=now-v['at']<=RETENTION),key=lambda x:-x[1]['at'])[:CAPACITY])


def followup(state, pools, api, gecko, deadline):
    """Evaluate current quotes first; batch missing quotes without starving later records."""
    import market_data
    now=time.time()
    current={(p.get('pairAddress'),(p.get('baseToken') or {}).get('address')):p for p in pools if isinstance(p,dict) and p.get('chainId')=='solana' and not p.get('identityConflict')}
    def price_of(p):
        value=amount(p.get('priceUsd')) if p else None
        return value if value is not None and value>0 else None
    def is_due(r,when):
        return any(str(h) not in r.get('samples',{}) and when>=r['at']+h for h in HORIZONS)
    due=[r for r in state.get('memory_v5',{}).values() if is_due(r,now)]
    pending=[]
    for r in due:
        # Missing/late horizons are recorded even if no provider can return a price.
        p=current.get((r['pair'],r['mint']))
        price=price_of(p)
        sample_performance(r,price,now)
        if price is None and is_due(r,now): pending.append(r)
    # Protect the nearest expiring short horizon before long-horizon backlog.
    def urgency(r):
        expiries=[r['at']+h+(600 if h<86400 else 10800) for h in HORIZONS
                  if str(h) not in r.get('samples',{}) and r['at']+h<=now]
        return (min(expiries,default=float('inf')),r.get('last_quote_attempt_at',0))
    pending.sort(key=urgency)
    # Several 6h cohorts can refer to one pool: fetch each identity once per cycle.
    grouped={}
    for r in pending:grouped.setdefault((r['pair'],r['mint']),[]).append(r)
    pending=[rows[0] for rows in grouped.values()]
    attempted=0; recovered=0
    for start in range(0,min(len(pending),60),20):
        if deadline and time.monotonic()>=deadline-1: break
        batch=pending[start:start+20]
        wanted={r['pair']:r['mint'] for r in batch}
        quotes={}
        try:
            raw=api.request(api.DEX+'/latest/dex/pairs/solana/'+','.join(wanted))
            for p in raw.get('pairs') or []:
                pair=p.get('pairAddress');mint=(p.get('baseToken') or {}).get('address')
                if p.get('chainId')=='solana' and not p.get('identityConflict') and pair in wanted and mint==wanted[pair]: quotes[(pair,mint)]=p
        except Exception: pass
        missing=[pair for pair,mint in wanted.items() if price_of(quotes.get((pair,mint))) is None]
        if missing and gecko is not None and (not deadline or time.monotonic()<deadline-1):
            try:
                raw=gecko.request(market_data.GECKO+'/networks/solana/pools/multi/'+','.join(missing)+'?include=base_token,quote_token,dex')
                for p in market_data.gecko_pools(raw):
                    pair=p.get('pairAddress');mint=(p.get('baseToken') or {}).get('address')
                    if pair in wanted and mint==wanted[pair]:quotes[(pair,mint)]=p
            except Exception: pass
        observed_at=time.time()
        for representative in batch:
            key=(representative['pair'],representative['mint']);price=price_of(quotes.get(key));attempted+=1
            if price is not None and price>0:recovered+=1
            for r in grouped[key]:
                r['last_quote_attempt_at']=observed_at
                sample_performance(r,price,observed_at)
    return {'due_records':len(due),'quote_attempts':attempted,'quotes_recovered':recovered,
            'note':'Actual observation times only; old missed windows are not reconstructed.'}


def replay(rows):
    """Replay immutable observations with only past history/security. Reject hindsight data."""
    history={}; results=[]; previous=-1
    for row in rows:
        t=row['observed_at']
        if t<previous: raise ValueError('replay_not_chronological')
        previous=t
        if row.get('security_observed_at',float('inf'))>t: safety=False
        else: safety=row.get('security',{}).get('complete') is True
        articles=[a for a in row.get('articles',[]) if a.get('observed_at',float('inf'))<=t and a.get('published_at',float('inf'))<=t]
        feed={'trends':global_intelligence.trends(articles,{},t)}
        n=global_intelligence.match(row['pool'],feed,t)
        m=hunter_modes.assess(row['pool'],history,t,n)
        results.append({'at':t,'mint':row['pool'].get('baseToken',{}).get('address'),
                        'accepted':not m.get('reject') and safety,
                        'rejection':m.get('reject') or (None if safety else 'point_in_time_security_missing')})
        from signal_quality import snapshot,merge_observations
        snap=snapshot(row['pool'],t)
        if snap: history.setdefault(row['pool']['pairAddress'],[]).append(snap)
        history=merge_observations(history,now=t)
    return {'method':'chronological prefix-only; no future evidence; observed prices are not executed returns',
            'decisions':results,'accepted':sum(r['accepted'] for r in results)}
