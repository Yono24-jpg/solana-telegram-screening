"""Read-only evidence collectors. Never infer missing social or on-chain facts."""
import json
import os
import re
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit
from screening_rules import address, number, timestamp, social_links, trade_evidence


class PublicPosts(HTMLParser):
    def __init__(self):
        super().__init__(); self.posts = []; self.depth = 0; self.text = []; self.dates = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'time' and a.get('datetime'):
            self.dates.append(a['datetime'])
        if tag == 'div' and 'tgme_widget_message_text' in a.get('class', '').split():
            self.depth = 1; self.text = []
        elif self.depth and tag == 'div': self.depth += 1
    def handle_endtag(self, tag):
        if self.depth and tag == 'div':
            self.depth -= 1
            if not self.depth: self.posts.append(' '.join(self.text)[:4000])
    def handle_data(self, data):
        if self.depth: self.text.append(data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_not_allowed')


def public_read(url, api, bearer=None, as_text=False):
    # URLs are generated internally from validated public handles, never arbitrary metadata hosts.
    remaining = (api.REQUEST_DEADLINE-time.monotonic()) if api.REQUEST_DEADLINE else 8
    if remaining <= 0: raise TimeoutError('evidence_budget')
    headers = {'User-Agent': 'SolanaScreening/2.0', 'Accept': 'text/html' if as_text else 'application/json'}
    if bearer: headers['Authorization'] = 'Bearer ' + bearer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=min(8, remaining)) as response:
        if urlsplit(response.url).hostname != urlsplit(url).hostname:
            raise ValueError('redirect_not_allowed')
        raw = response.read(1000001)
        if len(raw) > 1000000: raise ValueError('response_too_large')
    return raw.decode('utf-8') if as_text else json.loads(raw)


