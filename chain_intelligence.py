"""Official-layout RPC leads and sampled reserve changes, never synthetic market data."""
import copy
import hashlib
import json
from pathlib import Path
import time
from collections import Counter
import market_data as market
import smart_discovery as prior
from screening_rules import number, address
from vault_checks import key_bytes, b58encode, CPMM, ALPHABET

LAYOUTS = json.loads(Path(__file__).with_name('protocol_layouts_v54.json').read_text())
BY_DISC = {(r['program'], bytes(r['discriminator'])): r for r in LAYOUTS}
PROGRAMS = {r['protocol']: r['program'] for r in LAYOUTS}
QUOTE = 'So11111111111111111111111111111111111111112'


def pda(seed, program):
    """Solana find_program_address for this fixed one-seed PDA, no signing keys."""
    p = 2**255-19; d = -121665*pow(121666, -1, p) % p
    for bump in range(255, -1, -1):
        raw = hashlib.sha256(seed+bytes([bump])+key_bytes(program)+b'ProgramDerivedAddress').digest()
        y = int.from_bytes(raw, 'little') & (2**255-1)
        denominator = (d*y*y+1) % p
        x2 = ((y*y-1)*pow(denominator, -1, p)) % p if denominator else 0
        on_curve = y < p and denominator != 0 and pow(x2, (p-1)//2, p) in (0, 1)
        if not on_curve:
            return b58encode(raw)
    raise ValueError('pda_not_found')


PUMP_MINT_AUTHORITY = pda(b'mint-authority', PROGRAMS['pump'])


def instructions(tx):
    values = list(((tx.get('transaction') or {}).get('message') or {}).get('instructions') or [])
    for group in tx.get('meta', {}).get('innerInstructions') or []:
        if isinstance(group, dict): values += group.get('instructions') or []
    return [r for r in values if isinstance(r, dict)]


def valid_tx(tx, signature, now, horizon=3600):
    return (isinstance(tx, dict) and isinstance(tx.get('meta'), dict)
            and 'err' in tx['meta'] and tx['meta']['err'] is None and number(tx.get('blockTime'))
            and 0 <= now-tx['blockTime'] <= horizon
            and signature in (tx.get('transaction') or {}).get('signatures', []))


def layout_for(ix):
    try:
        value = ix.get('data')
        if not isinstance(value,str) or not 1 <= len(value) <= 4096:return None
        n=0
        for c in value:n=n*58+ALPHABET.index(c)
        raw=bytes(len(value)-len(value.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8,'big') if n else b'')
        accounts = ix.get('accounts') or []
        spec = BY_DISC.get((ix.get('programId'), raw[:8]))
        if not spec or len(accounts) < len(spec['accounts']): return None
        if any(accounts[int(i)] != v for i, v in spec['fixed'].items()): return None
        if any(not isinstance(a, str) for a in accounts): return None
        return spec, dict(zip(spec['accounts'], accounts))
    except (ValueError, TypeError): return None


def parse_creation(tx, signature, now):
    leads = prior.parse_initialize(tx, signature, now) if valid_tx(tx, signature, now) else []
    if not valid_tx(tx, signature, now): return []
    for ix in instructions(tx):
        found = layout_for(ix)
        if not found: continue
        spec, a = found; protocol = spec['protocol']; name = spec['name']
        try:
            if protocol == 'pump' and name in ('create', 'create_v2'):
                if a['mint_authority'] != PUMP_MINT_AUTHORITY: continue
                pair, mint, quote = a['bonding_curve'], a['mint'], QUOTE
                kind = 'bonding_curve'
            elif protocol == 'pumpswap' and name == 'create_pool':
                pair, mint, quote = a['pool'], a['base_mint'], a['quote_mint']; kind = 'amm_pool'
            elif protocol == 'meteora' and name.startswith('initialize_'):
                pair, mint, quote = a['pool'], a['token_a_mint'], a['token_b_mint']; kind = 'amm_pool'
                if mint in market.QUOTE_ASSETS: mint, quote = quote, mint
            else: continue
            for k in (pair, mint, quote): key_bytes(k)
            if mint in market.QUOTE_ASSETS or quote not in market.QUOTE_ASSETS or mint == quote: continue
            leads.append({'chainId': 'solana', 'pairAddress': pair,
                'baseToken': {'address': mint}, 'quoteToken': {'address': quote},
                'pairCreatedAt': tx['blockTime']*1000, 'dataSource': 'rpc_'+protocol,
                'discoveryEvidence': {'signature': signature, 'program': spec['program'], 'protocol': protocol,
                    'kind': kind, 'instruction': name, 'observed_at': now, 'block_time': tx['blockTime'],
                    'scope': 'creation only; no market or safety assertion'}})
        except (KeyError, ValueError, TypeError): continue
    return market.merge_pools(leads)


def discover(providers, state, now):
    r = state.setdefault('chain_intelligence_v54', {'at': now, 'signatures': {}, 'rotation': 0})
    r['at'] = now
    cache = {s: v for s, v in r.get('signatures', {}).items() if 0 <= now-v.get('at', 0) <= 7200}
    # Mint-authority indexes creations rather than the very large swap stream.
    alternate = 'pumpswap' if r.get('rotation', 0) % 2 == 0 else 'meteora'
    sources = [('pump', PUMP_MINT_AUTHORITY), ('raydium', prior.FEE), (alternate, PROGRAMS[alternate])]
    r['rotation'] = r.get('rotation', 0)+1
    stats = {'sources': {}, 'signature_reads': 0, 'transaction_reads': 0, 'cache_hits': 0,
             'baseline_cpmm_leads': 0, 'v54_leads': 0, 'scope': 'bounded HTTP polling sample; not complete or sub-minute coverage'}
    for protocol, account in sources:
        if providers.api.REQUEST_DEADLINE and time.monotonic()+2 >= providers.api.REQUEST_DEADLINE: break
        stats['signature_reads'] += 1
        try:
            rows = providers.rpc('getSignaturesForAddress', [account, {'limit': 20, 'commitment': 'finalized'}])
            if not isinstance(rows, list): raise ValueError('shape')
            stats['sources'][protocol] = {'status': 'ok', 'rows': len(rows)}
            for row in rows:
                if not isinstance(row, dict): continue
                sig = row.get('signature'); at = row.get('blockTime')
                if (not isinstance(sig, str) or not 64 <= len(sig) <= 88 or any(c not in ALPHABET for c in sig)
                        or row.get('err') is not None or not number(at) or not 0 <= now-at <= 3600): continue
                if sig in cache: stats['cache_hits'] += int(cache[sig].get('done', False))
                else: cache[sig] = {'at': now, 'block_time': at, 'protocol': protocol, 'done': False, 'retry_at': 0}
        except Exception: stats['sources'][protocol] = {'status': 'unavailable'}
    groups = {}
    for sig, v in sorted(cache.items(), key=lambda x: (x[1].get('attempts', 0), -x[1]['block_time'])):
        if not v.get('done') and v.get('retry_at', 0) <= now and 0 <= now-v['block_time'] <= 3600:
            groups.setdefault(v['protocol'], []).append((sig, v))
    pending = []
    while any(groups.values()) and len(pending) < 6:
        for key in ('pump', 'raydium', alternate, 'pumpswap', 'meteora'):
            if groups.get(key) and len(pending) < 6: pending.append(groups[key].pop(0))
    leads = []; baseline = []; archived = []
    for sig, row in pending:
        if providers.api.REQUEST_DEADLINE and time.monotonic()+2 >= providers.api.REQUEST_DEADLINE: break
        row.update(at=now, attempts=row.get('attempts', 0)+1, retry_at=now+295)
        stats['transaction_reads'] += 1
        try:
            tx = providers.rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
            if not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict): raise ValueError('shape')
            new = parse_creation(tx, sig, now); old = prior.parse_initialize(tx, sig, now) if valid_tx(tx, sig, now) else []
            leads += new; baseline += old; row['done'] = True
            archived.append({'signature': sig, 'observed_at': now, 'tx': tx,
                             'v53_cpmm_pairs': [p['pairAddress'] for p in old], 'v54_pairs': [p['pairAddress'] for p in new]})
        except Exception: stats.setdefault('transaction_failures', 0); stats['transaction_failures'] += 1
    r['signatures'] = dict(sorted(cache.items(), key=lambda x: -x[1]['at'])[:200])
    leads = market.merge_pools(leads); baseline = market.merge_pools(baseline)
    stats.update(baseline_cpmm_leads=len(baseline), v54_leads=len(leads),
                 leads=len(leads),new_protocol_leads=sum(p.get('dataSource') != 'rpc_initialize' for p in leads))
    # Bonding curves are not mislabeled as DEX AMM pools. Resolve the mint to an actual indexed pool.
    curves = [p for p in leads if p.get('discoveryEvidence', {}).get('kind') == 'bonding_curve']
    actual = [p for p in leads if p not in curves]
    if curves and (not providers.api.REQUEST_DEADLINE or time.monotonic()+2 < providers.api.REQUEST_DEADLINE):
        wanted = {p['baseToken']['address'] for p in curves}
        try:
            raw = providers.api.request(providers.api.DEX+'/tokens/v1/solana/'+','.join(sorted(wanted)))
            for p in raw if isinstance(raw, list) else []:
                if isinstance(p, dict) and p.get('chainId') == 'solana' and market.get(p, 'baseToken.address') in wanted:
                    actual.append(p)
        except Exception: pass
    stats['unindexed_curve_leads'] = sum(not any(market.get(p, 'baseToken.address') == c['baseToken']['address'] for p in actual) for c in curves)
    stats['market_rows'] = len(market.merge_pools(actual))
    stats['protocol_leads']=dict(Counter(p.get('discoveryEvidence',{}).get('protocol','raydium') for p in leads))
    return market.merge_pools(actual), stats, archived, leads


