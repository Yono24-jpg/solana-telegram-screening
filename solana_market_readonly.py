#!/usr/bin/env python3
"""Read-only real-market adapter for the EXISTING PaperBot; no trade endpoint.
Run: python3 solana_market_readonly.py --rounds 3 --interval 15 --output market_evidence.json
Discovery unions multiple public sources plus both Token Programs;
it is NOT an all-launch feed. SQLite preserves positions, dedup and scan cursors.
A finalized initializeMint instruction with exact mint and signature proves age.
Missing proof fails closed. Token-2022 requires a complete raw extension audit. DEX timestamps are receipt times, not a
guarantee of upstream tick freshness. Paper fills use marks, not swap quotes.
"""
import argparse
import datetime
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from collections import Counter
from pathlib import Path
from solana_sniper_paper import PaperBot, number
from sniper_runtime import PersistentPaperBot, RateLimiter
from sniper_token_extensions import audit_raw_mint, validate_quote
from sniper_discovery_policy import source_schedule, pool_priority, hint_from_pair, prioritized_watchlist

TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
PUBLIC_RPC='https://api.mainnet-beta.solana.com'
BACKUP_RPC='https://solana-rpc.publicnode.com'
READ_METHODS = frozenset(('getAccountInfo', 'getSignaturesForAddress', 'getTransaction','getBlockTime','getMultipleAccounts'))


