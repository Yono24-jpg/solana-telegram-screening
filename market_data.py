"""Independent, bounded public feeds. Never turn FDV into verified market cap."""
import copy
import threading
import time
from collections import Counter
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
    dq=get(dex,'quoteToken.address');gq=get(gecko,'quoteToken.address')
    if dq and gq and dq!=gq:same=False
    if not same:
        result = copy.deepcopy(dex); result['identityConflict'] = True; return result
    prepared = copy.deepcopy(dex)
    if amount(prepared.get('pairCreatedAt')) is None and number(gecko.get('pairCreatedAt')):
        prepared['pairCreatedAt'] = gecko['pairCreatedAt']; prepared['ageSource'] = 'geckoterminal'
    # Never blend liquidity, volume and transaction counts from different snapshots.
    # Prefer the snapshot with the fewest missing mandatory values; never blend metrics.
    quality=lambda p:(len(v3_missing_fields(p)),len(missing_fields(p)))
    result = copy.deepcopy(gecko) if quality(gecko)<quality(prepared) else prepared
    for flag in ('identityConflict','ageConflict'):
        if dex.get(flag) or gecko.get(flag):result[flag]=True
    result.setdefault('dataSource', 'dexscreener')
    da = amount(dex.get('pairCreatedAt')); ga = amount(gecko.get('pairCreatedAt'))
    if da is not None and ga is not None and abs(da-ga) > 120000:
        result['ageConflict'] = True
    description=get(dex,'info.description')
    if isinstance(description,str) and description.strip():
        result.setdefault('info',{})['description']=description[:1200]
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
    if dex is not None and not v3_missing_fields(dex): return select_pool(dex, None)
    try:
        rows = gecko_pools(gecko.request(GECKO+'/networks/solana/pools/'+pair+'?include=base_token,quote_token,dex'))
        for row in rows:
            if row['pairAddress'] == pair and row['baseToken']['address'] == mint:
                result=select_pool(dex,row)
                return cap_refresh(result,api)
    except Exception: pass
    if dex is not None:return cap_refresh(select_pool(dex,None),api)
    raise ValueError('refresh_unavailable_or_identity_mismatch')


def retain_watchlist(state, pools, now, max_age=86400):
    watched = {k:v for k,v in state.get('pool_watchlist', {}).items() if isinstance(v, dict)
               and number(v.get('created_at')) and 0 <= now-v['created_at'] <= max_age}
    for p in pools:
        created = amount(p.get('pairCreatedAt')); pair = p.get('pairAddress'); mint = get(p, 'baseToken.address')
        lp = amount(get(p, 'liquidity.usd')); volume = amount(get(p, 'volume.m5'))
        if not address(pair) or not address(mint) or created is None or not 0 <= now-created/1000 <= max_age: continue
        if lp is None or lp < 5000 or volume is None or volume < 500: continue
        old = watched.get(pair, {})
        watched[pair] = {'mint':mint, 'created_at':created/1000, 'last_seen':now,
                         'last_checked':now, 'first_seen':old.get('first_seen',now)}
    # Bound state; favor young, recently observed pools when capacity is exhausted.
    state['pool_watchlist'] = dict(sorted(watched.items(), key=lambda x:(now-x[1]['created_at'] <= 3600, x[1]['last_seen']), reverse=True)[:200])


def refresh_watchlist(pools, state, api, gecko, now, max_age=86400):
    retain_watchlist(state, pools, now, max_age)
    present = {p.get('pairAddress') for p in pools}
    pending = sorted(((pair,r) for pair,r in state['pool_watchlist'].items() if pair not in present), key=lambda v:v[1].get('last_checked',0))[:40]
    refreshed = []; matched = set()
    for start in range(0,len(pending),20):
        batch = dict(pending[start:start+20])
        try:
            response = api.request(api.DEX+'/latest/dex/pairs/solana/'+','.join(batch))
            for p in response.get('pairs') or []:
                if isinstance(p,dict) and p.get('chainId') == 'solana' and p.get('pairAddress') in batch and get(p,'baseToken.address') == batch[p['pairAddress']]['mint'] and not v3_missing_fields(p):
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
    retain_watchlist(state, refreshed, now, max_age)
    return pools+refreshed