def reserve_trade(tx, signature, pool, now):
    """One recognized swap per transaction; vault changes in token units, not USD."""
    if not valid_tx(tx, signature, now, 300): return None
    matched = []
    for ix in instructions(tx):
        found = layout_for(ix)
        if found:
            spec, a = found
            if spec['protocol'] == 'pumpswap' and spec['name'] in ('buy', 'buy_exact_quote_in', 'sell'):
                if a['pool'] == pool['pairAddress'] and a['base_mint'] == market.get(pool, 'baseToken.address') and a['quote_mint'] == market.get(pool, 'quoteToken.address'):
                    matched.append((a['pool_base_token_account'], a['pool_quote_token_account'], spec['name']))
    touches=[ix for ix in instructions(tx) if ix.get('programId')==PROGRAMS['pumpswap']
             and pool['pairAddress'] in (ix.get('accounts') or [])]
    if len(matched) != 1 or len(touches) != 1: return None
    keys = [k.get('pubkey') if isinstance(k, dict) else k for k in tx['transaction']['message'].get('accountKeys', [])]
    base_vault, quote_vault, name = matched[0]
    def balance(rows, vault, mint):
        candidates = [r for r in rows if isinstance(r, dict) and isinstance(r.get('accountIndex'), int)
                      and 0 <= r['accountIndex'] < len(keys) and keys[r['accountIndex']] == vault and r.get('mint') == mint]
        if len(candidates) != 1: raise ValueError('balance_identity')
        v = candidates[0]['uiTokenAmount']; decimals = v['decimals']
        if not isinstance(decimals, int) or not 0 <= decimals <= 18: raise ValueError('decimals')
        return int(v['amount'])/10**decimals, decimals
    try:
        pre, post = tx['meta']['preTokenBalances'], tx['meta']['postTokenBalances']
        b0, bd = balance(pre, base_vault, market.get(pool, 'baseToken.address'))
        b1, bd1 = balance(post, base_vault, market.get(pool, 'baseToken.address'))
        q0, qd = balance(pre, quote_vault, market.get(pool, 'quoteToken.address'))
        q1, qd1 = balance(post, quote_vault, market.get(pool, 'quoteToken.address'))
        if bd != bd1 or qd != qd1 or min(b0, b1, q0, q1) <= 0: return None
        db, dq = b1-b0, q1-q0
        kind = 'buy' if db < 0 and dq > 0 else 'sell' if db > 0 and dq < 0 else None
        if kind is None or (name == 'sell') != (kind == 'sell'): return None
        return {'signature': signature, 'at': tx['blockTime'], 'kind': kind,
                'base_reserve_change': db, 'quote_reserve_change': dq,
                'base_reserve': b1, 'quote_reserve': q1, 'quote_mint': market.get(pool, 'quoteToken.address'),
                'quote_per_base_reserve_ratio': q1/b1, 'scope': 'sampled net vault changes; fees included; no USD/LP safety assertion'}
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError): return None


