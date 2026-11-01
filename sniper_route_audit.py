"""Read-only audit of all quote mints and observed finalized SELL flows.
No transactions are built, signed, simulated on RPC, or submitted.
Quotes and past successful flows cannot guarantee future execution.
"""
import time
import re
from decimal import Decimal,ROUND_DOWN
from solana_sniper_paper import number
from sniper_token_extensions import validate_quote,uint64,TOKEN_PROGRAM,TOKEN_2022,audit_raw_token_account

WSOL='So11111111111111111111111111111111111111112'
USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'


def route_mints(quote):
    if not isinstance(quote,dict) or not isinstance(quote.get('routePlan'),list):raise ValueError('route_plan_missing')
    values={quote.get('inputMint'),quote.get('outputMint')}
    for row in quote['routePlan']:
        swap=row.get('swapInfo') or {};values.update((swap.get('inputMint'),swap.get('outputMint')))
    if len(values)>8 or any(not isinstance(v,str) or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{32,44}',v) for v in values):
        raise ValueError('route_mints_invalid_or_budget_exceeded')
    return values


def control_pass(security):
    return (security.get('verified') is True and (security.get('raw') or {}).get('owner') in (TOKEN_PROGRAM,TOKEN_2022)
            and (security.get('extension_audit') or {}).get('verified') is True
            and type((security.get('raw_context') or {}).get('slot')) is int
            and security['raw_context']['slot']>0 and security.get('mint_revoked') is True
            and security.get('freeze_revoked') is True and
            (security.get('extension_audit') or {}).get('transfer_fee_bps')==0)


def flow_vaults(tx,source,target,signers,addresses):
    rows={}
    for field,sign in [('preTokenBalances',-1),('postTokenBalances',1)]:
        for row in tx['meta'].get(field,[]):
            owner=row.get('owner');mint=row.get('mint');index=row.get('accountIndex')
            if owner in signers or mint not in (source,target):continue
            if not isinstance(owner,str) or type(index) is not int or not 0<=index<len(addresses):continue
            key=(index,mint,owner)
            rows[key]=rows.get(key,0)+sign*uint64(row['uiTokenAmount']['amount'])
    inputs=[dict(address=addresses[i],mint=m,authority=o,role='input_vault') for (i,m,o),delta in rows.items() if m==source and delta>0]
    outputs=[dict(address=addresses[i],mint=m,authority=o,role='output_vault') for (i,m,o),delta in rows.items() if m==target and delta<0]
    # Ambiguous split/multi-pool effects are not guessed into pool-vault identities.
    return inputs+outputs if len(inputs)==len(outputs)==1 else []


def audit_vaults(reader,proof,swap,mint_security):
    vaults=proof.get('vaults') or []
    result=dict(verified=False,vaults=vaults,accounts=[],observed_at=time.time())
    if len(vaults)!=2:return dict(result,reason='pool_vault_identity_unverified')
    data=reader.rpc('getMultipleAccounts',[[v['address'] for v in vaults],
        {'encoding':'base64','commitment':'finalized','minContextSlot':proof['slot']}])
    values=(data or {}).get('value');slot=((data or {}).get('context') or {}).get('slot')
    if not isinstance(values,list) or len(values)!=2 or type(slot) is not int or slot<proof['slot']:
        return dict(result,reason='pool_vault_snapshot_unavailable')
    for vault,value in zip(vaults,values):
        minimum=uint64(swap['outAmount']) if vault['role']=='output_vault' else 0
        program=(mint_security[vault['mint']].get('raw') or {}).get('owner')
        audit=audit_raw_token_account(value,vault['mint'],vault['authority'],program,minimum)
        result['accounts'].append(dict(address=vault['address'],role=vault['role'],audit=audit,raw=value))
    result.update(verified=all(a['audit']['verified'] for a in result['accounts']),context_slot=slot,
        observed_at=time.time(),minimum_finalized_slot=proof['slot'])
    return result


def sell_flow_proof(tx,signature,source,target,pool,program,min_slot,now):
    """Exact successful finalized tx requested by caller; signer balance-flow evidence.
    Every SELL leg needs its own evidence; no inference from BUY count or quote alone.
    """
    if (not isinstance(tx,dict) or not isinstance(tx.get('meta'),dict)
        or 'err' not in tx['meta'] or tx['meta']['err'] is not None
        or signature not in tx.get('transaction',{}).get('signatures',[])
        or not number(tx.get('slot')) or tx['slot']<min_slot
        or not number(tx.get('blockTime')) or not 0<=now-tx['blockTime']<=120):return None
    message=tx.get('transaction',{}).get('message',{})
    keys=message.get('accountKeys') or []
    addresses=[k.get('pubkey') if isinstance(k,dict) else k for k in keys]
    if pool not in addresses:return None
    instructions=list(message.get('instructions') or [])
    for group in tx['meta'].get('innerInstructions') or []:instructions+=group.get('instructions') or []
    if not any(i.get('programId')==program for i in instructions):return None
    signers={k['pubkey'] for k in keys if isinstance(k,dict) and k.get('signer') is True}
    pre={};post={}
    try:
        for destination,field in [(pre,'preTokenBalances'),(post,'postTokenBalances')]:
            if field not in tx['meta']:return None
            for row in tx['meta'][field]:
                owner=row.get('owner');mint=row.get('mint')
                if owner in signers and mint in (source,target):
                    destination[owner,mint]=destination.get((owner,mint),0)+uint64(row['uiTokenAmount']['amount'])
        for owner in signers:
            sold=pre.get((owner,source),0)-post.get((owner,source),0)
            received=post.get((owner,target),0)-pre.get((owner,target),0)
            if source==WSOL and sold<=0 and owner in addresses:
                index=addresses.index(owner)
                sold=uint64(tx['meta']['preBalances'][index])-uint64(tx['meta']['postBalances'][index])-uint64(tx['meta'].get('fee',0))
            native=False
            if target==WSOL and received<=0 and owner in addresses:
                index=addresses.index(owner)
                received=uint64(tx['meta']['postBalances'][index])-uint64(tx['meta']['preBalances'][index])
                native=True
            if sold>0 and received>0:
                vaults=flow_vaults(tx,source,target,signers,addresses)
                if not vaults:return None
                return dict(signature=signature,slot=tx['slot'],block_time=tx['blockTime'],
                    commitment='finalized',input_mint=source,output_mint=target,pool=pool,
                    program=program,vaults=vaults,sold_raw=sold,received_raw=received,native_sol_received=native,
                    scope='observed_successful_swap_program_and_signer_balance_flow',transaction=tx)
    except (ValueError,TypeError,KeyError,IndexError):return None
    return None


def audit_route(reader,mint,position_quantity=None):
    result=dict(verified=False,purpose='paper_entry' if position_quantity is None else 'paper_exit',quote_asset=WSOL,buy_usd=5,all_mint_security={},pools={},
        sell_execution_evidence=[],reasons=[],scope='paper_route_eligibility_not_future_execution_guarantee')
    def fail(reason):
        result['reasons'].append(reason);return result
    def read_quote(*args,**kwargs):
        try:return reader.quote(*args,**kwargs)
        except RuntimeError as error:
            if str(error)=='HTTP_400':attempt['read_error_source']='quote'
            raise
    def security(address):
        saved=reader.security_snapshots.get(address)
        if not saved or not 0<=time.time()-saved.get('observed_at',0)<=30:saved=reader.security(address)
        result['all_mint_security'][address]=saved
        return saved
    try:
        # Use SOL as funding asset so every route mint can satisfy the same strict
        # revoked-authority policy. USDC is not silently exempted from freeze checks.
        prices=reader.request('https://api.jup.ag/price/v3?ids='+WSOL)
        value=(prices or {}).get(WSOL) or {};price=value.get('usdPrice');slot=value.get('blockId')
        if not number(price) or price<=0 or type(slot) is not int or slot<=0:return fail('sol_usd_valuation_unavailable')
        timestamp=reader.rpc('getBlockTime',[slot])
        result['valuation']=dict(raw=value,block_time=timestamp,source='Jupiter_price_v3_and_RPC_block_time')
        if not number(timestamp) or not 0<=time.time()-timestamp<=30:return fail('sol_usd_valuation_stale')
        amount=int((Decimal(5)/Decimal(str(price))*Decimal(10**9)).to_integral_value(rounding=ROUND_DOWN))
        if not 0<amount<2**64:return fail('sol_input_invalid')
        result['input_lamports']=amount
        # Inspect best route, then a direct route if any control or topology cannot
        # be established. Each alternative is independently audited from scratch.
        for direct in (False,True):
            result['sell_execution_evidence']=[]
            attempt=dict(direct=direct,mint_checks={},reasons=[])
            result.setdefault('attempts',[]).append(attempt)
            try:
                buy=None
                if position_quantity is None:
                    buy=read_quote(WSOL,mint,amount,direct=direct);result['buy_quote']=buy;attempt['buy_quote']=buy
                    for address in sorted(route_mints(buy)):
                        ok=control_pass(security(address));attempt['mint_checks'][address]=ok
                        if not ok:attempt['reasons'].append('mint_controls_unverified_'+address)
                    if attempt['reasons']:continue
                    if not validate_quote(buy,WSOL,mint,amount,result['all_mint_security']):
                        attempt['reasons'].append('buy_quote_invalid');continue
                    token_amount=uint64(buy['otherAmountThreshold'])
                else:
                    target=security(mint)
                    if not control_pass(target):return fail('exit_mint_controls_unverified')
                    decimals=target['extension_audit'].get('decimals')
                    if type(decimals) is not int or not 0<=decimals<=255:return fail('exit_token_decimals_unverified')
                    token_amount=uint64(int((Decimal(str(position_quantity))*Decimal(10)**decimals).to_integral_value(rounding=ROUND_DOWN)))
                    if token_amount<=0:return fail('exit_quantity_unverified')
                    result['position_raw_amount']=token_amount
                sell=read_quote(mint,WSOL,token_amount,direct=direct);result['sell_quote']=sell;attempt['sell_quote']=sell
                for address in sorted(route_mints(sell)):
                    ok=control_pass(security(address));attempt['mint_checks'][address]=ok
                    if not ok:attempt['reasons'].append('mint_controls_unverified_'+address)
                if attempt['reasons']:continue
                if not validate_quote(sell,mint,WSOL,token_amount,result['all_mint_security']):
                    attempt['reasons'].append('sell_quote_invalid');continue
                quotes=[buy,sell] if buy else [sell]
                # Verify pool account ownership against Jupiter's supported program map.
                labels=reader.request('https://api.jup.ag/swap/v1/program-id-to-label')
                if not isinstance(labels,dict):return fail('supported_amm_programs_unavailable')
                for quote in quotes:
                    for leg in quote['routePlan']:
                        swap=leg['swapInfo'];key=swap['ammKey']
                        if key in result['pools'] and time.time()-result['pools'][key]['observed_at']<=30:continue
                        account=reader.rpc('getAccountInfo',[key,{'encoding':'base64','commitment':'finalized'}])
                        raw=(account or {}).get('value') or {};owner=raw.get('owner');context=(account or {}).get('context') or {}
                        if raw.get('executable') is not False or owner not in labels or not number(context.get('slot')):
                            attempt['reasons'].append('pool_program_unverified_'+key);break
                        result['pools'][key]=dict(owner=owner,context=context,label=labels[owner],observed_at=time.time())
                if attempt['reasons']:continue
                # Fresh finalized SELL evidence is required for every leg. Unknown or
                # missing transaction/flow stays a rejection, not an assumed success.
                proof_legs=([('BUY',v) for v in buy['routePlan']] if buy else [])+[('SELL',v) for v in sell['routePlan']]
                for side,leg in proof_legs:
                    swap=leg['swapInfo'];key=swap['ammKey'];program=result['pools'][key]['owner']
                    anchor=max(result['all_mint_security'][v].get('raw_context',{}).get('slot',0)
                        for v in (swap['inputMint'],swap['outputMint']))
                    signatures=reader.rpc('getSignaturesForAddress',[key,{'limit':10,'commitment':'finalized'}])
                    if not isinstance(signatures,list):return fail('sell_history_unavailable')
                    execution_check=dict(side=side,pool=key,input_mint=swap['inputMint'],output_mint=swap['outputMint'],
                        minimum_slot=anchor,signatures=signatures,transactions=[])
                    attempt.setdefault('execution_checks',[]).append(execution_check)
                    proof=None
                    for record in [s for s in signatures if s.get('err') is None and s.get('slot',0)>=anchor][:2]:
                        tx=reader.rpc('getTransaction',[record['signature'],{'encoding':'jsonParsed',
                            'commitment':'finalized','maxSupportedTransactionVersion':1}])
                        proof=sell_flow_proof(tx,record['signature'],swap['inputMint'],swap['outputMint'],key,program,anchor,time.time())
                        execution_check['transactions'].append(dict(signature=record['signature'],transaction=tx,
                            verified_flow=proof is not None))
                        if proof:break
                    if not proof:
                        execution_check['status']='no_qualifying_finalized_transaction' if not execution_check['transactions'] else 'flow_not_verified_in_bounded_sample'
                        attempt['reasons'].append('recent_finalized_'+side.lower()+'_unverified_'+key);break
                    execution_check['status']='verified_flow'
                    vault_audit=audit_vaults(reader,proof,swap,result['all_mint_security'])
                    execution_check['vault_audit']=vault_audit
                    if not vault_audit.get('verified'):
                        attempt['reasons'].append('pool_vault_transfer_state_unverified_'+key);break
                    result['sell_execution_evidence'].append(dict(proof,side=side,vault_audit=vault_audit))
                if attempt['reasons']:continue
                # Requote after slow RPC work. A changed pool/mint topology must not use
                # the previous route's security approval.
                # RPC audits can outlive a quote/price sample. Refresh accepted token
                # snapshots and SOL valuation before requesting the final pair of quotes.
                for address in set().union(*(route_mints(q) for q in quotes)):
                    if time.time()-result['all_mint_security'][address]['observed_at']>15:
                        result['all_mint_security'][address]=reader.security(address)
                    if not control_pass(result['all_mint_security'][address]):return fail('route_controls_changed')
                prices=reader.request('https://api.jup.ag/price/v3?ids='+WSOL)
                value=(prices or {}).get(WSOL) or {};price=value.get('usdPrice');slot=value.get('blockId')
                if not number(price) or price<=0 or type(slot) is not int:return fail('sol_usd_revaluation_unavailable')
                timestamp=reader.rpc('getBlockTime',[slot])
                if not number(timestamp) or not 0<=time.time()-timestamp<=30:return fail('sol_usd_revaluation_stale')
                amount=int((Decimal(5)/Decimal(str(price))*Decimal(10**9)).to_integral_value(rounding=ROUND_DOWN))
                result['valuation_final']=dict(raw=value,block_time=timestamp)
                result['input_lamports']=amount
                start=time.time();fresh_buy=read_quote(WSOL,mint,amount,direct=direct) if buy else None
                fresh_amount=uint64(fresh_buy['otherAmountThreshold']) if fresh_buy else token_amount
                fresh_sell=read_quote(mint,WSOL,fresh_amount,direct=direct)
                topology=lambda q:[(r['swapInfo']['ammKey'],r['swapInfo']['inputMint'],r['swapInfo']['outputMint']) for r in q['routePlan']]
                if (buy and topology(fresh_buy)!=topology(buy)) or topology(fresh_sell)!=topology(sell):
                    attempt['reasons'].append('route_changed_during_audit');continue
                if ((buy and not validate_quote(fresh_buy,WSOL,mint,amount,result['all_mint_security'])) or
                    not validate_quote(fresh_sell,mint,WSOL,fresh_amount,result['all_mint_security'])):
                    attempt['reasons'].append('refreshed_quote_invalid');continue
                fresh_quotes=[fresh_buy,fresh_sell] if fresh_buy else [fresh_sell]
                used=set().union(*(route_mints(q) for q in fresh_quotes))
                if any(not 0<=time.time()-result['all_mint_security'][v]['observed_at']<=30 for v in used):
                    attempt['reasons'].append('route_mint_security_stale');continue
                if not 0<=time.time()-timestamp<=30:return fail('sol_usd_valuation_stale_after_audit')
                for proof in result['sell_execution_evidence']:
                    if time.time()-proof['vault_audit']['observed_at']>15:
                        swap=next((leg['swapInfo'] for q in fresh_quotes for leg in q['routePlan']
                            if leg['swapInfo']['ammKey']==proof['pool'] and leg['swapInfo']['inputMint']==proof['input_mint']
                            and leg['swapInfo']['outputMint']==proof['output_mint']),None)
                        if swap is None:return fail('vault_revalidation_topology_missing')
                        proof['vault_audit']=audit_vaults(reader,proof,swap,result['all_mint_security'])
                        attempt.setdefault('vault_refreshes',[]).append(proof['vault_audit'])
                        if not proof['vault_audit'].get('verified'):return fail('vault_revalidation_failed')
                if any(time.time()-p['vault_audit']['observed_at']>30 for p in result['sell_execution_evidence'] if p.get('vault_audit')):
                    attempt['reasons'].append('vault_snapshot_stale');continue
                for q in fresh_quotes:
                    for leg in q['routePlan']:
                        swap=leg['swapInfo']
                        audits=[p['vault_audit'] for p in result['sell_execution_evidence'] if p['pool']==swap['ammKey'] and p['input_mint']==swap['inputMint'] and p['output_mint']==swap['outputMint']]
                        if not audits or not any(a['role']=='output_vault' and a['audit']['spendable_raw']>=uint64(swap['outAmount']) for audit in audits for a in audit['accounts']):
                            return fail('requote_exceeds_verified_vault_balance')
                if (time.time()-start>30 or not 0<=time.time()-timestamp<=30 or
                    any(not 0<=time.time()-result['all_mint_security'][v]['observed_at']<=30 for v in used)):
                    attempt['reasons'].append('route_evidence_stale_after_vault_refresh');continue
                result.update(verified=True,buy_quote=fresh_buy,sell_quote=fresh_sell,observed_at=start,
                    transfer_fee_bps=0,net_output_includes_amm_and_platform_fees=True,
                    quoted_roundtrip_loss_usd=(5-float(Decimal(fresh_sell['outAmount'])*Decimal(str(price))/Decimal(10**9))) if position_quantity is None else None,
                    quoted_exit_value_usd=float(Decimal(fresh_sell['outAmount'])*Decimal(str(price))/Decimal(10**9)),
                    fee_breakdown_complete=all('feeAmount' in r['swapInfo'] for q in fresh_quotes for r in q['routePlan']))
                return result
            except RuntimeError as error:
                if str(error)=='HTTP_400' and attempt.get('read_error_source')=='quote':
                    # A quote failure for the best route does not establish that
                    # the independently audited direct alternative is unavailable.
                    attempt['reasons'].append('quote_http_400_unverified')
                    attempt['error_code']='HTTP_400'
                    continue
                raise
        return fail('no_fully_audited_buy_sell_route')
    except Exception as error:
        # Safe errors only; never record URLs/keys from transport exceptions.
        result['reasons'].append('route_audit_unavailable_'+type(error).__name__)
        if isinstance(error,RuntimeError) and str(error).startswith(('HTTP_','RPC_error_','network_','rate_limit_')):result['error_code']=str(error)
        return result
