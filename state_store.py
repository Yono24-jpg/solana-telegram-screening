"""Bounded durable delivery reservations and public performance observations."""
import copy
import time
from signal_quality import merge_observations

RETENTION = 14*86400
HORIZONS = (300, 900, 3600, 86400)


def migrate(state, now):
    state.setdefault('delivery', {})
    state.setdefault('performance', {})
    state.setdefault('evidence_cache', {})
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
    record['updated'] = now
