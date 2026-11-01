"""Discovery scheduling/ranking only. Never grants permission to PAPER_BUY."""
import time
from solana_sniper_paper import number


def pool_priority(pair, now):
    born=pair.get('pairCreatedAt')
    age=(now-born/1000)/60 if number(born) else None
    young=age is not None and 0<=age<=60
    old=age is not None and age>60
    volume=(pair.get('volume') or {}).get('m5')
    tx=(pair.get('txns') or {}).get('m5') or {}
    buys,sells=tx.get('buys'),tx.get('sells')
    liquidity=(pair.get('liquidity') or {}).get('usd')
    activity=number(volume) and volume>0 and number(buys) and buys>0
    counts=all(number(v) and v>=0 and int(v)==v for v in (buys,sells))
    ratio_ok=counts and buys>0 and (sells==0 or buys/sells>=1.5)
    market_ok=(number(liquidity) and liquidity>=10000 and number(volume) and volume>=1500
               and counts and buys>=12 and ratio_ok and not old)
    group=(0 if young else 1) if market_ok else 2 if young and activity else 3 if activity and not old else 4 if young else 6 if old else 5
    return (group,-volume if number(volume) else 0,-buys if number(buys) else 0,
            -liquidity if number(liquidity) else 0,str(pair.get('pairAddress','')))


def source_schedule(round_id):
    # Historical samples: generic SOL/USDC/Raydium search, boosts and takeovers
    # overwhelmingly matched old pools. Retain them as occasional exploration.
    sources=['/token-profiles/latest/v1']
    if round_id%2==0:sources.append('/token-profiles/recent-updates/v1')
    if round_id%4==0:sources.append('/token-boosts/latest/v1')
    if round_id%6==0:sources.append('/community-takeovers/latest/v1')
    if round_id%4==0:sources.append('/latest/dex/search?q=pump')
    return sources


def hint_from_pair(pair, now, previous=None):
    volume=(pair.get('volume') or {}).get('m5');buys=((pair.get('txns') or {}).get('m5') or {}).get('buys')
    inactive=volume==0 or buys==0
    return dict(pairCreatedAt=pair.get('pairCreatedAt'),volume=pair.get('volume'),
                txns=pair.get('txns'),liquidity=pair.get('liquidity'),pairAddress=pair.get('pairAddress'),
                inspected_at=now,inactive_streak=(previous or {}).get('inactive_streak',0)+1 if inactive else 0)


def hint_due(hint, now):
    if not hint:return True,'unseen'
    rank=pool_priority(hint,now)[0]
    interval=1800 if rank==6 else min(300,60*2**min(3,max(0,hint.get('inactive_streak',1)-1))) if rank in (4,5) else 15
    return now-hint['inspected_at']>=interval, 'old_pool_cooldown' if rank==6 else 'inactive_cooldown' if rank in (4,5) else 'recent_inspection'


def prioritized_watchlist(registry,hints,round_id,max_tokens,now):
    due=[];skipped=[]
    for mint,value in registry.items():
        if now-value['last_seen']>=5400:continue
        ready,reason=hint_due(hints.get(mint),now)
        if (not ready and reason=='inactive_cooldown' and value.get('seed_buys',0)>0
            and value.get('seed_observed_at',0)>hints[mint]['inspected_at']):
            ready=True # Fresh BUY activity can wake an inactive discovery candidate.
        if not ready:
            skipped.append(dict(mint=mint,reason=reason));continue
        due.append(mint)
    known=sorted([m for m in due if m in hints],key=lambda m:(pool_priority(hints[m],now)[0],
        hints[m].get('verification_attempt',0),pool_priority(hints[m],now)[1:],hints[m]['inspected_at'],m))
    unseen=sorted([m for m in due if m not in hints],key=lambda m:(
        0 if registry[m].get('seed_buys',0)>0 else 1,-registry[m].get('seed_buys',0),
        -registry[m].get('first_seen',registry[m]['last_seen']),m))
    # Reserve exploration capacity for unseen mint addresses; remaining slots
    # return to known candidates when there are no new addresses.
    reserve=min(len(unseen),max(1,max_tokens//4))
    active_known=[m for m in known if pool_priority(hints[m],now)[0]<=3]
    waking=[m for m in known if pool_priority(hints[m],now)[0]!=6 and registry[m].get('seed_buys',0)>0
            and registry[m].get('seed_observed_at',0)>hints[m]['inspected_at']]
    active_known=list(dict.fromkeys(active_known+waking))
    inactive_known=[m for m in known if m not in active_known and pool_priority(hints[m],now)[0]!=6]
    old_known=[m for m in known if pool_priority(hints[m],now)[0]==6]
    chosen=active_known[:max_tokens-reserve]+unseen[:reserve]
    # A request budget is a ceiling, not a target to fill with dormant/old pools.
    inactive_known.sort(key=lambda m:(hints[m]['inspected_at'],m))
    old_known.sort(key=lambda m:(hints[m]['inspected_at'],m))
    probe_inactive=inactive_known[:2]
    probe_old=old_known[:1] if round_id%10==0 else []
    for mint in inactive_known[2:]:skipped.append(dict(mint=mint,reason='inactive_probe_budget'))
    for mint in old_known[len(probe_old):]:skipped.append(dict(mint=mint,reason='old_pool_low_priority'))
    remainder=[m for m in unseen+active_known+probe_inactive+probe_old if m not in chosen]
    chosen=(chosen+remainder)[:max_tokens]
    return chosen,skipped