def rpc(api, method, params):
    result = api.request(os.environ.get('SOLANA_RPC_URL') or 'https://api.mainnet-beta.solana.com',
                         {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    if not isinstance(result, dict) or 'error' in result or 'result' not in result:
        raise ValueError('rpc_unavailable')
    return result['result']


def mint_creation(mint, api, now):
    out = {'verified': False, 'age_seconds': None, 'status': 'history_incomplete'}
    before = None; oldest = None
    try:
        for _ in range(3):
            options = {'limit': 1000, 'commitment': 'finalized'}
            if before: options['before'] = before
            rows = rpc(api, 'getSignaturesForAddress', [mint, options])
            if not isinstance(rows, list): return out
            if rows:
                if not isinstance(rows[-1], dict) or not rows[-1].get('signature'): return out
                if rows[-1]['signature'] == before: return out
                oldest = rows[-1]; before = oldest['signature']
            if len(rows) < 1000:
                if not oldest or oldest.get('err') is not None: return out
                tx = rpc(api, 'getTransaction', [oldest['signature'], {'encoding': 'jsonParsed',
                          'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
                if not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict) or tx['meta'].get('err') is not None:
                    return out
                when = tx.get('blockTime')
                if not number(when) or not 0 <= now-when: return out
                instructions = list(tx.get('transaction', {}).get('message', {}).get('instructions', []))
                for group in tx['meta'].get('innerInstructions') or []:
                    instructions.extend(group.get('instructions', []))
                for instruction in instructions:
                    p = instruction.get('parsed', {})
                    if (instruction.get('programId') in (api.PROGRAM, api.TOKEN_2022)
                            and isinstance(p, dict) and p.get('type') in ('initializeMint', 'initializeMint2')
                            and p.get('info', {}).get('mint') == mint):
                        return {'verified': True, 'created_at': when, 'age_seconds': now-when,
                                'status': 'finalized_initialize_mint', 'signature': oldest['signature']}
                return out
    except Exception:
        out['status'] = 'rpc_unavailable_or_incomplete'
    return out


def security(mint, api, now):
    out = {'score': 0, 'authority_verified': False, 'complete': False, 'reject': None, 'risks': [], 'top10_accounts_pct': None}
    try:
        account = rpc(api, 'getAccountInfo', [mint, {'encoding': 'base64', 'commitment': 'finalized'}])['value']
        reason = api.security_reason(account)
        if reason:
            out['reject'] = reason; return out
        out.update(authority_verified=True, score=40)
    except Exception:
        out['reject'] = 'mint_security_unavailable'; return out
    try:
        pct = api.holder_concentration(mint)
        if not number(pct) or not 0 <= pct <= 100: raise ValueError('invalid_holders')
        out['top10_accounts_pct'] = round(pct, 2)
        if pct > 30: out['reject'] = 'top10_accounts_over_30'; return out
        out['score'] += 30
    except Exception: out['risks'].append('Distribusi token belum terverifikasi')
    try:
        report = api.request('https://api.rugcheck.xyz/v1/tokens/' + mint + '/report/summary')
        reason = api.rugcheck_risk_reason(report)
        if reason in ('danger_risk_flag', 'high_risk_score'):
            out['reject'] = reason; return out
        if reason: raise ValueError('risk_report_incomplete')
        out['score'] += 30
    except Exception: out['risks'].append('Laporan RugCheck belum tersedia')
    out['complete'] = out['score'] == 100
    return out


def x_analysis(handle, mint, api, now):
    result = {'status': 'api_not_configured', 'score': None, 'verified_link': False, 'complete': False, 'risks': []}
    token = os.environ.get('X_BEARER_TOKEN')
    # Reading X may incur charges; it is disabled unless explicitly configured by the owner.
    if not token or os.environ.get('X_READS_ENABLED', '0') != '1': return result
    try:
        query = urlencode({'user.fields': 'created_at,description,public_metrics,protected,username'})
        user = public_read('https://api.x.com/2/users/by/username/' + handle + '?' + query, api, bearer=token)['data']
        if user.get('username', '').lower() != handle.lower() or user.get('protected'): raise ValueError('identity_or_private')
        result['verified_link'] = True
        uid = str(user['id'])
        if not uid.isdigit(): raise ValueError('invalid_user_id')
        query = urlencode({'max_results': 20, 'tweet.fields': 'created_at,public_metrics,author_id'})
        payload = public_read('https://api.x.com/2/users/' + uid + '/tweets?' + query, api, bearer=token)
        posts = payload.get('data', [])
        recent = [p for p in posts if isinstance(p, dict) and str(p.get('author_id')) == uid
                  and timestamp(p.get('created_at')) is not None and 0 <= now-timestamp(p['created_at']) <= 604800]
        if not recent: result['status'] = 'no_recent_posts'; return result
        identity = mint in user.get('description', '') or any(mint in p.get('text', '') for p in recent)
        metrics = [p.get('public_metrics') for p in recent]
        complete_metrics = all(isinstance(m, dict) and all(number(m.get(k)) and m[k] >= 0
                               for k in ('like_count', 'reply_count', 'retweet_count')) for m in metrics)
        interactions = sum(m['like_count']+m['reply_count']+m['retweet_count'] for m in metrics) if complete_metrics else None
        texts = [p.get('text', '').strip().lower() for p in recent]
        repeat = 1-len(set(texts))/len(texts)
        if not identity: result['risks'].append('X tidak menyebut mint yang sama')
        if repeat > .5: result['risks'].append('Posting X sangat berulang')
        created = timestamp(user.get('created_at'))
        if created is not None and 0 <= now-created < 86400: result['risks'].append('Akun X berumur kurang dari 1 hari')
        score = (40 if identity else 0) + min(25, len(recent)*5) + (min(25, interactions) if interactions is not None else 0) + (10 if repeat <= .3 else 0)
        result.update(status='observed', score=round(score), complete=identity and complete_metrics and len(recent) >= 5 and not result['risks'],
                      posts_7d=len(recent), interactions=interactions, repeated_fraction=round(repeat, 2), identity_consistent=identity)
    except Exception: result['status'] = 'api_unavailable'
    return result


def telegram_analysis(handle, mint, api, now):
    result = {'status': 'unavailable', 'score': None, 'verified_link': False, 'complete': False, 'risks': []}
    try:
        chat = api.tg('getChat', chat_id='@'+handle)
        if (chat.get('type') not in ('channel', 'supergroup') or chat.get('username', '').lower() != handle.lower()):
            result['status'] = 'identity_unverified'; return result
        result['verified_link'] = True
        description = chat.get('description', '')
        pinned = chat.get('pinned_message') or {}
        identity = mint in description or mint in pinned.get('text', '')
        # Member count is informational only and is never used for scoring.
        try:
            members = api.tg('getChatMemberCount', chat_id='@'+handle)
            if isinstance(members, int) and not isinstance(members, bool) and members >= 0: result['members'] = members
        except Exception: pass
        parser = PublicPosts()
        try:
            parser.feed(public_read('https://t.me/s/'+handle, api, as_text=True))
        except Exception: pass
        posts = parser.posts[-30:]
        identity = identity or any(mint in p for p in posts)
        dated = [timestamp(d) for d in parser.dates[-30:]]
        recent = sum(1 for t in dated if t is not None and 0 <= now-t <= 604800)
        normalized = [re.sub(r'\s+', ' ', p.strip().lower()) for p in posts]
        repeat = 1-len(set(normalized))/len(normalized) if normalized else None
        if not identity: result['risks'].append('Telegram tidak menyebut mint yang sama')
        if repeat is not None and repeat > .5: result['risks'].append('Posting Telegram sangat berulang')
        result.update(status='public_posts' if posts else 'metadata_only', identity_consistent=identity,
                      posts_sample=len(posts), posts_7d_observed=recent, repeated_fraction=repeat,
                      score=(40 if identity else 0)+min(30, recent*6)+(20 if posts and repeat <= .3 else 0)+10,
                      complete=identity and recent >= 5 and len(posts) >= 5 and not result['risks'],
                      caveat='Sampel posting publik; aktivitas anggota dan identitas bot tidak dapat dipastikan.')
    except Exception: pass
    return result


def community(pool, api, now):
    links, conflicts = social_links(pool)
    mint = pool['baseToken']['address']
    x = x_analysis(links['x'].rsplit('/', 1)[-1], mint, api, now) if links['x'] else {'score': None, 'complete': False, 'status': 'missing_metadata', 'verified_link': False}
    tg = telegram_analysis(links['telegram'].rsplit('/', 1)[-1], mint, api, now) if links['telegram'] else {'score': None, 'complete': False, 'status': 'missing_metadata', 'verified_link': False}
    score = round((x['score']+tg['score'])/2, 1) if x.get('score') is not None and tg.get('score') is not None else None
    return {'score': score, 'complete': bool(x.get('complete') and tg.get('complete') and not conflicts),
            'x': x, 'telegram': tg, 'metadata_links': links, 'verified_links': {k: links[k] for k, v in [('x', x), ('telegram', tg)] if v.get('verified_link')},
            'risks': conflicts + x.get('risks', []) + tg.get('risks', [])}


def buyers(pool, api, now):
    try:
        data = api.request('https://api.geckoterminal.com/api/v2/networks/solana/pools/' + pool['pairAddress'] + '/trades')
        return trade_evidence(data, pool['baseToken']['address'], now)
    except Exception:
        return {'status': 'unavailable', 'unique_buyers': None, 'strong': False, 'risks': []}