class Reader:
    def __init__(self, store=None):
        self.rpc_url = os.getenv('SOLANA_READONLY_RPC', PUBLIC_RPC)
        self.active_rpc_url=self.rpc_url
        if urllib.parse.urlsplit(self.rpc_url).scheme != 'https':
            raise ValueError('RPC must use HTTPS')
        self.requests = []
        self.proofs = {}
        self.last_rpc = 0
        self.store = store
        self.limits = {'RPC_READ':RateLimiter(20,spacing=3.1),
                       'MARKET_GET':RateLimiter(30,spacing=2.1)}
        self.last_birth_scan = {}
        self.security_snapshots={}
        self.last_http_metadata={}

    def cache_get(self, kind, key):
        return self.store.cache_get(kind,key) if self.store else None

    def cache_put(self, kind, key, value):
        if self.store:
            self.store.cache_put(kind,key,value)

    def request(self, url, payload=None):
        kind = 'RPC_READ' if payload else 'MARKET_GET'
        if payload and payload.get('method') not in READ_METHODS:
            raise ValueError('RPC method not read-only allowlisted')
        for attempt in range(2):
            self.limits[kind].wait()
            start = time.time()
            audit = dict(kind=kind,method=payload['method'] if payload else 'GET',
                         path=None if payload else urllib.parse.urlsplit(url).path,
                         attempt=attempt+1,started_at=start)
            if payload:audit['provider']='Solana public' if url==PUBLIC_RPC else 'PublicNode' if url==BACKUP_RPC else 'configured RPC'
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                    headers={'Content-Type': 'application/json', 'User-Agent': 'SolanaReadOnlyPaper/1.0'})
                with urllib.request.urlopen(req, timeout=12) as response:
                    body = response.read()
                    age = response.headers.get('Age')
                    try:cache_age=float(age) if age is not None else None
                    except (TypeError,ValueError):cache_age=None
                    receipt=time.time();date=response.headers.get('Date');date_age=None
                    if date:
                        try:date_age=receipt-parsedate_to_datetime(date).timestamp()
                        except (ValueError,TypeError,AttributeError):pass
                    known=[v for v in (cache_age,date_age) if number(v) and v>=0]
                    self.last_http_metadata=dict(received_at=receipt,http_cache_age=max(known) if known else None,
                        age_header=age,response_date=date,upstream_metric_timestamp=None)
                    data = json.loads(body)
                audit.update(status='ok',http_metadata=dict(self.last_http_metadata),received_at=time.time(),sha256=hashlib.sha256(body).hexdigest(),
                             duration_seconds=round(time.time()-start,3))
                self.requests.append(audit)
                return data
            except urllib.error.HTTPError as error:
                audit.update(status=error.code,received_at=time.time())
                self.requests.append(audit)
                if error.code in (429, 500, 502, 503) and attempt == 0:
                    retry = error.headers.get('Retry-After') if error.headers else None
                    try:
                        delay = float(retry)
                    except (ValueError,TypeError):
                        try:
                            delay = parsedate_to_datetime(retry).timestamp()-time.time()
                        except (ValueError,TypeError,AttributeError):
                            delay = 10 if error.code == 429 else 2
                    self.limits[kind].cooldown(max(2,delay))
                    continue
                raise RuntimeError('HTTP_' + str(error.code)) from None
            except (urllib.error.URLError, TimeoutError):
                audit.update(status='network_error',received_at=time.time())
                self.requests.append(audit)
                self.limits[kind].cooldown(2)
                if attempt == 0:
                    continue
                raise RuntimeError('network_timeout_or_unavailable') from None

    def market(self, path):
        if not path.startswith(('/token-profiles/', '/token-boosts/', '/community-takeovers/',
                               '/latest/dex/search?', '/tokens/v1/solana/', '/latest/dex/pairs/solana/')):
            raise ValueError('Market endpoint not allowlisted')
        data=self.request('https://api.dexscreener.com' + path)
        metadata=dict(self.last_http_metadata)
        rows=data if isinstance(data,list) else data.get('pairs',[]) if isinstance(data,dict) else []
        for pair in rows:
            if isinstance(pair,dict) and pair.get('chainId')=='solana':pair['_market_observation']=metadata
        return data

    def recent_tokens(self):
        return self.request('https://api.jup.ag/tokens/v2/recent')

    def new_pools(self):
        # Address discovery only: reserveUsd/GT metrics never replace required
        # DEX Screener liquidity/m5 metrics or the finalized on-chain checks.
        return self.request('https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page=1')

    def rpc(self, method, params):
        if method not in READ_METHODS:
            raise ValueError('RPC method not read-only allowlisted')
        time.sleep(max(0, .4 - (time.monotonic()-self.last_rpc)))
        self.last_rpc = time.monotonic()
        payload=dict(jsonrpc='2.0', id=1, method=method, params=params)
        try:
            data=self.request(self.active_rpc_url,payload)
        except RuntimeError as error:
            # Do not bypass HTTP 429/cooldowns or override an explicitly configured RPC.
            if str(error)!='network_timeout_or_unavailable' or self.rpc_url!=PUBLIC_RPC or self.active_rpc_url!=PUBLIC_RPC:
                raise
            self.active_rpc_url=BACKUP_RPC
            data=self.request(self.active_rpc_url,payload)
        def record_rpc_result(response):
            if self.requests and self.requests[-1].get('kind')=='RPC_READ':
                error=(response.get('error') or {}) if isinstance(response,dict) else {}
                self.requests[-1]['rpc_success']=isinstance(response,dict) and 'error' not in response
                if error:self.requests[-1]['rpc_error_code']=error.get('code')
        record_rpc_result(data)
        # A finalized minContextSlot must never be lowered to work around lag.
        # Some public replicas lag the prior read: bounded retry of identical params.
        for _ in range(2):
            if not isinstance(data,dict) or (data.get('error') or {}).get('code')!=-32016:break
            self.limits['RPC_READ'].cooldown(3.1)
            data=self.request(self.active_rpc_url,payload)
            record_rpc_result(data)
        if 'error' in data:
            raise RuntimeError('RPC_error_' + str(data['error'].get('code', 'unknown')))
        self.last_rpc_provider='Solana public' if self.active_rpc_url==PUBLIC_RPC else 'PublicNode' if self.active_rpc_url==BACKUP_RPC else 'configured RPC'
        return data.get('result')

    def security(self, mint):
        result = self.rpc('getAccountInfo', [mint, {'encoding':'jsonParsed', 'commitment':'finalized'}])
        value = (result or {}).get('value')
        decoded = decode_security(value, (result or {}).get('context'))
        if (value or {}).get('owner') in (TOKEN_PROGRAM,TOKEN_2022):
            raw_result=self.rpc('getAccountInfo',[mint,{'encoding':'base64','commitment':'finalized',
                'minContextSlot':((result or {}).get('context') or {}).get('slot',0)}])
            raw_value=(raw_result or {}).get('value')
            audit=audit_raw_mint(raw_value)
            decoded.update(raw_account=raw_value,raw_context=(raw_result or {}).get('context'),extension_audit=audit)
            parsed_slot=((result or {}).get('context') or {}).get('slot',0)
            raw_slot=((raw_result or {}).get('context') or {}).get('slot',0)
            consistent=(type(parsed_slot) is int and type(raw_slot) is int and 0<parsed_slot<=raw_slot
                and (raw_value or {}).get('owner')==(value or {}).get('owner')) and all(
                decoded.get(k)==audit.get(k) for k in ('mint_revoked','freeze_revoked'))
            decoded['verified']=bool(decoded.get('authority_data_verified') and audit['verified'] and consistent)
            decoded['reason']=None if decoded['verified'] else 'raw_extensions_or_authorities_unverified'
        decoded['observed_at'] = time.time()
        self.security_snapshots[mint]=decoded
        return decoded

    def quote(self,source,target,amount,direct=False):
        params=urllib.parse.urlencode(dict(inputMint=source,outputMint=target,amount=amount,
            swapMode='ExactIn',slippageBps=50,instructionVersion='V2',
            restrictIntermediateTokens='true',onlyDirectRoutes='true' if direct else 'false'))
        return self.request('https://api.jup.ag/swap/v1/quote?'+params)

    def sell_route(self,mint):
        from sniper_route_audit import audit_route
        return audit_route(self,mint)

    def exit_route(self,mint,quantity):
        from sniper_route_audit import audit_route
        return audit_route(self,mint,position_quantity=quantity)

    def mint_birth(self, mint, program_id=TOKEN_PROGRAM):
        self.last_birth_scan=dict(mint=mint,status='started')
        if mint in self.proofs:
            self.last_birth_scan = dict(mint=mint,cached=True)
            if self.proofs[mint].get('program_id')!=program_id:
                raise RuntimeError('invalid_cached_birth_program')
            return self.proofs[mint]
        cached = self.cache_get('birth',mint)
        if cached:
            if not transaction_proof(cached.get('transaction'),mint,cached.get('signature'),program_id):
                raise RuntimeError('invalid_cached_birth_proof')
            self.proofs[mint] = cached
            self.last_birth_scan = dict(mint=mint,cached=True)
            return cached
        scan = self.cache_get('birth_scan',mint) or dict(before=None,pages=0,oldest=[],checked=[],complete=False)
        # v1 lost all but 40 signatures. Re-enumerate that incomplete index;
        # keep the old cursor as evidence, and retain already validated init proofs.
        if scan.get('schema')!=2:
            if scan.get('pages'):self.cache_put('birth_scan_legacy',mint,scan)
            scan=dict(schema=2,before=None,pages=0,oldest=[],checked=[],complete=False,cursors=[])
        # No lifetime page/transaction cap: resume until the provider's tail or exact init.
        # Only two pages and two transaction reads are allowed per visit.
        for _ in range(2):
            if scan['complete']:
                break
            options = {'limit':1000, 'commitment':'finalized'}
            if scan['before']:
                options['before'] = scan['before']
            signatures = self.rpc('getSignaturesForAddress', [mint, options])
            if not isinstance(signatures,list):raise RuntimeError('history_response_unavailable')
            if any(not isinstance(v,dict) or not isinstance(v.get('signature'),str) or not v['signature']
                or not number(v.get('slot')) or v['slot']<=0 or 'err' not in v
                or v.get('confirmationStatus') not in (None,'finalized') for v in signatures):
                raise RuntimeError('history_response_invalid')
            if len({v['signature'] for v in signatures})!=len(signatures):raise RuntimeError('history_duplicate_signatures')
            if signatures and (signatures[-1]['signature'] == scan['before'] or signatures[-1]['signature'] in scan.get('cursors',[])):

                raise RuntimeError('history_cursor_did_not_advance')
            successful = [s for s in signatures if 'err' in s and s['err'] is None]
            unique = {s['signature']:s for s in scan['oldest']+successful}
            scan['oldest'] = sorted(unique.values(),key=lambda s:s.get('slot',0))
            scan['pages'] += 1
            scan['complete'] = len(signatures) < 1000
            if signatures:
                scan['before'] = signatures[-1]['signature']
                scan.setdefault('cursors',[]).append(scan['before'])
            self.cache_put('birth_scan',mint,scan)
        self.last_birth_scan = dict(mint=mint,pages=scan['pages'],history_complete=scan['complete'],
                                    successful_candidates=len(scan['oldest']),checked=len(scan['checked']),
                                    history_scope='provider_tail_not_independent_archive_completeness',lifetime_page_cap=None)
        pending = [s for s in scan['oldest'] if s['signature'] not in scan['checked']]
        scan.setdefault('unavailable',{})
        scan.setdefault('transaction_attempts',{})
        pending=[s for s in pending if scan['unavailable'].get(s['signature'],0)<=time.time()]
        pending.sort(key=lambda s:(scan['transaction_attempts'].get(s['signature'],0),s.get('slot',0)))
        for item in pending[:2]:
            tx = self.rpc('getTransaction', [item['signature'],
                {'encoding':'jsonParsed', 'commitment':'finalized', 'maxSupportedTransactionVersion':1}])
            scan['transaction_attempts'][item['signature']]=scan['transaction_attempts'].get(item['signature'],0)+1
            proof = transaction_proof(tx,mint,item['signature'],program_id)
            if tx is None:
                # Null is unavailable at this commitment, not proof of no init.
                # Do not permanently mark the signature as inspected.
                scan['unavailable'][item['signature']]=time.time()+60
                self.cache_put('birth_scan',mint,scan)
                self.last_birth_scan['transaction_unavailable']=True
                continue
            scan['checked'].append(item['signature'])
            self.last_birth_scan['checked']=len(scan['checked'])
            self.cache_put('birth_scan',mint,scan)
            if proof and (proof['slot']!=item['slot'] or (number(item.get('blockTime')) and item['blockTime']!=proof['block_time'])):
                raise RuntimeError('history_initialization_proof_mismatch')
            if proof:
                proof['rpc_provider']=getattr(self,'last_rpc_provider','unknown')
                self.proofs[mint] = proof
                self.cache_put('birth',mint,proof)
                return proof
        return None

    def discover(self, round_id, max_tokens=120, onchain_transactions=2):
        sources = source_schedule(round_id)
        audit, candidates = [], {}
        def add(mint, source, seed=None):
            if not isinstance(mint,str) or not 32 <= len(mint) <= 44:
                return
            old = candidates.setdefault(mint,dict(last_seen=time.time(),sources=[]))
            if source not in old['sources']:
                old['sources'].append(source)
            if seed:
                # A second discovery source with absent/zero BUY counts must not
                # overwrite a positive activity hint found in this same round.
                buys=max(old.get('seed_buys',0),seed.get('seed_buys',0))
                old.update(seed);old['seed_buys']=buys
        try:
            fresh=self.new_pools();seeds=[]
            for pool in fresh.get('data') or []:
                identifier=pool.get('relationships',{}).get('base_token',{}).get('data',{}).get('id','')
                if not identifier.startswith('solana_'):continue
                mint=identifier[len('solana_'):]
                attrs=pool.get('attributes') or {};buys=((attrs.get('transactions') or {}).get('m5') or {}).get('buys')
                seed_buys=buys if number(buys) and buys>=0 and int(buys)==buys else 0
                add(mint,'geckoterminal_new_pools',dict(seed_buys=seed_buys,seed_observed_at=time.time(),
                    source_pool_created_at=attrs.get('pool_created_at')))
                seeds.append(mint)
            audit.append(dict(source='geckoterminal_new_pools',records=len(fresh.get('data') or []),
                              solana_mints=list(dict.fromkeys(seeds)),raw_seed_pools=fresh.get('data') or []))
        except Exception as error:
            audit.append(dict(source='geckoterminal_new_pools',error=safe_error(error)))
        try:
            recent=self.recent_tokens()
            if not isinstance(recent,list):raise ValueError('recent_tokens_not_list')
            seeds=[]
            for token in recent:
                mint=token.get('id');stats=token.get('stats5m') or {}
                buys=stats.get('numBuys')
                seed=buys if number(buys) and buys>=0 and int(buys)==buys else 0
                add(mint,'jupiter_recent',dict(seed_buys=seed,seed_observed_at=time.time()))
                seeds.append(mint)
            audit.append(dict(source='jupiter_recent',records=len(recent),solana_mints=seeds,raw_tokens=recent))
        except Exception as error:
            audit.append(dict(source='jupiter_recent',error=safe_error(error)))
        for source in sources:
            source_mints=[]
            try:
                data = self.market(source)
                if isinstance(data,dict):
                    records=data.get('pairs') or []
                    for p in records:
                        if p.get('chainId') == 'solana':
                            add(p.get('baseToken',{}).get('address'),source)
                            source_mints.append(p.get('baseToken',{}).get('address'))
                else:
                    records=data
                    for p in records:
                        if p.get('chainId') == 'solana':
                            add(p.get('tokenAddress'),source)
                            source_mints.append(p.get('tokenAddress'))
                audit.append(dict(source=source,records=len(records),solana_mints=list(dict.fromkeys(source_mints))))
            except Exception as error:
                audit.append(dict(source=source,error=safe_error(error)))
        # Additional independent on-chain sample: alternate both Token Programs.
        # Not all transactions are launches. Only exact initializeMint is used.
        if onchain_transactions and round_id%3==0:
            program=TOKEN_PROGRAM if (round_id//3)%2==0 else TOKEN_2022
            try:
                signatures = self.rpc('getSignaturesForAddress',[program,{'limit':30,'commitment':'finalized'}]) or []
                pending=[s for s in signatures if s.get('err') is None
                         and not self.cache_get('discovery_tx',s['signature'])][:onchain_transactions]
                for s in pending:
                    tx=self.rpc('getTransaction',[s['signature'],{'encoding':'jsonParsed','commitment':'finalized',
                                                               'maxSupportedTransactionVersion':1}])
                    for mint in initialized_mints(tx,program):
                        proof=transaction_proof(tx,mint,s['signature'],program)
                        if proof:
                            self.proofs[mint]=proof
                            self.cache_put('birth',mint,proof)
                            add(mint,'onchain_initializeMint_'+program)
                    self.cache_put('discovery_tx',s['signature'],dict(checked_at=time.time()))
                audit.append(dict(source='onchain_token_program',program=program,signatures=len(signatures),transactions_checked=len(pending)))
            except Exception as error:
                audit.append(dict(source='onchain_token_program',error=safe_error(error)))
        new_discovered=[]
        for mint,value in candidates.items():
            old=self.cache_get('watch',mint)
            if old:
                value['sources']=sorted(set(old['sources']+value['sources']))
                for field in ('seed_buys','seed_observed_at','source_pool_created_at'):
                    if field not in value and field in old:value[field]=old[field]
            else:new_discovered.append(mint)
            value['first_seen']=old.get('first_seen',old['last_seen']) if old else value['last_seen']
            self.cache_put('watch',mint,value)
        registry=dict(self.store.cache_items('watch')) if self.store else candidates
        hints=dict(self.store.cache_items('market_hint')) if self.store else {}
        for mint,hint in hints.items():hint['verification_attempt']=self.cache_get('verification_attempt',mint) or 0
        ordered,skipped=prioritized_watchlist(registry,hints,round_id,max_tokens,time.time())
        pairs=[]
        for start in range(0,len(ordered),30):
            try:
                pairs.extend(self.market('/tokens/v1/solana/'+','.join(ordered[start:start+30])))
            except Exception as error:
                audit.append(dict(source='token_batch',offset=start,error=safe_error(error)))
        selected={}
        now=time.time()
        for pair in pairs:
            mint=pair.get('baseToken',{}).get('address')
            if pair.get('chainId')=='solana' and mint in ordered and (
                mint not in selected or pool_priority(pair,now)<pool_priority(selected[mint],now)):
                selected[mint]=pair
        for mint,pair in selected.items():self.cache_put('market_hint',mint,hint_from_pair(pair,now,hints.get(mint)))
        for source in audit:
            source['cached_old_mints']=sum(m in hints and pool_priority(hints[m],now)[0]==6 for m in source.get('solana_mints',[]))
            members=[selected[m] for m in source.get('solana_mints',[]) if m in selected]
            source['matched_mints_this_round']=len(members)
            source['old_pools_this_round']=sum(pool_priority(p,now)[0]==6 for p in members)
            source['young_pools_this_round']=sum(number(p.get('pairCreatedAt')) and 0<=now-p['pairCreatedAt']/1000<=3600 for p in members)
            source['inactive_this_round']=sum((p.get('volume') or {}).get('m5')==0 or ((p.get('txns') or {}).get('m5') or {}).get('buys')==0 for p in members)
        return ordered,pairs,dict(sources=audit,discovered_this_round=len(candidates),
            watchlist_eligible=sum(now-v['last_seen']<5400 for v in registry.values()),requested_mints=len(ordered),
            new_unique_addresses=len(new_discovered),new_addresses=new_discovered,
            deferred_cached_mints=skipped,selection_policy='young_active_first_with_unseen_reserve')


def safe_error(error):
    # Never include RPC URLs or environment credentials in evidence.
    if isinstance(error,RuntimeError) and str(error).startswith(('HTTP_','RPC_error_',
        'rate_limit_','history_cursor_','invalid_cached_','network_','history_')):
        return str(error)
    return type(error).__name__


def initialized_mints(tx,program_id=TOKEN_PROGRAM):
    if not tx or not tx.get('meta') or 'err' not in tx['meta'] or tx['meta']['err'] is not None:
        return []
    instructions=list(tx.get('transaction',{}).get('message',{}).get('instructions',[]))
    for group in tx['meta'].get('innerInstructions') or []:
        instructions.extend(group.get('instructions',[]))
    return list(dict.fromkeys(i['parsed']['info']['mint'] for i in instructions
        if i.get('programId') == program_id and i.get('parsed',{}).get('type') in ('initializeMint','initializeMint2')
        and isinstance(i.get('parsed',{}).get('info',{}).get('mint'),str)))


def transaction_proof(tx,mint,signature,program_id=TOKEN_PROGRAM):
    if (program_id not in (TOKEN_PROGRAM,TOKEN_2022) or not tx or mint not in initialized_mints(tx,program_id) or not number(tx.get('slot')) or tx['slot'] <= 0
        or not number(tx.get('blockTime')) or tx['blockTime'] <= 0
        or not signature or signature not in tx.get('transaction',{}).get('signatures',[])):
        return None
    return dict(block_time=tx['blockTime'],signature=signature,slot=tx['slot'],
                program_id=program_id,commitment='finalized',
                instruction='initializeMint/initializeMint2',transaction=tx)


def decode_security(value, context=None):
    if not value or value.get('owner') not in (TOKEN_PROGRAM,TOKEN_2022):
        return dict(verified=False, reason='missing_mint_or_unsupported_token_program', raw=value, context=context)
    parsed = value.get('data', {}).get('parsed', {})
    info = parsed.get('info', {})
    valid = (parsed.get('type') == 'mint' and info.get('isInitialized') is True
             and all(key in info for key in ('mintAuthority', 'freezeAuthority')))
    return dict(verified=valid and value['owner'] == TOKEN_PROGRAM,
                authority_data_verified=valid,
                reason='raw_extensions_not_checked' if value['owner'] == TOKEN_2022 else None,
                mint_revoked=valid and info['mintAuthority'] is None,
                freeze_revoked=valid and info['freezeAuthority'] is None, raw=value, context=context)


def decode_birth(tx, mint):
    if not tx or not tx.get('meta') or tx['meta'].get('err') is not None:
        return None
    instructions = list(tx.get('transaction', {}).get('message', {}).get('instructions', []))
    for inner in tx['meta'].get('innerInstructions') or []:
        instructions.extend(inner.get('instructions', []))
    for instruction in instructions:
        parsed = instruction.get('parsed', {})
        if (instruction.get('programId') in (TOKEN_PROGRAM,TOKEN_2022)
            and parsed.get('type') in ('initializeMint', 'initializeMint2')
            and parsed.get('info', {}).get('mint') == mint
            and number(tx.get('blockTime'))):
            return tx['blockTime']
    return None


def market_data_age(pair,now):
    meta=pair.get('_market_observation') or {}
    received=meta.get('received_at',now);cache=meta.get('http_cache_age')
    if not number(received) or received>now:return None
    if cache is not None and (not number(cache) or cache<0):return None
    return now-received+(cache or 0)


def metrics(pair, now):
    txns = pair.get('txns', {}).get('m5', {})
    try:
        price = float(pair.get('priceUsd'))
    except (ValueError, TypeError):
        price = None
    birth = pair.get('pairCreatedAt')
    return dict(type='candidate', mint=pair.get('baseToken', {}).get('address'),
        chain=pair.get('chainId'), price=price, now=now,
        observed_at=(pair.get('_market_observation') or {}).get('received_at',now),
        data_age_seconds=market_data_age(pair,now),
        market_provenance=pair.get('_market_observation',dict(scope='fixture_or_legacy_receipt_only')),
        age_minutes=None, age_source='unverified', mint_revoked=None, freeze_revoked=None,
        liquidity_usd=(pair.get('liquidity') or {}).get('usd'),
        volume_5m_usd=(pair.get('volume') or {}).get('m5'),
        buys_5m=txns.get('buys'), sells_5m=txns.get('sells'),
        pool_age_minutes=(now-birth/1000)/60 if number(birth) else None)


def market_assessment(event):
    """Separate actual threshold violations from unavailable data. Fail closed."""
    checks, reasons = {}, []
    for key, limit in [('liquidity_usd',10000),('volume_5m_usd',1500),('buys_5m',12)]:
        value=event.get(key)
        valid=number(value) and value>=0 and (key!='buys_5m' or int(value)==value)
        age=event.get('data_age_seconds',0)
        stale=number(age) and age>30
        status='unavailable' if not valid or not number(age) or age<0 else 'stale' if stale else 'fail' if value<limit else 'pass'
        checks[key]=dict(status=status,value=value,minimum=limit,data_age_seconds=age,
            data_state='missing_or_invalid_value' if not valid else 'unknown_freshness' if not number(age) or age<0
            else 'stale' if stale else 'below_threshold' if value<limit else 'fresh_response_above_threshold',
            upstream_metric_timestamp_verified=False)
        if status!='pass':reasons.append(key+'_'+status if status in ('unavailable','stale') else key)
    buys,sells=event.get('buys_5m'),event.get('sells_5m')
    valid=all(number(v) and v>=0 and int(v)==v for v in (buys,sells))
    if not valid or (buys==0 and sells==0):
        ratio=None;status='unavailable'
    elif sells==0:
        ratio=None;status='pass_no_sells' # Positive BUY and zero SELL; never serialize infinity.
    else:
        ratio=buys/sells;status='fail' if ratio<1.5 else 'pass'
    checks['buy_sell_ratio']=dict(status=status,value=ratio,buys=buys,sells=sells,minimum=1.5)
    if status in ('unavailable','fail'):
        reasons.append('buy_sell_ratio_unavailable' if status=='unavailable' else 'buy_sell_ratio')
    age=event.get('pool_age_minutes')
    status='unavailable' if not number(age) or age<0 else 'fail' if age>60 else 'pass_lower_bound_only'
    checks['pool_age']=dict(status=status,value=age)
    if status=='fail':reasons.append('pool_already_older_than_60m')
    # Pool age is an optional lower bound. Its absence never substitutes for mint proof.
    checks.update(mint_age=dict(status='not_checked'),mint_authority=dict(status='not_checked'),
                  freeze_authority=dict(status='not_checked'),token_program=dict(status='not_checked'))
    return checks,reasons


def record_security_checks(checks, security):
    if security.get('authority_data_verified'):
        for name,key in [('mint_authority','mint_revoked'),('freeze_authority','freeze_revoked')]:
            checks[name]=dict(status='pass' if security.get(key) is True else 'fail')
    else:
        checks['mint_authority']=dict(status='unavailable')
        checks['freeze_authority']=dict(status='unavailable')
    owner=(security.get('raw') or {}).get('owner')
    checks['token_program']=dict(status='pass' if owner in (TOKEN_PROGRAM,TOKEN_2022) else 'unavailable',owner=owner)
    audit=security.get('extension_audit') or {}
    checks['extensions']=dict(status='pass' if security.get('verified') and audit.get('verified') else 'unavailable',
        attempted=True,details=audit)



def verify_stages(reader,mint,checks):
    """Audit both token programs, fail closed on extensions and finalized age."""
    errors=[];security={};birth=None
    try:
        security=reader.security(mint)
    except Exception as error:
        errors.append(dict(stage='account_state',error=safe_error(error)))
    record_security_checks(checks,security)
    for key in ('mint_authority','freeze_authority','token_program'):
        checks[key]['attempted']=True
    program=(security.get('raw') or {}).get('owner') or TOKEN_PROGRAM
    checks['mint_age']=dict(status='unavailable',attempted=True,commitment='finalized')
    try:
        if program in (TOKEN_PROGRAM,TOKEN_2022):
            birth=reader.mint_birth(mint) if program==TOKEN_PROGRAM else reader.mint_birth(mint,program_id=program)
        if birth:
            age=(time.time()-birth['block_time'])/60
            checks['mint_age'].update(status='pass' if 1<=age<=60 else 'fail',
                                      value=age,proof_signature=birth.get('signature'))
    except Exception as error:
        errors.append(dict(stage='mint_initialization',error=safe_error(error)))
    reasons=[]
    for key,failed,unknown in [('mint_authority','mint_revoked','mint_authority_unverified'),
                              ('freeze_authority','freeze_revoked','freeze_authority_unverified'),
                              ('token_program','unsupported_token_program','token_program_unverified'),
                              ('extensions','unsafe_extensions','extensions_unverified'),
                              ('mint_age','age_minutes','mint_age_unverified')]:
        status=checks[key]['status']
        if status!='pass':reasons.append(failed if status=='fail' else unknown)
    return security,birth,reasons,errors


def run(args,reader_factory=None):
    bot = PersistentPaperBot(args.state_db,fee=.013,fixed=.05,slippage_bps=50)
    reader = (reader_factory or Reader)(bot)
    evidence = dict(mode='PAPER_READ_ONLY', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        core_sha256=hashlib.sha256(Path(__file__).with_name('solana_sniper_paper.py').read_bytes()).hexdigest(),
        code_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
            ('solana_market_readonly.py','sniper_token_extensions.py','sniper_discovery_policy.py','sniper_runtime.py','sniper_route_audit.py')},
        strategy=dict(age_minutes=[1,60], liquidity_usd=10000, volume_5m_usd=1500,
            buys_5m=12, buy_sell_ratio=1.5, buy_usd=5, tp=.20, sl=-.10, max_positions=2),
        cost_assumptions=dict(platform_fee=.01, dex_fee=.003, fixed_usd_per_side=.05,
            adverse_slippage_bps_per_side=50, measured=False,
            exclusions=['token_account_rent','failed_transactions','market_depth_and_price_impact']),
        real_trading=False,recovered_state=bot.snapshot(),
        limits=dict(market_per_minute=30,rpc_per_minute=20,token_batch_size=30,
                    max_tokens_per_round=args.max_tokens),
        limitations=['multi-source discovery and on-chain sampling are not all new launches',
            'receipt timestamp does not prove upstream tick freshness',
            'paper fills are marks, not executable swap quotes',
            'mint/freeze checks alone do not prove a token safe'], rounds=[], errors=[])
    run_checked=set()
    for round_id in range(args.rounds):
        if round_id:
            time.sleep(args.interval)
        row = dict(round=round_id+1, raw_pairs=[], candidates=[], marks=[])
        try:
            bot.refresh()
            pins = bot.pins
            # Monitor existing positions before considering new entries.
            for mint in list(bot.positions):
                data = reader.market('/latest/dex/pairs/solana/' + pins[mint])
                matches = [p for p in data.get('pairs') or [] if p.get('pairAddress') == pins[mint]
                           and p.get('baseToken', {}).get('address') == mint]
                if not matches:
                    row['marks'].append(dict(mint=mint, action='UNPRICED_OPEN_POSITION'))
                    continue
                pair = matches[0]
                row['raw_pairs'].append(pair)
                event = metrics(pair, time.time())
                event['type'] = 'price'
                exit_audit=None
                if not number(event.get('data_age_seconds')) or not 0<=event['data_age_seconds']<=30:
                    outcome=dict(action='UNPRICED_STALE_OPEN_POSITION')
                elif number(event.get('price')) and event['price']>0 and (
                    event['price']/bot.positions[mint]['entry']>=1.20-1e-12 or
                    event['price']/bot.positions[mint]['entry']<=.90+1e-12):
                    exit_audit=reader.exit_route(mint,bot.positions[mint]['quantity'])
                    if not exit_audit.get('verified'):
                        outcome=dict(action='PAPER_EXIT_BLOCKED_ROUTE',reasons=exit_audit.get('reasons',[]))
                    else:
                        # Do not execute a simulated exit using the mark from before
                        # the RPC route audit; re-read the persisted pool pin.
                        response=reader.market('/latest/dex/pairs/solana/'+pins[mint])
                        fresh=next((p for p in response.get('pairs') or [] if p.get('chainId')=='solana'
                            and p.get('pairAddress')==pins[mint] and p.get('baseToken',{}).get('address')==mint),None)
                        if fresh is None:
                            outcome=dict(action='UNPRICED_OPEN_POSITION')
                        else:
                            row['raw_pairs'].append(fresh);event=metrics(fresh,time.time());event['type']='price'
                            outcome=(bot.process(event) if number(event.get('data_age_seconds')) and 0<=event['data_age_seconds']<=30
                                and 0<=time.time()-exit_audit['observed_at']<=30 else dict(action='UNPRICED_STALE_OPEN_POSITION'))
                else:
                    outcome=bot.process(event)
                row['marks'].append(dict(event=event, outcome=outcome,exit_route_audit=exit_audit))
            cursor=bot.cache_get('discovery','round') or 0
            mints,pairs,row['discovery']=reader.discover(cursor,args.max_tokens,args.onchain_transactions)
            bot.cache_put('discovery','round',cursor+1)
            selected={}
            ranking_time=time.time()
            for pair in pairs:
                mint=pair.get('baseToken',{}).get('address')
                lp=(pair.get('liquidity') or {}).get('usd') or 0
                if pair.get('chainId') == 'solana' and mint in mints and (mint not in selected
                    or pool_priority(pair,ranking_time)<pool_priority(selected[mint][0],ranking_time)):
                    selected[mint]=(pair,lp)
            security_count = 0
            data_refresh_count = 0
            ordered_candidates=sorted(selected.items(),key=lambda item:(pool_priority(item[1][0],ranking_time)[0],
                bot.cache_get('verification_attempt',item[0]) or 0,pool_priority(item[1][0],ranking_time)[1:]))
            for mint, (pair, _) in ordered_candidates:
                if mint in bot.seen:
                    continue
                row['raw_pairs'].append(pair)
                event = metrics(pair, time.time())
                entry = dict(symbol=pair.get('baseToken', {}).get('symbol'), pair=pair.get('pairAddress'))
                # Screen market thresholds before expensive RPC. Pool age over
                # 60m proves the mint cannot be younger than its existing pool.
                checks,pre=market_assessment(event)
                # Proven data gap: missing LP was mislabeled as insufficient LP.
                # Re-read the SAME pair only when data absence is the sole blocker.
                # No inferred liquidity, alternative pool or relaxed threshold is used.
                if pre and all(reason.endswith(('_unavailable','_stale')) for reason in pre) and data_refresh_count<3:
                    data_refresh_count+=1
                    entry['initial_market_event']=event.copy()
                    try:
                        response=reader.market('/latest/dex/pairs/solana/'+pair['pairAddress'])
                        fresh=next((p for p in response.get('pairs') or [] if p.get('chainId')=='solana'
                            and p.get('pairAddress')==pair['pairAddress']
                            and p.get('baseToken',{}).get('address')==mint),None)
                        if fresh is None:raise RuntimeError('pair_missing_at_recheck')
                        row['raw_pairs'].append(fresh)
                        pair=fresh;event=metrics(pair,time.time());checks,pre=market_assessment(event)
                        entry['data_refresh']=dict(status='read_ok',still_unavailable=any(r.endswith('_unavailable') for r in pre))
                    except Exception as error:
                        entry['data_refresh']=dict(status='failed',error=safe_error(error))
                entry['checks']=checks
                entry['market_thresholds_passed']=not pre
                if pre:
                    entry.update(event=event, outcome=dict(action='REJECT', reasons=pre))
                elif security_count >= args.max_security:
                    entry.update(event=event, outcome=dict(action='DEFER', reasons=['verification_budget_pending']))
                else:
                    security_count += 1
                    try:
                        security,birth,blocked,stage_errors=verify_stages(reader,mint,checks)
                        bot.cache_put('verification_attempt',mint,time.time())
                        entry['security'] = security
                        entry['mint_creation_proof']=birth
                        entry['mint_history_scan']=reader.last_birth_scan
                        entry['verification_errors']=stage_errors
                        if security.get('authority_data_verified'):
                            event.update(mint_revoked=security['mint_revoked'],freeze_revoked=security['freeze_revoked'])
                        if birth:
                            event.update(age_source='mint_creation',age_minutes=(time.time()-birth['block_time'])/60)
                        route=dict(verified=False,reason='mint_controls_not_verified')
                        if (security.get('verified') and security.get('mint_revoked') is True
                            and security.get('freeze_revoked') is True):
                            try:
                                route=reader.sell_route(mint)
                            except Exception as error:
                                route=dict(verified=False,error=safe_error(error))
                            checks['sell_route']=dict(status='pass' if route.get('verified') else 'unavailable',attempted=True)
                        else:
                            checks['sell_route']=dict(status='not_checked',attempted=False)
                        entry['sell_route']=route
                        if not route.get('verified'):blocked.append('sell_route_unverified')
                        if blocked:
                            entry.update(event=event,outcome=dict(action='REJECT',reasons=blocked))
                            row['candidates'].append(entry)
                            continue
                        # RPC may take time: refresh security and market before a BUY.
                        if time.time()-security['observed_at'] > 30:
                            security = reader.security(mint)
                            entry['security'] = security
                            record_security_checks(checks,security)
                            event.update(mint_revoked=security.get('mint_revoked') if security.get('authority_data_verified') else None,
                                         freeze_revoked=security.get('freeze_revoked') if security.get('authority_data_verified') else None)
                        refresh = reader.market('/latest/dex/pairs/solana/' + pair['pairAddress'])
                        match = next((p for p in refresh.get('pairs') or [] if p.get('pairAddress') == pair['pairAddress']
                                      and p.get('baseToken', {}).get('address') == mint), None)
                        if match is None:
                            raise RuntimeError('pair_missing_at_recheck')
                        row['raw_pairs'].append(match)
                        newer = metrics(match, time.time())
                        entry['liquidity_revalidation']=dict(previous=event.get('liquidity_usd'),
                            current=newer.get('liquidity_usd'),same_pair=pair['pairAddress'],
                            upstream_metric_timestamp=(match.get('_market_observation') or {}).get('upstream_metric_timestamp'))
                        for key in ('age_source','mint_revoked','freeze_revoked'):
                            newer[key] = event[key]
                        proof = entry.get('mint_creation_proof')
                        newer['age_minutes'] = (newer['now']-proof['block_time'])/60 if proof else None
                        event = newer
                        refreshed_checks,refreshed_reasons=market_assessment(event)
                        for key in ('liquidity_usd','volume_5m_usd','buys_5m','buy_sell_ratio','pool_age'):
                            checks[key]=refreshed_checks[key]
                        if proof:
                            checks['mint_age']['status']='pass' if 1<=newer['age_minutes']<=60 else 'fail'
                        event['pair_address']=pair['pairAddress']
                        if (not refreshed_reasons and security.get('verified') and 0 <= time.time()-security['observed_at'] <= 30
                            and 0 <= time.time()-route['observed_at'] <= 30):
                            outcome = bot.process(event)
                        else:
                            reasons = refreshed_reasons or [security.get('reason') or 'security_or_route_stale_or_unverified']
                            if newer['age_minutes'] is None:
                                reasons.append('mint_age_unverified')
                            elif not 1 <= newer['age_minutes'] <= 60:
                                reasons.append('age_minutes')
                            outcome = dict(action='REJECT', reasons=reasons)
                        entry.update(event=event, outcome=outcome)
                    except Exception as error:
                        entry.update(event=event, outcome=dict(action='REJECT', reasons=['verification_unavailable'], error=safe_error(error)))
                row['candidates'].append(entry)
        except Exception as error:
            evidence['errors'].append(dict(round=round_id+1, error=safe_error(error)))
        round_mints={c['event']['mint'] for c in row['candidates']}
        row['new_mints_in_this_run']=sorted(round_mints-run_checked)
        row['repeated_discovery_checks']=len(row['candidates'])-len(row['new_mints_in_this_run'])
        row['globally_first_market_mints']=[]
        for candidate in row['candidates']:
            mint=candidate['event']['mint'];previous=bot.cache_get('checked_mint',mint)
            candidate['first_recorded_market_check']=previous is None
            if previous is None:row['globally_first_market_mints'].append(mint)
            bot.cache_put('checked_mint',mint,dict(first_checked_at=previous['first_checked_at'] if previous else candidate['event']['now'],
                last_checked_at=candidate['event']['now'],checks=(previous.get('checks',0) if previous else 0)+1))
        run_checked.update(round_mints)
        evidence['rounds'].append(row)
        evidence['requests'] = reader.requests
        all_candidates=[c for r in evidence['rounds'] for c in r['candidates']]
        unique={c['event']['mint'] for c in all_candidates}
        stage_counts={}
        stage_unique={};reason_unique={}
        for candidate in all_candidates:
            for stage,check in candidate.get('checks',{}).items():
                statuses=stage_counts.setdefault(stage,Counter());statuses[check['status']]+=1
                stage_unique.setdefault(stage,{}).setdefault(check['status'],set()).add(candidate['event']['mint'])
            if candidate['outcome']['action']=='REJECT':
                for reason in candidate['outcome']['reasons']:
                    reason_unique.setdefault(reason,set()).add(candidate['event']['mint'])
        evidence['summary'] = dict(candidate_checks=sum(len(r['candidates']) for r in evidence['rounds']),
            actions=dict(Counter(c['outcome']['action'] for r in evidence['rounds'] for c in r['candidates'])),
            realized_net_pnl_usd=round(bot.pnl,6), open_positions=bot.positions,
            max_positions_observed=max([0]+[c['outcome'].get('positions',0) for r in evidence['rounds'] for c in r['candidates']]),
            blockchain_transactions_sent=0,unique_mints_checked=len(unique),
            security_pass_unique_by_program={program:len({c['event']['mint'] for c in all_candidates
                if c.get('checks',{}).get('token_program',{}).get('owner')==program and all(
                    c.get('checks',{}).get(stage,{}).get('status')=='pass' for stage in
                    ('mint_age','mint_authority','freeze_authority','token_program','extensions','sell_route'))})
                    for program in (TOKEN_PROGRAM,TOKEN_2022)},
            repeated_checks=len(all_candidates)-len(unique),stage_counts={k:dict(v) for k,v in stage_counts.items()},
            market_pass_checks=sum(c.get('market_thresholds_passed',False) for c in all_candidates),
            market_pass_unique_mints=len({c['event']['mint'] for c in all_candidates if c.get('market_thresholds_passed')}),
            rejection_reason_counts=dict(Counter(reason for c in all_candidates if c['outcome']['action']=='REJECT' for reason in c['outcome']['reasons'])),
            rejection_reason_unique_mints={k:len(v) for k,v in reason_unique.items()},
            stage_unique_mints={k:{s:len(v) for s,v in statuses.items()} for k,statuses in stage_unique.items()},
            verification_deferred_checks=sum(c['outcome']['action']=='DEFER' for c in all_candidates),
            newly_discovered_addresses_per_round=[r.get('discovery',{}).get('new_unique_addresses',0) for r in evidence['rounds']],
            new_mints_in_run_per_round=[len(r['new_mints_in_this_run']) for r in evidence['rounds']],
            globally_first_market_checks=sum(len(r['globally_first_market_mints']) for r in evidence['rounds']),
            globally_first_market_mints_per_round=[len(r['globally_first_market_mints']) for r in evidence['rounds']],
            position_price_checks=sum(len(r['marks']) for r in evidence['rounds']),
            complete_verification_attempts=sum(all(c.get('checks',{}).get(k,{}).get('attempted') for k in
                ('mint_age','mint_authority','freeze_authority','token_program')) for c in all_candidates))
        evidence['durable_state']=bot.snapshot()
        temporary=Path(args.output+'.tmp')
        temporary.write_text(json.dumps(evidence, indent=2, allow_nan=False))
        temporary.replace(args.output)
        print(json.dumps(dict(round=round_id+1, **evidence['summary'])), flush=True)
    bot.close()
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--interval', type=float, default=15)
    parser.add_argument('--max-security', type=int, default=3)
    parser.add_argument('--output', default='market_evidence.json')
    parser.add_argument('--state-db',default='sniper_paper.sqlite3')
    parser.add_argument('--max-tokens',type=int,default=120)
    parser.add_argument('--onchain-transactions',type=int,default=2)
    args = parser.parse_args()
    if (not 1 <= args.rounds <= 10000 or not 5 <= args.interval <= 60 or not 0 <= args.max_security <= 10
        or not 30 <= args.max_tokens <= 300 or not 0 <= args.onchain_transactions <= 8):
        parser.error('Bounded PAPER observation: rounds 1..10000, interval 5..60, security 0..10, tokens 30..300, chain tx 0..8')
    run(args)
