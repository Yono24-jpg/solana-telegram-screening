"""Independent, bounded public feeds. Never turn FDV into verified market cap."""
import copy
import threading
import time
from screening_rules import address, amount, number, timestamp

GECKO = 'https://api.geckoterminal.com/api/v2'
QUOTE_ASSETS = {'So11111111111111111111111111111111111111112',
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'}
CORE = ('pairCreatedAt', 'liquidity.usd', 'volume.m5', 'txns.m5.buys',
        'txns.m5.sells', 'priceChange.m5', 'priceUsd')


def get(data, path):
    for key in path.split('.'):
        data = data.get(key) if isinstance(data, dict) else None
    return data


def missing_fields(pool):
    missing = [key for key in CORE if amount(get(pool, key)) is None]
    if not any(amount(pool.get(key)) is not None and amount(pool[key]) > 0 for key in ('marketCap', 'fdv')):
        missing.append('marketCap_or_fdv')
    return missing


class GeckoClient:
    """Nine requests per rolling minute, including failed requests and previous runs."""
    def __init__(self, api, state):
        self.api = api; self.state = state; self.lock = threading.Lock(); self.limited = 0
    def request(self, url):
        if not url.startswith(GECKO + '/'):
            raise ValueError('unsupported_gecko_url')
        with self.lock:
            now = time.time()
            calls = [t for t in self.state.get('gecko_requests', []) if number(t) and 0 <= now-t < 60]
            self.state['gecko_requests'] = calls
            if len(calls) >= 9:
                self.limited += 1
                raise RuntimeError('gecko_free_budget')
            calls.append(now)
        return self.api.request(url)


def gecko_pools(payload):
    if not isinstance(payload, dict): return []
    included = {r['id']:r.get('attributes', {}) for r in payload.get('included', [])
                if isinstance(r, dict) and isinstance(r.get('id'), str) and isinstance(r.get('attributes'), dict)}
    rows = payload.get('data', [])
    if isinstance(rows, dict): rows = [rows]
    pools = []
    for row in rows if isinstance(rows, list) else []:
        try:
            a = row['attributes']; rel = row['relationships']
            pair = a['address']; base_id = rel['base_token']['data']['id']; quote_id = rel['quote_token']['data']['id']
            if not all(isinstance(v, str) and v.startswith('solana_') for v in (base_id, quote_id)): continue
            mint = base_id[len('solana_'):]; quote = quote_id[len('solana_'):]
            if not all(address(v) for v in (pair, mint, quote)) or mint in QUOTE_ASSETS or mint == quote: continue
            token = included.get(base_id, {})
            if token.get('address', mint) != mint: continue
            created = timestamp(a.get('pool_created_at'))
            changes = a.get('price_change_percentage') or {}; volumes = a.get('volume_usd') or {}
            transactions = a.get('transactions') or {}
            pool = {'chainId':'solana', 'pairAddress':pair,
                    'baseToken':{'address':mint, 'name':token.get('name') or 'Token belum bernama', 'symbol':token.get('symbol') or mint[:6]},
                    'quoteToken':{'address':quote}, 'dexId':rel.get('dex', {}).get('data', {}).get('id'),
                    'pairCreatedAt':created*1000 if created is not None else None,
                    'priceUsd':amount(a.get('base_token_price_usd')), 'liquidity':{'usd':amount(a.get('reserve_in_usd'))},
                    'marketCap':amount(a.get('market_cap_usd')), 'fdv':amount(a.get('fdv_usd')),
                    'volume':{k:amount(v) for k,v in volumes.items()},
                    'priceChange':{k:amount(v) for k,v in changes.items()}, 'txns':{},
                    'dataSource':'geckoterminal', 'info':{'socials':[]}}
            for window, values in transactions.items():
                if isinstance(values, dict): pool['txns'][window] = {k:amount(values.get(k)) for k in ('buys','sells','buyers','sellers')}
            pools.append(pool)
        except (KeyError, TypeError, ValueError, AttributeError): continue
    return pools


def select_pool(dex, gecko):
    """Use one coherent market snapshot; only add matched identity/metadata/creation time."""
    if dex is None: return copy.deepcopy(gecko)
    if gecko is None:
        result = copy.deepcopy(dex); result.setdefault('dataSource', 'dexscreener'); return result
    same = dex.get('pairAddress') == gecko.get('pairAddress') and get(dex, 'baseToken.address') == get(gecko, 'baseToken.address')
    if not same:
        result = copy.deepcopy(dex); result['identityConflict'] = True; return result
    prepared = copy.deepcopy(dex)
    if amount(prepared.get('pairCreatedAt')) is None and number(gecko.get('pairCreatedAt')):
        prepared['pairCreatedAt'] = gecko['pairCreatedAt']; prepared['ageSource'] = 'geckoterminal'
    # Never blend liquidity, volume and transaction counts from different snapshots.
    result = prepared if not missing_fields(prepared) or missing_fields(gecko) else copy.deepcopy(gecko)
    result.setdefault('dataSource', 'dexscreener')
    da = amount(dex.get('pairCreatedAt')); ga = amount(gecko.get('pairCreatedAt'))
    if da is not None and ga is not None and abs(da-ga) > 120000:
        result['ageConflict'] = True
    socials = get(dex, 'info.socials')
    if isinstance(socials, list):
        result.setdefault('info', {})['socials'] = copy.deepcopy(socials)
    return result


def refresh_pool(pair, mint, api, gecko):
    dex = None
    try:
        payload = api.request(api.DEX+'/latest/dex/pairs/solana/'+pair)
        for row in payload.get('pairs') or []:
            if isinstance(row, dict) and row.get('chainId') == 'solana' and row.get('pairAddress') == pair and get(row, 'baseToken.address') == mint:
                dex = row; break
    except Exception: pass
    if dex is not None and not missing_fields(dex): return select_pool(dex, None)
    try:
        rows = gecko_pools(gecko.request(GECKO+'/networks/solana/pools/'+pair+'?include=base_token,quote_token,dex'))
        for row in rows:
            if row['pairAddress'] == pair and row['baseToken']['address'] == mint:
                return select_pool(dex, row)
    except Exception: pass
    if dex is not None: return select_pool(dex, None)
    raise ValueError('refresh_unavailable_or_identity_mismatch')


def retain_watchlist(state, pools, now):
    watched = {k:v for k,v in state.get('pool_watchlist', {}).items() if isinstance(v, dict)
               and number(v.get('created_at')) and 0 <= now-v['created_at'] <= 86400}
    for p in pools:
        created = amount(p.get('pairCreatedAt')); pair = p.get('pairAddress'); mint = get(p, 'baseToken.address')
        lp = amount(get(p, 'liquidity.usd')); volume = amount(get(p, 'volume.m5'))
        if not address(pair) or not address(mint) or created is None or not 0 <= now-created/1000 <= 86400: continue
        if lp is None or lp < 5000 or volume is None or volume < 500: continue
        old = watched.get(pair, {})
        watched[pair] = {'mint':mint, 'created_at':created/1000, 'last_seen':now,
                         'last_checked':now, 'first_seen':old.get('first_seen',now)}
    # Bound state; favor young, recently observed pools when capacity is exhausted.
    state['pool_watchlist'] = dict(sorted(watched.items(), key=lambda x:(now-x[1]['created_at'] <= 3600, x[1]['last_seen']), reverse=True)[:200])


def refresh_watchlist(pools, state, api, gecko, now):
    retain_watchlist(state, pools, now)
    present = {p.get('pairAddress') for p in pools}
    pending = sorted(((pair,r) for pair,r in state['pool_watchlist'].items() if pair not in present), key=lambda v:v[1].get('last_checked',0))[:40]
    refreshed = []; matched = set()
    for start in range(0,len(pending),20):
        batch = dict(pending[start:start+20])
        try:
            response = api.request(api.DEX+'/latest/dex/pairs/solana/'+','.join(batch))
            for p in response.get('pairs') or []:
                if isinstance(p,dict) and p.get('chainId') == 'solana' and p.get('pairAddress') in batch and get(p,'baseToken.address') == batch[p['pairAddress']]['mint'] and not missing_fields(p):
                    refreshed.append(select_pool(p,None)); matched.add(p['pairAddress'])
        except Exception: pass
    # One bounded Gecko batch covers pools not yet indexed by DexScreener.
    fallback = dict((pair,r) for pair,r in pending if pair not in matched)
    fallback = dict(list(fallback.items())[:20])
    if fallback:
        try:
            payload = gecko.request(GECKO+'/networks/solana/pools/multi/'+','.join(fallback)+'?include=base_token,quote_token,dex')
            for p in gecko_pools(payload):
                if p['pairAddress'] in fallback and p['baseToken']['address'] == fallback[p['pairAddress']]['mint']:
                    refreshed.append(p)
        except Exception: pass
    for pair,_ in pending: state['pool_watchlist'][pair]['last_checked'] = now
    retain_watchlist(state, refreshed, now)
    return pools+refreshed
