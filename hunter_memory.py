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
                      'decision':decision,'narrative':narrative.get('label'), 'safety_complete':bool((safety or {}).get('complete'))}
    elif old:
        old.update(decision=decision,updated=now,safety_complete=bool((safety or {}).get('complete')))
    state['memory_v5']=dict(sorted(((k,v) for k,v in records.items() if 0<=now-v['at']<=RETENTION),key=lambda x:-x[1]['at'])[:CAPACITY])


def followup(state, pools, api, gecko, deadline):
    import scanner_v2
    current={(p.get('pairAddress'),(p.get('baseToken') or {}).get('address')):p for p in pools}
    due=[r for r in state.get('memory_v5',{}).values() if any(str(h) not in r.get('samples',{}) and time.time()>=r['at']+h for h in HORIZONS)]
    for r in sorted(due,key=lambda r:r.get('last_observed_at',0))[:20]:
        if deadline and time.monotonic()>=deadline-20: break
        p=current.get((r['pair'],r['mint']))
        if p is None:
            try: p=scanner_v2.refresh(r['pair'],r['mint'],api,gecko)
            except Exception: p={}
        sample_performance(r,amount(p.get('priceUsd')),time.time())


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