def v3_missing_fields(pool):
    """Required actual values for v3. FDV never substitutes for circulating market cap."""
    paths = CORE + ('volume.h1','marketCap')
    return [path for path in paths if amount(get(pool,path)) is None]


def merge_pools(pools):
    """A later search result cannot overwrite a better market snapshot."""
    result={}
    for pool in pools:
        if not isinstance(pool,dict) or not address(pool.get('pairAddress')): continue
        pair=pool['pairAddress']
        result[pair]=select_pool(result.get(pair),pool) if pair in result else copy.deepcopy(pool)
    return list(result.values())


def hydrate_incomplete(pools, api, gecko, now, limit=40):
    """Retry incomplete *present* pools as well as the existing absent-pool watchlist.

    Bounded pair batches, matched mint+pool identities, one coherent winning snapshot.
    Provider failures preserve missing values and never create passing market evidence.
    """
    pools=merge_pools(pools);positions={p['pairAddress']:i for i,p in enumerate(pools)}
    def priority(p):
        created=amount(p.get('pairCreatedAt')); age=now-created/1000 if created is not None else 86401
        lp=amount(get(p,'liquidity.usd')) or 0
        return (not 60<=age<=3600,not 60<=age<=86400,lp<10000,-lp)
    pending=sorted([p for p in pools if v3_missing_fields(p)],key=priority)[:limit]
    fields=lambda:dict(Counter(k for p in pools for k in v3_missing_fields(p)))
    stats={'incomplete_before':sum(bool(v3_missing_fields(p)) for p in pools),'requested':len(pending),'dex_batches':0,'gecko_batches':0,'recovered':0,
           'missing_before':fields(),'sources':{},'identity_rejections':0,'partial_improvements':0}
    def status(source, **values): stats['sources'].setdefault(source,{}).update(values)
    def failure(source,error):
        code=getattr(error,'code',None)
        status(source,status='http_'+str(code) if isinstance(code,int) else ('rate_budget' if str(error)=='gecko_free_budget' else type(error).__name__))
    def merge_rows(rows, expected):
        if not isinstance(rows,list):raise ValueError('response_shape')
        for row in rows:
            if not isinstance(row,dict) or row.get('chainId')!='solana': continue
            pair=row.get('pairAddress')
            if pair not in expected or get(row,'baseToken.address')!=expected[pair]:
                stats['identity_rejections']+=1;continue
            index=positions[pair];before=len(v3_missing_fields(pools[index]));pools[index]=select_pool(pools[index],row)
            stats['partial_improvements']+=int(len(v3_missing_fields(pools[index]))<before)
    for start in range(0,len(pending),20):
        batch=pending[start:start+20];expected={p['pairAddress']:get(p,'baseToken.address') for p in batch}
        try:
            stats['dex_batches']+=1
            data=api.request(api.DEX+'/latest/dex/pairs/solana/'+','.join(expected))
            if not isinstance(data,dict):raise ValueError('response_shape')
            merge_rows(data.get('pairs') or [],expected)
            status('dex_pairs',status='ok',rows=len(data.get('pairs') or []))
        except Exception as error:failure('dex_pairs',error)
        expected={pair:mint for pair,mint in expected.items() if v3_missing_fields(pools[positions[pair]])}
        if not expected:continue
        try:
            stats['gecko_batches']+=1
            rows=gecko_pools(gecko.request(GECKO+'/networks/solana/pools/multi/'+','.join(expected)+'?include=base_token,quote_token,dex'))
            merge_rows(rows,expected)
            status('gecko_pools',status='ok',rows=len(rows))
        except Exception as error:failure('gecko_pools',error)
    # A mint endpoint is distinct from the pair endpoint; never treat the CA as a pool.
    unresolved=[p for p in pending if v3_missing_fields(pools[positions[p['pairAddress']]])]
    for start in range(0,len(unresolved),30):
        batch=unresolved[start:start+30];expected={p['pairAddress']:get(p,'baseToken.address') for p in batch}
        try:
            rows=api.request(api.DEX+'/tokens/v1/solana/'+','.join(dict.fromkeys(expected.values())))
            merge_rows(rows,expected);status('dex_tokens',status='ok',rows=len(rows))
        except Exception as error:failure('dex_tokens',error)
    # Independently supplied circulating valuation; do not synthesize cap from mint supply/FDV.
    # At most two lookups per cycle, only for otherwise useful, cap-missing snapshots.
    eligible=[pools[positions[p['pairAddress']]] for p in pending]
    eligible=[p for p in eligible if v3_missing_fields(p)==['marketCap'] and (amount(get(p,'liquidity.usd')) or 0)>=10000
              and (amount(get(p,'volume.h1')) or 0)>=5000]
    for p in eligible[:2]:
        mint=get(p,'baseToken.address')
        try:
            url='https://api.coingecko.com/api/v3/coins/solana/contract/'+mint
            raw=api.request(url); proof=verified_cap(raw,mint,p,now)
            if proof:
                p['marketCap']=proof['usd'];p['marketCapEvidence']=dict(proof,url=url)
                status('coingecko_contract',status='verified')
            else:status('coingecko_contract',status='identity_freshness_or_supply_unverified')
        except Exception as error:failure('coingecko_contract',error)
    stats['incomplete_after']=sum(bool(v3_missing_fields(p)) for p in pools)
    stats['missing_after']=fields()
    stats['recovered']=stats['incomplete_before']-stats['incomplete_after']
    return pools,stats


