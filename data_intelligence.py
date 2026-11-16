"""Official read-only providers, bounded usage and explicit partial coverage. No trading."""
import json
import os
import threading
import time
import urllib.request
from urllib.parse import urlencode,urlsplit
from screening_rules import address,amount,number,timestamp

JUP='https://api.jup.ag'
BIRD='https://public-api.birdeye.so'
RUG='https://api.rugcheck.xyz'
READ_METHODS={'getAccountInfo','getMultipleAccounts','getTokenLargestAccounts','getTokenAccountsByOwner',
              'getTokenSupply','getTransaction','getSignaturesForAddress','getSlot','getGenesisHash','getBlockTime'}


class Unavailable(ValueError):pass


class Client:
    def __init__(self,api,state):
        self.api=api;self.state=state;self.lock=threading.Lock();self.counts={};self.status={}
        self.tokens_by_mint={}
        for name,key in [('helius','HELIUS_API_KEY'),('birdeye','BIRDEYE_API_KEY')]:
            if not os.environ.get(key):self.status[name]={'status':'not_configured'}
    def credentials(self):
        rpc=os.environ.get('SOLANA_RPC_URL','')
        return {'helius':{'configured':bool(os.environ.get('HELIUS_API_KEY')) or urlsplit(rpc).hostname=='mainnet.helius-rpc.com'},
                'birdeye':{'configured':bool(os.environ.get('BIRDEYE_API_KEY'))},
                'jupiter':{'configured':bool(os.environ.get('JUPITER_API_KEY')),'keyless_supported':True},
                'rugcheck':{'configured':bool(os.environ.get('RUGCHECK_BEARER_TOKEN')),'public_read_supported':True},
                'solana_rpc':{'configured':bool(rpc),'public_fallback':True},
                'x':{'configured':bool(os.environ.get('X_BEARER_TOKEN')),'reads_enabled':os.environ.get('X_READS_ENABLED')=='1',
                     'requirement':'owner-enabled official X API bearer token with read entitlement; no paid access enabled'}}
    def request(self,provider,url,data=None,headers=None):
        # Only internally constructed official URLs; credentials never enter status records.
        host=urlsplit(url).hostname
        official={'jupiter':{'api.jup.ag'},'birdeye':{'public-api.birdeye.so'},'rugcheck':{'api.rugcheck.xyz'},
                  'helius':{'mainnet.helius-rpc.com'},'solana_rpc':{'api.mainnet-beta.solana.com'}}
        configured=os.environ.get('SOLANA_RPC_URL')
        if urlsplit(url).scheme!='https' or (host not in official.get(provider,set()) and not (provider=='configured_rpc' and url==configured)):
            raise Unavailable('provider_url_not_allowed')
        now=time.time();day=int(now//86400);max_run=80 if 'rpc' in provider or provider=='helius' else (4 if provider=='jupiter' else 12)
        with self.lock:
            record=self.state.setdefault('provider_state_v5',{}).setdefault(provider,{})
            if record.get('day')!=day:record.update(day=day,requests=0)
            reason=None
            if now<record.get('retry_after',0):reason='backoff'
            elif self.counts.get(provider,0)>=max_run or record.get('requests',0)>=(5000 if max_run==80 else 1000):reason='local_quota'
            elif provider=='jupiter' and now-record.get('last_request_at',0)<2.1:reason='local_spacing'
            if reason:
                self.status[provider]={'status':reason,'at':now};raise Unavailable(reason)
            record.update(at=now,last_request_at=now,requests=record.get('requests',0)+1)
            self.counts[provider]=self.counts.get(provider,0)+1
        try:
            if headers:
                remaining=(self.api.REQUEST_DEADLINE-time.monotonic()) if self.api.REQUEST_DEADLINE else 8
                if remaining<=0:raise TimeoutError()
                import evidence
                req=urllib.request.Request(url,data=None if data is None else json.dumps(data).encode(),
                    headers={'Accept':'application/json','Content-Type':'application/json','User-Agent':'MAILHunter/5.0',**headers})
                with urllib.request.build_opener(evidence.NoRedirect).open(req,timeout=min(8,remaining)) as response:
                    raw=response.read(1000001)
                if len(raw)>1000000:raise ValueError()
                result=json.loads(raw)
            else:result=self.api.request(url) if data is None else self.api.request(url,data)
            self.status[provider]={'status':'ok','at':time.time()}
            return result
        except Exception as error:
            code=getattr(error,'code',None);status='http_'+str(code) if isinstance(code,int) else type(error).__name__
            delay=0
            if code==429:
                try:delay=float((getattr(error,'headers',{}) or {}).get('Retry-After',120))
                except (TypeError,ValueError):delay=120
                delay=max(60,min(900,delay)) if number(delay) else 120
            elif code in (401,403):delay=3600
            if delay:record['retry_after']=time.time()+delay
            self.status[provider]={'status':status,'at':time.time()}
            raise Unavailable(status) from None
    def rpc(self,method,params):
        if method not in READ_METHODS:raise Unavailable('rpc_method_not_read_only')
        routes=[];key=os.environ.get('HELIUS_API_KEY');configured=os.environ.get('SOLANA_RPC_URL')
        if key:routes.append(('helius','https://mainnet.helius-rpc.com/?'+urlencode({'api-key':key})))
        if configured and urlsplit(configured).scheme=='https':routes.append(('configured_rpc',configured))
        routes.append(('solana_rpc','https://api.mainnet-beta.solana.com'))
        tried=set()
        for provider,url in routes:
            if url in tried:continue
            tried.add(url)
            try:
                result=self.request(provider,url,{'jsonrpc':'2.0','id':1,'method':method,'params':params})
                if not isinstance(result,dict) or 'error' in result or result.get('result') is None:
                    self.status[provider]={'status':'rpc_error_or_empty','at':time.time()};continue
                payload=result['result']
                if isinstance(payload,dict) and 'value' in payload and payload['value'] is None:
                    self.status[provider]={'status':'rpc_value_missing','at':time.time()};continue
                return payload
            except Unavailable:continue
        raise Unavailable('all_rpc_sources_unavailable')
    def jupiter(self,path):
        key=os.environ.get('JUPITER_API_KEY');return self.request('jupiter',JUP+path,headers={'x-api-key':key} if key else None)
    def token_rows(self,mints):
        selected=list(dict.fromkeys(m for m in mints if address(m)))[:30]
        missing=[m for m in selected if m not in self.tokens_by_mint]
        if missing:
            try:
                rows=self.jupiter('/tokens/v2/search?'+urlencode({'query':','.join(missing)}))
                if not isinstance(rows,list):raise Unavailable('invalid_jupiter_shape')
                for r in rows:
                    if isinstance(r,dict) and r.get('id') in missing:self.tokens_by_mint[r['id']]=r
            except Unavailable:pass
        return {m:self.tokens_by_mint[m] for m in selected if m in self.tokens_by_mint}
    def trending(self):
        try:
            rows=self.jupiter('/tokens/v2/toptrending/5m')
            if not isinstance(rows,list):raise Unavailable('invalid_jupiter_shape')
            rows=[r for r in rows[:30] if isinstance(r,dict) and address(r.get('id'))]
            for r in rows:self.tokens_by_mint[r['id']]=r
            return rows
        except Unavailable:return []
    def birdeye(self,mint):
        key=os.environ.get('BIRDEYE_API_KEY')
        if not key:self.status['birdeye']={'status':'not_configured'};return None
        try:
            raw=self.request('birdeye',BIRD+'/defi/token_overview?'+urlencode({'address':mint}),headers={'X-API-KEY':key,'x-chain':'solana'})
            data=raw.get('data') if isinstance(raw,dict) and raw.get('success') is True else None
            if not isinstance(data,dict) or data.get('address')!=mint:raise Unavailable('birdeye_identity_unverified')
            return data
        except Unavailable:return None
    def rugcheck(self,mint,summary=False):
        if not address(mint):raise Unavailable('invalid_mint')
        key=os.environ.get('RUGCHECK_BEARER_TOKEN')
        return self.request('rugcheck',RUG+'/v1/tokens/'+mint+'/report'+('/summary' if summary else ''),headers={'Authorization':key if key.startswith('Bearer ') else 'Bearer '+key} if key else None)
    def enrich(self,pools):
        pending=[p for p in pools if amount(p.get('marketCap')) is None and address((p.get('baseToken') or {}).get('address'))]
        rows=self.token_rows([(p.get('baseToken') or {})['address'] for p in pending])
        recovered=0
        for pool in pending:
            mint=pool['baseToken']['address'];row=rows.get(mint);proof=cap_proof(row,mint,pool,time.time())
            if proof:pool['marketCap']=proof['usd'];pool['marketCapEvidence']=proof;recovered+=1
        conflicts=0
        for pool in pools:
            mint=(pool.get('baseToken') or {}).get('address');row=self.tokens_by_mint.get(mint)
            proof=cap_proof(row,mint,pool,time.time());cap=amount(pool.get('marketCap'))
            if proof and cap is not None and cap>0 and abs(cap-proof['usd'])/proof['usd']>.2:
                pool['valuationConflict']=True;pool['valuationConflictEvidence']={'primary_cap':cap,'reference':proof};conflicts+=1
        # Birdeye is optional authenticated corroboration. It cannot replace pool metrics.
        birdeye_reads=0
        if os.environ.get('BIRDEYE_API_KEY'):
            for pool in pending[:2]:
                mint=pool['baseToken']['address'];data=self.birdeye(mint);birdeye_reads+=1
                if data:
                    pool['_birdeye_evidence']={'mint':mint,'observed_at':time.time(),'price':data.get('price'),
                        'market_cap':data.get('mc'),'scope':'token overview; not a pool or safety clearance'}
        return {'requested_mints':len(set(p['baseToken']['address'] for p in pending[:30])),'cap_recovered':recovered,
                'birdeye_reads':birdeye_reads,
                'cap_conflicts':conflicts,
                'scope':'token circulating cap only; no aggregate volumes/transactions substituted for pool metrics'}


def cap_proof(row,mint,pool,now):
    if not isinstance(row,dict) or row.get('id')!=mint:return None
    updated=timestamp(row.get('updatedAt'));cap=amount(row.get('mcap'));price=amount(row.get('usdPrice'));supply=amount(row.get('circSupply'));quote=amount(pool.get('priceUsd'))
    if updated is None or not 0<=now-updated<=120:return None
    if any(v is None or v<=0 for v in (cap,price,supply,quote)):return None
    if abs(cap-price*supply)/cap>.02 or abs(price-quote)/quote>.1:return None
    return {'provider':'jupiter_tokens_v2','mint':mint,'usd':cap,'circulating_supply':supply,'price_usd':price,'updated_at':updated,'observed_at':now}


def client(api):
    value=getattr(api,'DATA_INTELLIGENCE',None)
    return value if isinstance(value,Client) else None


def watch(state,pool,narrative,reason,now,verified=False):
    """Research observations are internal. Only the existing deliver gate can send."""
    if narrative.get('reject') or not narrative.get('label'):return
    mint=(pool.get('baseToken') or {}).get('address');pair=pool.get('pairAddress')
    if not address(mint) or not address(pair):return
    records=state.setdefault('narrative_watch_v5',{})
    records[mint+':'+pair]={'at':now,'mint':mint,'pair':pair,'name':pool['baseToken'].get('name'),
        'tier':'VERIFIED ALERT' if verified else 'NARRATIVE WATCH','reason':reason or 'security_pending',
        'narrative':narrative['label'],'source_urls':[s.get('url') for s in narrative.get('sources',[])[:2]],
        'security_verified':verified,'internal_only':not verified}
    state['narrative_watch_v5']=dict(sorted(((k,v) for k,v in records.items() if 0<=now-v['at']<=7*86400),key=lambda x:-x[1]['at'])[:300])


def history_review(state,now):
    """Observed rejected cohorts, no hindsight safety substitution or threshold tuning."""
    records=[r for r in state.get('memory_v5',{}).values() if r.get('decision') in ('v5_market_cap','v5_pool_age')]
    groups={}
    for reason in ('v5_market_cap','v5_pool_age'):
        rows=[r for r in records if r['decision']==reason]
        groups[reason]={'records':len(rows),'observed_24h':sum(r.get('samples',{}).get('86400',{}).get('status')=='observed' for r in rows),
            'security_complete_at_first_observation':sum(r.get('initial_safety_complete') is True for r in rows),
            'original_cap_age_archived':sum(number(r.get('market_cap_at_observation')) and number(r.get('pool_age_at_observation')) for r in rows)}
    return {'at':now,'groups':groups,'filter_change':False,
        'conclusion':'Insufficient point-in-time safety/24h coverage to infer missed safe opportunities. Bounds unchanged; selection bias applies.'}
