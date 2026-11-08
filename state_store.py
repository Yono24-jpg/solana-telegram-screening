"""Bounded durable delivery reservations and public performance observations."""
import copy
import time
import statistics
from signal_quality import merge_observations
from screening_rules import number, address

RETENTION = 14*86400
HORIZONS = (300, 900, 3600, 86400)


def migrate(state, now):
    state.setdefault('delivery', {})
    state.setdefault('performance', {})
    state.setdefault('evidence_cache', {})
    state.setdefault('pool_watchlist', {})
    state['scan_history'] = sorted([r for r in state.get('scan_history',[]) if isinstance(r,dict)
                                   and number(r.get('at')) and 0<=now-r['at']<=7*86400],key=lambda r:r['at'])[-100:]
    state['gecko_requests'] = sorted(set(t for t in state.get('gecko_requests',[]) if number(t) and 0 <= now-t <= 120))[-100:]
    state['pool_watchlist'] = {k:v for k,v in state['pool_watchlist'].items() if address(k) and isinstance(v,dict)
                              and address(v.get('mint')) and number(v.get('created_at')) and 0 <= now-v['created_at'] <= 86400
                              and number(v.get('last_seen')) and number(v.get('last_checked'))}
    state['pool_watchlist'] = dict(sorted(state['pool_watchlist'].items(),key=lambda x:(now-x[1]['created_at']<=3600,x[1]['last_seen']),reverse=True)[:200])
    state['schema_version'] = 2
    state['delivery'] = {k:v for k,v in state['delivery'].items() if isinstance(v, dict)
                         and isinstance(v.get('at'), (int, float)) and 0 <= now-v['at'] <= RETENTION}
    state['performance'] = {k:v for k,v in state['performance'].items() if isinstance(v, dict)
                            and isinstance(v.get('at'), (int, float)) and 0 <= now-v['at'] <= RETENTION}
    state['evidence_cache'] = {k:v for k,v in state['evidence_cache'].items() if isinstance(v, dict)
                               and isinstance(v.get('at'), (int, float)) and 0 <= now-v['at'] <= 3600}
    for name, limit in [('delivery', 2000), ('performance', 2000), ('evidence_cache', 200)]:
        state[name] = dict(sorted(state[name].items(), key=lambda x:x[1]['at'], reverse=True)[:limit])
    return state


def already_delivered(state, mint, tier, now):
    # Previous-version deliveries retain suppression through the complete pool-age window.
    legacy = state.get('sent', {}).get(mint)
    if isinstance(legacy, (int, float)) and 0 <= now-legacy <= 2*86400 and not any(k.startswith(mint+':') for k in state['delivery']):
        return True
    if mint+':'+tier in state['delivery']:
        return True
    return tier == 'EARLY WATCH' and mint+':STRONG SIGNAL' in state['delivery']


def merge(remote, local, now):
    out = dict(remote)
    for key in ('delivery', 'performance', 'evidence_cache'):
        records = copy.deepcopy(remote.get(key, {}))
        for k, item in local.get(key, {}).items():
            old = records.get(k)
            if key == 'delivery' and old and old.get('reservation') != item.get('reservation'):
                continue  # First persisted reservation owns the right to send.
            if key == 'performance' and old:
                item = dict(item, samples={**old.get('samples', {}), **item.get('samples', {})})
            if not old or item.get('updated', item.get('at', 0)) >= old.get('updated', old.get('at', 0)):
                records[k] = item
        out[key] = records
    out['observations'] = merge_observations(remote.get('observations', {}), local.get('observations', {}), now=now)
    out['gecko_requests'] = remote.get('gecko_requests',[])+local.get('gecko_requests',[])
    out['scan_history'] = list({(r['at'],r.get('run_id')):r for r in remote.get('scan_history',[])+local.get('scan_history',[])
                               if isinstance(r,dict) and number(r.get('at'))}.values())
    out['pool_watchlist'] = copy.deepcopy(remote.get('pool_watchlist',{}))
    for key,value in local.get('pool_watchlist',{}).items():
        old = out['pool_watchlist'].get(key,{})
        if value.get('last_checked',0) >= old.get('last_checked',0): out['pool_watchlist'][key] = copy.deepcopy(value)
    out['sent'] = {k:v for k,v in {**local.get('sent', {}), **remote.get('sent', {})}.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= now-v <= 2*86400}
    ro = remote.get('offset', 0); lo = local.get('offset', 0)
    out['offset'] = max(ro, lo)
    out['enabled'] = local.get('enabled', False) if lo > ro else remote.get('enabled', local.get('enabled', False))
    out['initialized'] = bool(local.get('initialized') or remote.get('initialized'))
    out['last_scan'] = local.get('last_scan', remote.get('last_scan'))
    return migrate(out, now)


def sample_performance(record, price, now):
    """Observed prices only; delayed runs are marked missed, not backdated."""
    samples = record.setdefault('samples', {})
    for seconds in HORIZONS:
        key = str(seconds)
        if key in samples or now < record['at']+seconds: continue
        lateness = now-record['at']-seconds
        grace = 600 if seconds < 86400 else 10800
        if lateness > grace:
            samples[key] = {'status': 'missed', 'reason': 'no_observation_in_window'}
        elif price is not None and price > 0:
            samples[key] = {'status': 'observed', 'at': now, 'elapsed_seconds': now-record['at'],
                            'price': price, 'change_pct': round(100*(price/record['price']-1), 2)}
    if price is not None and price > 0:
        record['last_observed_price'] = price; record['last_observed_at'] = now
        change = 100*(price/record['price']-1)
        record['best_observed_pct'] = round(max(record.get('best_observed_pct',0),change),2)
        record['worst_observed_pct'] = round(min(record.get('worst_observed_pct',0),change),2)
    record['updated'] = now


def performance_summary(state):
    result = {}
    for tier in ('EARLY WATCH','STRONG SIGNAL'):
        rows = [r for r in state.get('performance',{}).values() if r.get('tier') == tier]
        windows = {}
        for h in HORIZONS:
            samples = [r.get('samples',{}).get(str(h),{}) for r in rows]
            returns = [s['change_pct'] for s in samples if s.get('status') == 'observed' and number(s.get('change_pct'))]
            windows[str(h)] = {'observed':len(returns),'missed':sum(s.get('status')=='missed' for s in samples),
                               'median_change_pct':round(statistics.median(returns),2) if returns else None}
        result[tier] = {'signals':len(rows),'windows_seconds':windows}
    return result
