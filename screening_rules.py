"""Pure, conservative scoring. All scores are evidence rules, not predictions."""
import math
import re
from datetime import datetime
from urllib.parse import urlsplit

MIN_AGE = 60
MAX_AGE = 86400
BASE58 = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amount(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def address(value):
    return isinstance(value, str) and bool(BASE58.fullmatch(value))


def canonical_social(raw, platform):
    if not isinstance(raw, str) or len(raw) > 300:
        return None
    try:
        u = urlsplit(raw)
        if u.scheme not in ('https', 'http') or u.username or u.password or u.port:
            return None
        host = (u.hostname or '').lower()
        parts = [part for part in u.path.split('/') if part]
        if platform == 'x':
            if host not in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com') or len(parts) != 1:
                return None
            handle = parts[0]
            if handle.lower() in ('home', 'intent', 'share', 'search', 'i', 'explore', 'settings'):
                return None
            if not re.fullmatch(r'[A-Za-z0-9_]{1,15}', handle):
                return None
            return 'https://x.com/' + handle.lower()
        if platform == 'telegram':
            if host not in ('t.me', 'www.t.me', 'telegram.me'):
                return None
            if len(parts) == 2 and parts[0] == 's':
                parts = parts[1:]
            if len(parts) != 1 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', parts[0]):
                return None
            if parts[0].lower() in ('share', 'joinchat', 'proxy', 'socks', 'addstickers'):
                return None
            return 'https://t.me/' + parts[0].lower()
    except ValueError:
        return None
    return None


def social_links(pool):
    found = {'x': set(), 'telegram': set()}
    info = pool.get('info') or {}
    rows = info.get('socials', []) if isinstance(info, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for platform in found:
            link = canonical_social(row.get('url'), platform)
            if link:
                found[platform].add(link)
    return {k: next(iter(v)) if len(v) == 1 else None for k, v in found.items()}, [k + '_metadata_conflict' for k, v in found.items() if len(v) > 1]


def market(pool, history, now):
    try:
        if pool['chainId'] != 'solana' or not address(pool['pairAddress']) or not address(pool['baseToken']['address']):
            return {'reject': 'invalid_identity'}
        age = now - pool['pairCreatedAt'] / 1000
        lp = pool['liquidity']['usd']; vol = pool['volume']['m5']
        buys = pool['txns']['m5']['buys']; sells = pool['txns']['m5']['sells']
        cap = pool['marketCap']; m5 = pool['priceChange']['m5']; h1 = pool['priceChange'].get('h1')
        price = amount(pool['priceUsd'])
        if not all(number(x) for x in (age, lp, vol, buys, sells, cap, m5, price)):
            return {'reject': 'missing_market_data'}
        if not MIN_AGE <= age <= MAX_AGE:
            return {'reject': 'pool_age'}
        if cap <= 0 or price <= 0 or min(buys, sells) < 0 or int(buys) != buys or int(sells) != sells:
            return {'reject': 'invalid_market_data'}
        if lp < 10000 or lp / cap < .08:
            return {'reject': 'liquidity'}
        if vol < 1500 or buys < 12 or buys / max(sells, 1) < 1.5:
            return {'reject': 'weak_activity'}
        if m5 < 0 or m5 > 25 or (number(h1) and (h1 < -15 or h1 > 80)):
            return {'reject': 'late_or_falling_price'}
        rows = history.get(pool['pairAddress'], []) if isinstance(history, dict) else []
        eligible = [r for r in rows if isinstance(r, dict) and r.get('mint') == pool['baseToken']['address']
                    and all(number(r.get(k)) for k in ('t', 'price', 'lp', 'volume', 'buys', 'sells'))
                    and 300 <= now-r['t'] <= 900 and r['price'] > 0 and r['lp'] > 0
                    and r['volume'] > 0 and r['buys'] > 0 and r['sells'] >= 0]
        growth = None
        if eligible:
            old = max(eligible, key=lambda r: r['t'])
            growth = {'volume': vol/old['volume'], 'buys': buys/old['buys'],
                      'transactions': (buys+sells)/(old['buys']+old['sells']),
                      'lp_retained': lp/old['lp'], 'price': 100*(price/old['price']-1),
                      'minutes': (now-old['t'])/60}
            if growth['lp_retained'] < .90 or growth['price'] < -5 or growth['price'] > 25:
                return {'reject': 'deterioration_or_late_entry'}
        share = buys/(buys+sells)
        parts = {'buy_pressure': 25*min(1, max(0, (share-.5)/.25)),
                 'buy_activity': 20*min(1, buys/40), 'liquidity': 20*min(1, lp/cap/.15),
                 'volume': 15*min(1, vol/6000), 'early_price': 10*max(0, 1-m5/30),
                 'acceleration': 0}
        if growth:
            parts['acceleration'] = 10*min(1, max(0, min(growth['volume'], growth['buys'], growth['transactions'])-1)/.5)
        score = round(sum(parts.values()), 1)
        if score < 60:
            return {'reject': 'market_score_below_60'}
        strong = (score >= 80 and growth is not None and growth['volume'] >= 1.1 and growth['buys'] >= 1.1
                  and growth['transactions'] >= 1.1 and -5 <= growth['price'] <= 15
                  and sells >= 3 and m5 <= 15 and number(h1) and -15 <= h1 <= 60)
        return {'reject': None, 'score': score, 'parts': {k: round(v, 1) for k, v in parts.items()},
                'age_seconds': age, 'priority': age <= 3600, 'price': price, 'lp': lp, 'volume': vol,
                'buys': buys, 'sells': sells, 'cap': cap, 'm5': m5, 'h1': h1 if number(h1) else None,
                'growth': growth, 'strong': strong}
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return {'reject': 'missing_market_data'}


def trade_evidence(payload, mint, now):
    """Count observed addresses in the last five minutes; never call them humans."""
    out = {'status': 'unavailable', 'unique_buyers': None, 'strong': False, 'risks': []}
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        return out
    seen = set(); wallets = {}; sell_wallets = set(); sizes = {}; count = 0
    for row in payload['data']:
        a = row.get('attributes', {}) if isinstance(row, dict) else {}
        when = timestamp(a.get('block_timestamp'))
        if when is None or not 0 <= now-when <= 300:
            continue
        wallet = a.get('tx_from_address'); tx = a.get('tx_hash'); kind = a.get('kind')
        usd = amount(a.get('volume_in_usd'))
        if not address(wallet) or not isinstance(tx, str) or not tx or tx in seen or usd is None or usd <= 0:
            continue
        # Bind buy/sell direction to the candidate mint, not the pool's assumed base token.
        if kind == 'buy' and a.get('to_token_address') != mint:
            continue
        if kind == 'sell' and a.get('from_token_address') != mint:
            continue
        if kind not in ('buy', 'sell'):
            continue
        if a.get('is_anomalous') is True:
            out['risks'].append('provider_anomalous_trade')
            continue
        seen.add(tx)
        if kind == 'buy':
            count += 1
            wallets[wallet] = wallets.get(wallet, 0) + usd
            key = round(usd, 2); sizes[key] = sizes.get(key, 0) + 1
        else:
            sell_wallets.add(wallet)
    if not wallets:
        return out
    concentration = max(wallets.values()) / sum(wallets.values())
    overlap = len(set(wallets) & sell_wallets) / len(wallets)
    repeats = max(sizes.values()) / count
    risks = list(set(out['risks']))
    if concentration > .30: risks.append('volume_buy_terpusat')
    if overlap > .5: risks.append('banyak_alamat_beli_dan_jual')
    if repeats > .6 and count >= 10: risks.append('nominal_transaksi_berulang')
    out.update(status='observed_sample', unique_buyers=len(wallets), buy_transactions=count,
               top_buyer_share=round(100*concentration, 1), roundtrip_share=round(100*overlap, 1),
               risks=risks, strong=len(wallets) >= 20 and len(sell_wallets) >= 3 and not risks,
               caveat='Sampel alamat unik; bukan bukti manusia atau bebas wash trading.')
    return out


def choose_tier(market_data, security, community, buyers, mint_age):
    if market_data.get('reject') or security.get('reject') or not security.get('authority_verified'):
        return None
    full = (market_data.get('strong') and security.get('complete') and security.get('score', 0) >= 80
            and community.get('complete') and (community.get('score') or 0) >= 80
            and buyers.get('strong') and mint_age.get('verified')
            and number(mint_age.get('age_seconds')) and 0 <= mint_age['age_seconds'] <= MAX_AGE
            and mint_age['age_seconds'] >= market_data.get('age_seconds', MAX_AGE)-60)
    return 'STRONG SIGNAL' if full else 'EARLY WATCH'