def verified_cap(raw,mint,pool,now):
    """Bind CoinGecko cap to exact Solana CA, recent price and circulating supply."""
    if not isinstance(raw,dict) or get(raw,'platforms.solana')!=mint:return None
    updated=timestamp(raw.get('last_updated'));data=raw.get('market_data') or {}
    cap=amount(get(data,'market_cap.usd'));price=amount(get(data,'current_price.usd'));supply=amount(data.get('circulating_supply'))
    pair_price=amount(pool.get('priceUsd'))
    if updated is None or not 0<=now-updated<=240:return None
    if any(x is None or x<=0 for x in (cap,price,supply,pair_price)):return None
    if abs(cap-price*supply)/cap>0.02 or abs(price-pair_price)/pair_price>0.1:return None
    return {'usd':cap,'provider':'coingecko_contract','mint':mint,'updated_at':updated,'observed_at':now,
            'circulating_supply':supply,'valuation_price_usd':price}


def cap_refresh(pool,api):
    """Final refresh must reverify an alternate valuation, never reuse stale cap."""
    if v3_missing_fields(pool)!=['marketCap']:return pool
    mint=get(pool,'baseToken.address');url='https://api.coingecko.com/api/v3/coins/solana/contract/'+mint
    try:
        raw=api.request(url);proof=verified_cap(raw,mint,pool,time.time())
        if proof:pool['marketCap']=proof['usd'];pool['marketCapEvidence']=dict(proof,url=url)
    except Exception:pass
    return pool


def configured_mints(path, now):
    """An explicit, expiring CA watchlist is retrieval only, never a security allowlist."""
    if not path:return []
    try:
        import json
        from pathlib import Path
        config=json.loads(Path(path).read_text())
        result=[]
        for row in config.get('tokens',[])[:20]:
            if not isinstance(row,dict) or not address(row.get('mint')):continue
            expires=row.get('expires_at');added=row.get('added_at')
            if not number(expires) or not number(added) or not added<=now<expires or expires-added>86400:continue
            if row['mint'] not in result:result.append(row['mint'])
        return result
    except Exception:return []