def sample_market(providers, pools, now):
    eligible = [p for p in pools if prior.young(p, now) and 'pump' in str(p.get('dexId', '')).lower()
                and market.amount(market.get(p, 'liquidity.usd')) is not None]
    eligible.sort(key=lambda p: -(market.amount(market.get(p, 'volume.m5')) or 0))
    out = {'scope': 'at most one pool / two transactions; sampled lower bounds, never full five-minute volume',
           'status': 'no_supported_pool', 'requests': 0, 'buys': 0, 'sells': 0, 'trades': [],
           'complete_window': False, 'usd_volume': None, 'usd_liquidity': None}
    if not eligible: return out
    p = eligible[0]; out.update(pair=p['pairAddress'], mint=market.get(p, 'baseToken.address'))
    try:
        out['requests'] += 1
        rows = providers.rpc('getSignaturesForAddress', [p['pairAddress'], {'limit': 6, 'commitment': 'finalized'}])
        recent = [r for r in rows if isinstance(r, dict) and r.get('err') is None
                  and number(r.get('blockTime')) and 0 <= now-r['blockTime'] <= 300]
        for row in recent[:2]:
            if providers.api.REQUEST_DEADLINE and time.monotonic()+2 >= providers.api.REQUEST_DEADLINE: break
            sig = row['signature']; out['requests'] += 1
            tx = providers.rpc('getTransaction', [sig, {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
            trade = reserve_trade(tx, sig, p, now)
            if trade: out['trades'].append(trade); out[trade['kind']+'s'] += 1
        out['status'] = 'observed_sample' if out['trades'] else 'no_decodable_sample'
        out['quote_reserve_turnover'] = sum(abs(r['quote_reserve_change']) for r in out['trades'])
    except Exception: out['status'] = 'partial_unavailable'
    return out
