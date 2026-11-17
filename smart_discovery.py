"""Bounded on-chain leads and durable rechecks. No market or safety fabrication.

RPC parser: raydium-io/raydium-cp-swap programs/cp-swap/src/instructions/initialize.rs.
Mainnet addresses: raydium-io/raydium-docs-v1 reference/program-addresses.mdx.
Only CPMM initialize is decoded; other protocols continue through public feeds.
"""
import copy
import hashlib
import time
from collections import Counter
import market_data as market
from screening_rules import address, number
from vault_checks import ALPHABET, CPMM, key_bytes

FEE = 'DNXgeM9EiiaAbaWvwjHj9fQQLAX5ZsfHyvmYUNRAdNC8'
INIT = hashlib.sha256(b'global:initialize').digest()[:8]
STATE_KEY = 'smart_discovery_v53'


def state_for(state, now):
    record = state.setdefault(STATE_KEY, {'at': now, 'queue': {}, 'signatures': {}})
    record['at'] = now
    for key in ('queue', 'signatures'):
        record.setdefault(key, {})
    record['queue'] = {k: v for k, v in record['queue'].items()
                       if address(k) and isinstance(v, dict) and number(v.get('at'))
                       and 0 <= now-v['at'] <= 86400}
    record['signatures'] = {k: v for k, v in record['signatures'].items()
                            if isinstance(v, dict) and number(v.get('at')) and 0 <= now-v['at'] <= 7200}
    return record


def decode58(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError('instruction_encoding')
    n = 0
    for c in value:
        n = n*58+ALPHABET.index(c)
    return bytes(len(value)-len(value.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8, 'big') if n else b'')


def parse_initialize(tx, signature, now):
    """Successful finalized transaction + exact program/discriminator/account layout.

    A discovery lead proves neither current liquidity nor safety. No balances are
    converted into USD or rolling trading windows here.
    """
    if not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict) or tx['meta'].get('err') is not None:
        return []
    at = tx.get('blockTime')
    if not number(at) or not 0 <= now-at <= 3600:
        return []
    transaction = tx.get('transaction') or {}
    if signature not in transaction.get('signatures', []):
        return []
    message = transaction.get('message') or {}
    instructions = list(message.get('instructions') or [])
    for group in tx['meta'].get('innerInstructions') or []:
        instructions += group.get('instructions') or []
    result = []
    for ix in instructions:
        try:
            if ix.get('programId') != CPMM:
                continue
            raw = decode58(ix.get('data'))
            accounts = ix.get('accounts') or []
            if len(raw) != 32 or raw[:8] != INIT or len(accounts) < 20 or accounts[12] != FEE:
                continue
            pair, a, b = accounts[3:6]
            for key in (pair, a, b):
                key_bytes(key)
            if a == b or (a in market.QUOTE_ASSETS) == (b in market.QUOTE_ASSETS):
                continue
            mint, quote = (b, a) if a in market.QUOTE_ASSETS else (a, b)
            result.append({'chainId': 'solana', 'pairAddress': pair,
                           'baseToken': {'address': mint}, 'quoteToken': {'address': quote},
                           'pairCreatedAt': at*1000, 'dexId': 'raydium', 'dataSource': 'rpc_initialize',
                           'discoveryEvidence': {'signature': signature, 'program': CPMM,
                                                 'block_time': at, 'observed_at': now,
                                                 'scope': 'creation lead only; security unverified'}})
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return result


