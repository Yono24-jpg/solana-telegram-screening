"""Budgeted official Birdeye Standard reads; token aggregates never clear pool gates."""
import copy
import json
import os
import threading
import time
import urllib.request
from urllib.parse import urlencode
from screening_rules import address,amount,number

COSTS={'price':3,'overview':18}
PATHS={'price':'/defi/price','overview':'/defi/token_overview'}
LIMIT=24000


class Standard:
    def __init__(self,parent):
        self.parent=parent;self.state=parent.state;self.lock=threading.Lock();self.pace=threading.Lock()
        self.stats={'requests':0,'reserved_cu':0,'cache_hits':0,'successes':{},'recovered_cap_fields':0,'reference_fields':0}
        self.record=self.state.setdefault('provider_state_v5',{}).setdefault('birdeye',{})
        if 'cu_days' not in self.record and self.record.get('requests',0)>0:
            # Conservatively import the previous adapter's known overview calls.
            self.record['cu_days']={str(self.record['day']):18*self.record['requests']}
    def transport(self,url,headers):
        import evidence
        deadline=self.parent.api.REQUEST_DEADLINE
        remaining=deadline-time.monotonic() if deadline else 8
        if remaining<=0:raise TimeoutError()
        req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MAILHunter/5.0',**headers})
        with urllib.request.build_opener(evidence.NoRedirect).open(req,timeout=min(8,remaining)) as response:raw=response.read(1000001)
        if len(raw)>1000000:raise ValueError()
        return json.loads(raw)
    def read(self,mint,kind='overview'):
        if kind not in COSTS or not address(mint):return None
        key=os.environ.get('BIRDEYE_API_KEY')
        if not key:self.parent.status['birdeye']={'status':'not_configured'};return None
        # Independent read-only CI jobs cannot bypass the durable production ledger.
        if os.environ.get('BIRDEYE_NETWORK_ENABLED')=='0':return None
        now=time.time();day=int(now//86400);hour=int(now//3600);r=self.record
        with self.lock:
            r.setdefault('endpoints',{});ep=r['endpoints'].setdefault(kind,{})
            cache=r.setdefault('cache',{});entry=cache.get(kind+':'+mint)
            if entry and 0<=now-entry['at']<300:
                self.stats['cache_hits']+=1;return copy.deepcopy(entry['data'])
            days={k:v for k,v in r.get('cu_days',{}).items() if k.isdigit() and day-30<=int(k)<=day}
            r['cu_days']=days
            if r.get('hour')!=hour:r.update(hour=hour,hour_cu=0)
            cost=COSTS[kind];reason=None
            if now<ep.get('retry_after',0):reason='endpoint_backoff'
            elif days.get(str(day),0)+cost>720 or sum(days.values())+cost>LIMIT or r.get('hour_cu',0)+cost>30:reason='local_cu_budget'
            elif self.stats['requests']>=2:reason='cycle_budget'
            if reason:
                self.parent.status['birdeye']={'status':reason,'at':now};return None
            days[str(day)]=days.get(str(day),0)+cost;r.update(at=now,hour_cu=r.get('hour_cu',0)+cost)
            self.stats['requests']+=1;self.stats['reserved_cu']+=cost
        with self.pace:
            # Persisted timestamp also spaces separate scanner processes.
            delay=max(0,r.get('last_request_at',0)+1.05-time.time())
            if delay:time.sleep(delay)
            r['last_request_at']=time.time()
            query={'address':mint,'ui_amount_mode':'raw'}
            if kind=='overview':query['frames']='1h,24h'
            else:query['include_liquidity']='true'
            try:
                raw=self.transport('https://public-api.birdeye.so'+PATHS[kind]+'?'+urlencode(query),{'X-API-KEY':key,'x-chain':'solana'})
                data=raw.get('data') if isinstance(raw,dict) and raw.get('success') is True else None
                if not isinstance(data,dict) or not data:raise ValueError()
                if data.get('address',mint)!=mint or (kind=='overview' and data.get('address')!=mint):raise ValueError()
                # Keep selected numeric/raw fields only; never provider URLs/messages.
                selected={k:v for k,v in data.items() if k in ('price','value','marketCap','mc','circulatingSupply','liquidity','v1hUSD','v24hUSD','updateUnixTime','lastTradeUnixTime','supply','fdv','isScaledUiToken') and (number(v) or isinstance(v,bool))}
                selected.update(address=mint,observed_at=time.time(),endpoint=kind)
                ep.update(status='ok',at=time.time());self.parent.status['birdeye']={'status':'ok','at':time.time()}
                self.stats['successes'][kind]=self.stats['successes'].get(kind,0)+1
                cache[kind+':'+mint]={'at':time.time(),'data':selected}
                r['cache']=dict(sorted(cache.items(),key=lambda x:-x[1]['at'])[:20])
                return copy.deepcopy(selected)
            except Exception as e:
                code=getattr(e,'code',None);status='http_'+str(code) if isinstance(code,int) else 'transport_or_invalid_data'
                delay=86400 if code==403 else 3600 if code==401 else 120
                if code==429:
                    try:delay=max(60,min(900,float(e.headers.get('Retry-After',120))))
                    except Exception:delay=120
                ep.update(status=status,at=time.time(),retry_after=time.time()+delay)
                self.parent.status['birdeye']={'status':status,'at':time.time()};return None
    def apply(self,pool,data):
        mint=(pool.get('baseToken') or {}).get('address')
        if not data or data.get('address')!=mint:return 0
        now=time.time();observed=data.get('observed_at');updated=amount(data.get('updateUnixTime') or data.get('lastTradeUnixTime'))
        if not number(observed) or not 0<=now-observed<=120:return 0
        reference={k:data[k] for k in ('price','value','marketCap','mc','liquidity','v1hUSD','v24hUSD') if amount(data.get(k)) is not None}
        pool['_birdeye_evidence']={'mint':mint,'observed_at':observed,'updated_at':updated,'fields':reference,
                                   'scope':'token aggregate reference only; not pool liquidity/volume/transaction evidence'}
        self.stats['reference_fields']+=len(reference)
        # Circulating cap only, with independent supply consistency and pool price agreement.
        price=amount(data.get('price',data.get('value')));cap=amount(data.get('marketCap',data.get('mc')))
        supply=amount(data.get('circulatingSupply'));quote=amount(pool.get('priceUsd'))
        if data.get('isScaledUiToken') is True or updated is None or not 0<=now-updated<=120:return 0
        if any(v is None or v<=0 for v in (price,cap,supply,quote)):return 0
        if abs(cap-price*supply)/cap>.02 or abs(price-quote)/quote>.1:return 0
        current=amount(pool.get('marketCap'))
        proof={'provider':'birdeye_standard','mint':mint,'usd':cap,'price_usd':price,'circulating_supply':supply,'updated_at':updated,'observed_at':observed}
        if current is not None and current>0:
            if abs(current-cap)/cap>.2:pool['valuationConflict']=True
            return 0
        pool['marketCap']=cap;pool['marketCapEvidence']=proof;self.stats['recovered_cap_fields']+=1;return 1
    def enrich(self,pools):
        targets=[p for p in pools if amount(p.get('marketCap')) is None or amount(p.get('priceUsd')) is None]
        targets.sort(key=lambda p:-(amount((p.get('liquidity') or {}).get('usd')) or 0))
        seen=set()
        for p in targets:
            mint=(p.get('baseToken') or {}).get('address')
            if mint in seen or not address(mint):continue
            seen.add(mint)
            data=self.read(mint)
            if data is None:data=self.read(mint,'price')
            self.apply(p,data)
            if len(seen)>=2:break
        return self.report()
    def probe(self):
        if self.record.get('probe_completed'):return self.record['probe_completed']
        mint='So11111111111111111111111111111111111111112'
        price=self.read(mint,'price');overview=self.read(mint,'overview')
        result={'at':time.time(),'mint':mint,'price_success':bool(price),'overview_success':bool(overview),
                'price':price,'overview':overview,'scope':'live token aggregate probe, not a trading candidate'}
        if price or overview:self.record['probe_completed']=result
        return result
    def report(self):
        return {**copy.deepcopy(self.stats),'estimated_cu_31d':sum(self.record.get('cu_days',{}).values()),
                'limit_31d':LIMIT,'daily_limit':720,'hourly_limit':30,'rps':1,'endpoint_costs':COSTS,
                'endpoints':copy.deepcopy(self.record.get('endpoints',{})),
                'basis':'conservative CU reservations for this scanner since activation; includes failed attempts; not account billing'}