def rpc_discover(providers, state, now, max_transactions=6):
    record = state_for(state, now)
    stats = {'scope': 'Raydium CPMM fee-account initialization sample; not all Solana pools',
             'signature_reads': 0, 'transaction_reads': 0, 'cache_hits': 0, 'leads': 0,
             'status': 'ok', 'transaction_limit': min(max_transactions, 6)}
    deadline = min(getattr(providers.api, 'REQUEST_DEADLINE', None) or float('inf'), time.monotonic()+18)
    if time.monotonic()+2 >= deadline:
        stats['status'] = 'deadline'; return [], stats
    try:
        stats['signature_reads'] += 1
        rows = providers.rpc('getSignaturesForAddress', [FEE, {'limit': 40, 'commitment': 'finalized'}])
        if not isinstance(rows, list):
            raise ValueError('signature_shape')
        for row in rows:
            sig = row.get('signature') if isinstance(row, dict) else None
            at = row.get('blockTime') if isinstance(row, dict) else None
            if (isinstance(sig, str) and 64 <= len(sig) <= 88 and all(c in ALPHABET for c in sig)
                    and row.get('err') is None and number(at) and 0 <= now-at <= 3600):
                if sig in record['signatures']:
                    stats['cache_hits'] += int(record['signatures'][sig].get('done', False))
                else:
                    record['signatures'][sig] = {'at': now, 'block_time': at, 'done': False, 'retry_at': 0}
    except Exception:
        stats['status'] = 'signatures_unavailable'
    pending = sorted(((s, r) for s, r in record['signatures'].items()
                      if not r.get('done') and r.get('retry_at', 0) <= now
                      and 0 <= now-r.get('block_time', 0) <= 3600),
                     key=lambda x: (x[1].get('attempts', 0), -x[1]['block_time']))
    leads = []
    for sig, row in pending[:min(max_transactions, 6)]:
        if time.monotonic()+2 >= deadline:
            stats['deadline_exhausted'] = True; break
        stats['transaction_reads'] += 1
        row.update(at=now, attempts=row.get('attempts', 0)+1, retry_at=now+300)
        try:
            tx = providers.rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'commitment': 'finalized',
                                                      'maxSupportedTransactionVersion': 0}])
            if not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict):
                raise ValueError('transaction_shape')
            leads += parse_initialize(tx, sig, now)
            row['done'] = True
        except Exception:
            stats['status'] = 'partial_transaction_unavailable'
    record['signatures'] = dict(sorted(record['signatures'].items(), key=lambda x: -x[1]['at'])[:200])
    stats['leads'] = len(leads)
    return market.merge_pools(leads), stats


def seed(pool):
    """Identity cache only. Old price/volume/liquidity cannot reenter alert evaluation."""
    return {k: copy.deepcopy(pool[k]) for k in
            ('chainId', 'pairAddress', 'baseToken', 'quoteToken', 'pairCreatedAt', 'dexId', 'discoveryEvidence') if k in pool}


def young(pool, now):
    created = market.amount(pool.get('pairCreatedAt'))
    return created is not None and 0 <= now-created/1000 <= 3600


def prepare(pools, state, now):
    record = state_for(state, now)
    for p in pools:
        pair = p.get('pairAddress'); mint = market.get(p, 'baseToken.address')
        if not address(pair) or not address(mint):
            continue
        old = record['queue'].get(pair, {})
        if old and market.get(old.get('seed', {}), 'baseToken.address') != mint:
            continue
        record['queue'][pair] = dict(old, at=now, seed=seed(p), first_seen=old.get('first_seen', now))
    # Young leads first; retry rotation is durable, and only invoked requests move it.
    record['queue'] = dict(sorted(record['queue'].items(), key=lambda x:
        (not young(x[1]['seed'], now), -x[1]['at'], x[0]))[:300])
    existing = {p['pairAddress'] for p in pools}
    absent = [(k, r) for k, r in record['queue'].items() if k not in existing and r.get('next_at', 0) <= now]
    absent.sort(key=lambda x: (not young(x[1]['seed'], now), x[1].get('last_attempt', 0), x[0]))
    return market.merge_pools(pools+[copy.deepcopy(r['seed']) for _, r in absent[:80]])


def recover(pools, state, api, gecko, now):
    record = state_for(state, now)
    pending = [p for p in pools if market.v3_missing_fields(p)
               and record['queue'].get(p['pairAddress'], {}).get('next_at', 0) <= now]
    pending.sort(key=lambda p: (not young(p, now),
        record['queue'].get(p['pairAddress'], {}).get('last_attempt', 0), p['pairAddress']))
    # Existing hydration retains exact mint/pair checks and coherent snapshots.
    selected = pending[:80]
    repaired, stats = market.hydrate_incomplete(selected, api, gecko, now)
    by_pair = {p['pairAddress']: p for p in repaired}
    attempts = state.get('provider_state_v5', {}).get('hydration', {}).get('attempts', {})
    for p in selected:
        pair = p['pairAddress']; row = record['queue'].get(pair)
        if row is None or attempts.get(pair, 0) < now:
            continue
        after = by_pair[pair]
        row.update(last_attempt=now, next_at=now+(295 if young(p, now) else 895),
                   attempts=row.get('attempts', 0)+1, missing=market.v3_missing_fields(after))
    stats.update(queue_size=len(record['queue']), due=len(pending), selected_young=sum(young(p, now) for p in selected),
                 deferred=len(pending)-len(selected), policy='identity-only durable cache; bounded due queue; young first')
    # Replacement is per pair, rather than appending old metrics to a new snapshot.
    return [by_pair.get(p['pairAddress'], p) for p in pools], stats


def cohort_start(state, pools, now, baseline=None):
    record = state_for(state, now)
    if record.get('cohort'):
        return
    if baseline and baseline.get('version') == '5.2' and baseline.get('rows'):
        record['cohort'] = copy.deepcopy(baseline)
        return
    rows = sorted(pools, key=lambda p: (not young(p, now), p['pairAddress']))[:80]
    if rows:
        record['cohort'] = {'at': now, 'rows': {p['pairAddress']: {'mint': market.get(p, 'baseToken.address'),
            'initial_missing': market.v3_missing_fields(p), 'initial_young': young(p, now)} for p in rows}}


def cohort_refresh(state, api, now):
    """Reobserve the exact pre-upgrade sample; never use baseline market numbers."""
    cohort = state_for(state, now).get('cohort', {})
    if not number(cohort.get('at')) or not 0 <= now-cohort['at'] <= 21600:
        return [], {'status': 'validation_window_closed', 'requests': 0}
    expected = dict(list(cohort.get('rows', {}).items())[:80])
    stats = {'status': 'ok', 'requests': 0, 'observed': 0, 'identity_rejections': 0}
    found = []
    pairs = list(expected)
    for start in range(0, len(pairs), 20):
        deadline = getattr(api, 'REQUEST_DEADLINE', None)
        if number(deadline) and time.monotonic()+2 >= deadline:
            stats['status'] = 'deadline'; break
        batch = pairs[start:start+20]
        try:
            stats['requests'] += 1
            raw = api.request(api.DEX+'/latest/dex/pairs/solana/'+','.join(batch))
            if not isinstance(raw, dict) or not isinstance(raw.get('pairs'), list):
                raise ValueError('response_shape')
            for p in raw['pairs']:
                pair = p.get('pairAddress') if isinstance(p, dict) else None
                if (pair not in batch or p.get('chainId') != 'solana'
                        or market.get(p, 'baseToken.address') != expected[pair]['mint']):
                    stats['identity_rejections'] += 1; continue
                found.append(p)
        except Exception:
            stats['status'] = 'partial_unavailable'
    stats['observed'] = len({p['pairAddress'] for p in found})
    return market.merge_pools(found), stats


def comparison(state, before, after, now):
    """Fixed denominator, no absent/cached market values counted as complete."""
    def index(rows):
        return {(p['pairAddress'], market.get(p, 'baseToken.address')): p for p in rows}
    a, b = index(before), index(after)
    cohort = state_for(state, now).get('cohort', {'rows': {}})
    rows = []
    for pair, r in cohort['rows'].items():
        key = (pair, r['mint']); current = b.get(key)
        missing = market.v3_missing_fields(current) if current else ['not_observed_this_cycle']
        rows.append({'pair': pair, 'mint': r['mint'], 'initial_missing': r['initial_missing'],
                     'current_missing': missing, 'initial_young': r['initial_young']})
    paired = [{'pair': k[0], 'mint': k[1], 'before': market.v3_missing_fields(p),
               'after': market.v3_missing_fields(b[k]) if k in b else ['not_observed_this_cycle']}
              for k, p in sorted(a.items())]
    return {'scope': 'same-identity pre/post recovery plus fixed cohort; temporal comparison, not causal A/B',
            'fixed': {'started_at': cohort.get('at'), 'baseline_version': cohort.get('version', '5.3 entry'),
                      'source_run': cohort.get('source_run'), 'total': len(rows),
                      'baseline_complete': sum(not r['initial_missing'] for r in rows),
                      'current_complete': sum(not r['current_missing'] for r in rows),
                      'absent': sum(r['current_missing'] == ['not_observed_this_cycle'] for r in rows), 'rows': rows},
            'paired': {'total': len(paired), 'before_complete': sum(not r['before'] for r in paired),
                       'after_complete': sum(not r['after'] for r in paired),
                       'recovered': sum(bool(r['before']) and not r['after'] for r in paired),
                       'regressed': sum(not r['before'] and bool(r['after']) for r in paired), 'rows': paired},
            'source_mix': dict(Counter(p.get('dataSource', 'dexscreener') for p in after))}
