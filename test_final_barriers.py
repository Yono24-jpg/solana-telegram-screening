"""Adversarial tests for bounded complete history, liquidity provenance and route audit.
Network fixtures are synthetic except the explicitly labelled saved API replay.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from solana_market_readonly import Reader,TOKEN_PROGRAM,TOKEN_2022,metrics,market_assessment
from sniper_runtime import PersistentPaperBot
from sniper_token_extensions import validate_quote
from sniper_route_audit import audit_route,sell_flow_proof,route_mints,WSOL
from test_relevance_and_birth import tx

MINT='A'*32;MID='B'*32;POOL='C'*32;PROGRAM='D'*32


def security(owner=TOKEN_PROGRAM):
    return dict(verified=True,mint_revoked=True,freeze_revoked=True,authority_data_verified=True,
        extension_audit=dict(verified=True,transfer_fee_bps=0,decimals=6),observed_at=time.time(),
        raw=dict(owner=owner),raw_context=dict(slot=10))


def q(source,target,amount,pool=POOL):
    return dict(inputMint=source,outputMint=target,inAmount=str(amount),outAmount=str(amount),
        otherAmountThreshold=str(amount*995//1000+1),swapMode='ExactIn',slippageBps=50,
        contextSlot=100,priceImpactPct='0.001',routePlan=[dict(bps=10000,percent=None,
        swapInfo=dict(inputMint=source,outputMint=target,inAmount=str(amount),outAmount=str(amount),ammKey=pool))])


def flow(source=MINT,target=WSOL,err=None,slot=12):
    return dict(slot=slot,blockTime=time.time()-2,transaction=dict(signatures=['SIG'],message=dict(
        accountKeys=[dict(pubkey='ACTOR',signer=True),dict(pubkey=POOL,signer=False),dict(pubkey='G'*32,signer=False),dict(pubkey='H'*32,signer=False)],
        instructions=[dict(programId=PROGRAM)])),meta=dict(err=err,fee=5000,
        preBalances=[100000000,0],postBalances=[110000000,0],
        preTokenBalances=[dict(owner='ACTOR',mint=source,uiTokenAmount=dict(amount='100')),
            dict(owner='J'*32,mint=source,accountIndex=2,uiTokenAmount=dict(amount='10')),
            dict(owner='J'*32,mint=target,accountIndex=3,uiTokenAmount=dict(amount='90'))],
        postTokenBalances=[dict(owner='ACTOR',mint=source,uiTokenAmount=dict(amount='50')),
                           dict(owner='ACTOR',mint=target,uiTokenAmount=dict(amount='80')),
            dict(owner='J'*32,mint=source,accountIndex=2,uiTokenAmount=dict(amount='60')),
            dict(owner='J'*32,mint=target,accountIndex=3,uiTokenAmount=dict(amount='10'))]))


class BarrierTests(unittest.TestCase):
    def test_no_20_page_lifetime_cap_and_no_40_signature_loss(self):
        with tempfile.TemporaryDirectory() as d:
            bot=PersistentPaperBot(Path(d)/'s.sqlite3');reader=Reader(bot)
            scan=dict(schema=2,before='CURSOR',pages=20,oldest=[dict(signature='FIRST',slot=1,err=None)]+[
                dict(signature='L'+str(i),slot=i+20,err=None) for i in range(60)],
                checked=['FIRST']+['L'+str(i) for i in range(40)],complete=False,cursors=['CURSOR'])
            bot.cache_put('birth_scan','M',scan)
            with patch.object(reader,'rpc',side_effect=[[],None,None]) as rpc:
                self.assertIsNone(reader.mint_birth('M'));self.assertEqual(rpc.call_args_list[0].args[1][1]['before'],'CURSOR')
            saved=bot.cache_get('birth_scan','M')
            self.assertEqual(saved['pages'],21);self.assertEqual(len(saved['oldest']),61)
            self.assertIn('L59',[v['signature'] for v in saved['oldest']]);bot.close()

    def test_search_can_find_init_outside_old_40_transaction_window(self):
        with tempfile.TemporaryDirectory() as d:
            bot=PersistentPaperBot(Path(d)/'s.sqlite3');reader=Reader(bot)
            signatures=[dict(signature='EARLY'+str(i),slot=i+1,err=None) for i in range(45)]+[dict(signature='SIG',slot=10,err=None)]
            bot.cache_put('birth_scan','M',dict(schema=2,before=None,pages=1,oldest=signatures,
                checked=['EARLY'+str(i) for i in range(45)],complete=True,cursors=[]))
            with patch.object(reader,'rpc',return_value=tx()):self.assertEqual(reader.mint_birth('M')['signature'],'SIG')
            bot.close()

    def test_old_truncated_index_is_migrated_without_faking_completeness(self):
        with tempfile.TemporaryDirectory() as d:
            bot=PersistentPaperBot(Path(d)/'s.sqlite3');reader=Reader(bot)
            old=dict(before='OLD',pages=20,oldest=[],checked=[],complete=True)
            bot.cache_put('birth_scan','M',old)
            with patch.object(reader,'rpc',return_value=[]) as rpc:reader.mint_birth('M')
            self.assertNotIn('before',rpc.call_args.args[1][1]);self.assertEqual(bot.cache_get('birth_scan_legacy','M'),old)
            bot.close()

    def test_none_history_is_unknown_not_provider_tail(self):
        reader=Reader()
        with patch.object(reader,'rpc',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'history_response_unavailable'):reader.mint_birth('M')

    def test_liquidity_missing_stale_and_below_remain_distinct(self):
        pair=dict(chainId='solana',baseToken=dict(address=MINT),priceUsd='1',liquidity=dict(usd=12000),
            volume=dict(m5=2000),txns=dict(m5=dict(buys=20,sells=10)),
            _market_observation=dict(received_at=100,http_cache_age=0))
        event=metrics(pair,140);checks,reasons=market_assessment(event)
        self.assertEqual(event['observed_at'],100);self.assertEqual(checks['liquidity_usd']['status'],'stale')
        self.assertIn('liquidity_usd_stale',reasons)
        pair['liquidity']['usd']=None
        self.assertEqual(market_assessment(metrics(pair,140))[0]['liquidity_usd']['status'],'unavailable')
        pair['_market_observation']['received_at']=140;pair['liquidity']['usd']=9999
        self.assertEqual(market_assessment(metrics(pair,140))[0]['liquidity_usd']['status'],'fail')
        pair['liquidity']['usd']=12000;pair['_market_observation']['http_cache_age']=31
        self.assertEqual(market_assessment(metrics(pair,140))[0]['liquidity_usd']['status'],'stale')

    def test_market_reader_preserves_http_receipt_not_processing_time(self):
        reader=Reader();pair=dict(chainId='solana',baseToken=dict(address=MINT),liquidity=dict(usd=12000))
        def request(url):reader.last_http_metadata=dict(received_at=10,http_cache_age=50);return [pair]
        with patch.object(reader,'request',side_effect=request):data=reader.market('/tokens/v1/solana/'+MINT)
        self.assertEqual(metrics(data[0],100)['data_age_seconds'],140)

    def test_intermediate_must_be_explicitly_verified_and_cycles_rejected(self):
        quote=q(MINT,WSOL,100000)
        quote['routePlan'][0]['swapInfo'].update(outputMint=MID)
        quote['routePlan'].append(dict(swapInfo=dict(inputMint=MID,outputMint=WSOL,inAmount='100000',outAmount='100000',ammKey=POOL)))
        self.assertFalse(validate_quote(quote,MINT,WSOL,100000))
        self.assertTrue(validate_quote(quote,MINT,WSOL,100000,[MID]))
        quote['routePlan'].append(dict(swapInfo=dict(inputMint=MID,outputMint=MID,inAmount='1',outAmount='1',ammKey=POOL)))
        self.assertFalse(validate_quote(quote,MINT,WSOL,100000,[MID]))

    def test_real_sell_instruction_label_does_not_prove_sale_of_target_mint(self):
        case=json.loads(Path('sniper_route_flow_replay.json').read_text());tx=case['transaction']
        self.assertIsNone(tx['meta']['err'])
        self.assertTrue(any('Instruction: Sell' in v for v in tx['meta']['logMessages']))
        # Evaluate the historical shape at its original time, not as fresh evidence.
        proof=sell_flow_proof(tx,case['signature'],case['source_mint'],case['target_mint'],
            case['pool'],case['program'],case['minimum_slot'],tx['blockTime']+1)
        self.assertIsNone(proof)

    def test_finalized_sell_needs_success_signature_program_pool_and_real_flows(self):
        self.assertIsNotNone(sell_flow_proof(flow(),'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time()))
        for value,args in [(flow(err='failed'),()),(flow(slot=9),())]:
            self.assertIsNone(sell_flow_proof(value,'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time()))
        value=flow();value['meta']['postTokenBalances'][0]['uiTokenAmount']['amount']='150'
        self.assertIsNone(sell_flow_proof(value,'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time()))
        self.assertIsNone(sell_flow_proof(flow(),'WRONG',MINT,WSOL,POOL,PROGRAM,10,time.time()))
        self.assertIsNone(sell_flow_proof(flow(),'SIG',MINT,WSOL,'OTHER',PROGRAM,10,time.time()))
        self.assertIsNone(sell_flow_proof(flow(),'SIG',MINT,WSOL,POOL,'OTHER',10,time.time()))

    def test_native_sol_sell_receipt_and_buy_payment_are_checked(self):
        value=flow();value['meta']['postTokenBalances']=[r for r in value['meta']['postTokenBalances'] if not (r['owner']=='ACTOR' and r['mint']==WSOL)]
        self.assertTrue(sell_flow_proof(value,'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time())['native_sol_received'])
        value['meta']['postBalances'][0]=90000000
        self.assertIsNone(sell_flow_proof(value,'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time()))

    def reader(self,unsafe=False,changed=False,no_sell=False):
        reader=Reader();reader.security=Mock(side_effect=lambda mint:dict(security(TOKEN_2022 if mint==MINT else TOKEN_PROGRAM),freeze_revoked=False if unsafe and mint==MINT else True))
        def request(url):
            if '/price/' in url:return {WSOL:dict(usdPrice=100,blockId=100)}
            return {PROGRAM:'Fixture AMM'}
        reader.request=Mock(side_effect=request)
        reader.quote=Mock(side_effect=lambda a,b,n,direct=False:q(a,b,n,pool=('E'*32 if changed and (reader.quote.call_count-1)%4>=2 else POOL)))
        def rpc(method,params):
            if method=='getBlockTime':return time.time()-1
            if method=='getAccountInfo':return dict(context=dict(slot=11),value=dict(owner=PROGRAM,executable=False))
            if method=='getSignaturesForAddress':return [] if no_sell else [dict(signature='SIG',slot=12,err=None)]
            # proof parser itself is tested above; orchestration uses a distinct stub below.
            return flow()
        reader.rpc=Mock(side_effect=rpc);return reader

    def test_complete_route_for_both_programs_and_every_buy_sell_leg(self):
        for owner in (TOKEN_PROGRAM,TOKEN_2022):
            reader=self.reader();reader.security.side_effect=lambda mint:security(owner)
            with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',return_value=dict(verified=True,observed_at=time.time(),accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])):
                result=audit_route(reader,MINT)
            self.assertTrue(result['verified'],result)
            self.assertEqual(set(result['all_mint_security']),{MINT,WSOL})
            self.assertEqual([p['side'] for p in result['sell_execution_evidence']],['BUY','SELL'])
            self.assertEqual(len(result['attempts'][0]['execution_checks']),2)
            self.assertTrue(result['attempts'][0]['execution_checks'][0]['transactions'])
            self.assertLessEqual(result['input_lamports']*100/1e9,5)

    def test_exit_audit_uses_the_actual_persisted_position_quantity(self):
        reader=self.reader()
        with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',return_value=dict(verified=True,observed_at=time.time(),accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])):
            result=audit_route(reader,MINT,position_quantity=12.345678)
        self.assertTrue(result['verified'],result)
        self.assertEqual(result['position_raw_amount'],12345678)
        self.assertEqual(result['sell_quote']['inAmount'],'12345678')
        self.assertTrue(all(c.args[0]==MINT for c in reader.quote.call_args_list))
        self.assertEqual([p['side'] for p in result['sell_execution_evidence']],['SELL'])

    def test_stale_vault_snapshots_are_revalidated_not_silently_reused(self):
        reader=self.reader();calls=[]
        def vaults(*args):
            calls.append(1)
            return dict(verified=True,observed_at=time.time()-(40 if len(calls)<=2 else 0),
                accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])
        with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',side_effect=vaults):
            result=audit_route(reader,MINT)
        self.assertTrue(result['verified'],result);self.assertEqual(len(calls),4)
        self.assertEqual(len(result['attempts'][0]['vault_refreshes']),2)

    def test_min_context_lag_retries_identical_finalized_request_with_bound(self):
        reader=Reader();params=['M',{'encoding':'base64','commitment':'finalized','minContextSlot':999}]
        lag={'error':{'code':-32016}}
        with patch.object(reader,'request',side_effect=[lag,lag,{'result':{'value':'GOOD'}}]) as request:
            self.assertEqual(reader.rpc('getAccountInfo',params),{'value':'GOOD'})
            self.assertEqual(request.call_count,3)
            self.assertTrue(all(c.args[1]['params']==params for c in request.call_args_list))
        with patch.object(reader,'request',return_value=lag) as request,patch('solana_market_readonly.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'RPC_error_-32016'):reader.rpc('getAccountInfo',params)
            self.assertEqual(request.call_count,3)

    def test_quote_http400_still_audits_direct_alternative_without_assuming_safe(self):
        reader=self.reader();original=reader.quote.side_effect
        def quote_failure(a,b,n,direct=False):
            if not direct:raise RuntimeError('HTTP_400')
            return original(a,b,n,direct=True)
        reader.quote.side_effect=quote_failure
        with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',return_value=dict(verified=True,observed_at=time.time(),accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])):
            result=audit_route(reader,MINT)
        self.assertTrue(result['verified'],result)
        self.assertEqual(result['attempts'][0]['error_code'],'HTTP_400')
        self.assertTrue(result['attempts'][1]['direct'])

    def test_rpc_http400_is_not_mislabeled_as_quote_failure(self):
        reader=self.reader();old=reader.rpc.side_effect
        reader.rpc.side_effect=lambda method,params: (_ for _ in ()).throw(RuntimeError('HTTP_400')) if method=='getAccountInfo' else old(method,params)
        result=audit_route(reader,MINT)
        self.assertFalse(result['verified']);self.assertEqual(len(result['attempts']),1)
        self.assertNotIn('quote_http_400_unverified',result['attempts'][0]['reasons'])

    def test_slow_last_vault_refresh_cannot_approve_stale_mint_and_quote_evidence(self):
        reader=self.reader();clock=[1000.0];calls=[]
        def vaults(*args):
            calls.append(1)
            if len(calls)>2:clock[0]+=20
            return dict(verified=True,observed_at=clock[0]-(20 if len(calls)<=2 else 0),
                accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])
        with patch('sniper_route_audit.time.time',side_effect=lambda:clock[0]),patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',side_effect=vaults):
            result=audit_route(reader,MINT)
        self.assertFalse(result['verified'],result)
        self.assertTrue(any('route_evidence_stale_after_vault_refresh' in a['reasons'] for a in result['attempts']))

    def test_unknown_controls_missing_sell_and_changed_topology_fail_closed(self):
        for kwargs in [dict(unsafe=True),dict(no_sell=True),dict(changed=True)]:
            reader=self.reader(**kwargs)
            with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',return_value=dict(verified=True,observed_at=time.time(),accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])):
                self.assertFalse(audit_route(reader,MINT)['verified'],kwargs)

    def test_all_intermediate_mints_are_audited_for_both_programs(self):
        for owner in (TOKEN_PROGRAM,TOKEN_2022):
            for unsafe in (False,True):
                reader=self.reader()
                reader.security.side_effect=lambda v:dict(security(owner),freeze_revoked=False if unsafe and v==MID else True)
                def multihop(a,b,n,direct=False):
                    quote=q(a,b,n);quote['routePlan'][0]['swapInfo']['outputMint']=MID
                    quote['routePlan'].append(dict(swapInfo=dict(inputMint=MID,outputMint=b,
                        inAmount=str(n),outAmount=str(n),ammKey='F'*32)))
                    return quote
                reader.quote.side_effect=multihop
                with patch('sniper_route_audit.sell_flow_proof',side_effect=lambda tx,sig,source,target,pool,program,anchor,now:dict(slot=12,signature=sig,pool=pool,input_mint=source,output_mint=target)),patch('sniper_route_audit.audit_vaults',return_value=dict(verified=True,observed_at=time.time(),accounts=[dict(role='output_vault',audit=dict(spendable_raw=2**64-1))])):
                    result=audit_route(reader,MINT)
                self.assertEqual(result['verified'],not unsafe,result)
                self.assertIn(MID,result['all_mint_security'])
                if not unsafe:self.assertEqual(len(result['sell_execution_evidence']),4)

    def test_unsafe_stablecoin_is_not_exempted_from_route_checks(self):
        from sniper_route_audit import USDC
        reader=self.reader()
        reader.security.side_effect=lambda v:dict(security(),freeze_revoked=False if v==USDC else True)
        def quote_with_usdc(a,b,n,direct=False):
            quote=q(a,b,n);quote['routePlan'][0]['swapInfo']['outputMint']=USDC
            quote['routePlan'].append(dict(swapInfo=dict(inputMint=USDC,outputMint=b,
                inAmount=str(n),outAmount=str(n),ammKey=POOL)))
            return quote
        reader.quote.side_effect=quote_with_usdc
        result=audit_route(reader,MINT)
        self.assertFalse(result['verified']);self.assertIn(USDC,result['all_mint_security'])
        self.assertFalse(any(c.args[0].startswith('send') for c in reader.rpc.call_args_list))

    def test_raw_vault_extensions_freeze_delegate_cpi_and_spendable_fee_balance(self):
        import base64,struct
        from sniper_token_extensions import audit_raw_token_account
        def value(program=TOKEN_PROGRAM,state=1,extensions=(),delegate=False):
            data=bytearray(165);data[64:72]=(1000).to_bytes(8,'little');data[108]=state
            if delegate:data[72]=1
            if extensions:
                data+=b'\x02'
                for kind,body in extensions:data+=struct.pack('<HH',kind,len(body))+body
            return dict(owner=program,data=[base64.b64encode(data).decode(),'base64'])
        check=lambda v,minimum=0:audit_raw_token_account(v,'1'*32,'1'*32,v['owner'],minimum)
        self.assertTrue(check(value())['verified'])
        self.assertFalse(check(value(state=2))['verified'])
        self.assertFalse(check(value(delegate=True))['verified'])
        for kind in (8,11,15):
            self.assertTrue(check(value(TOKEN_2022,extensions=[(kind,b'\0')]))['verified'])
            self.assertFalse(check(value(TOKEN_2022,extensions=[(kind,b'\x01')]))['verified'])
        for kind in (5,13,17,999):self.assertFalse(check(value(TOKEN_2022,extensions=[(kind,b'')]))['verified'])
        withheld=value(TOKEN_2022,extensions=[(2,(200).to_bytes(8,'little'))])
        self.assertEqual(check(withheld,1000)['spendable_raw'],1000)
        self.assertFalse(check(withheld,1001)['verified'])

    def test_vault_identity_is_required_even_when_signer_flows_look_like_sell(self):
        value=flow();value['meta']['preTokenBalances']=[r for r in value['meta']['preTokenBalances'] if r['owner']=='ACTOR']
        value['meta']['postTokenBalances']=[r for r in value['meta']['postTokenBalances'] if r['owner']=='ACTOR']
        self.assertIsNone(sell_flow_proof(value,'SIG',MINT,WSOL,POOL,PROGRAM,10,time.time()))

    def test_unknown_route_controls_or_program_cannot_be_whitelisted(self):
        from sniper_route_audit import control_pass
        for patch_value in [dict(raw=dict(owner='UNSUPPORTED')),dict(raw_context={}),
                            dict(extension_audit=dict(verified=False,transfer_fee_bps=0))]:
            value=security();value.update(patch_value);self.assertFalse(control_pass(value))

    def test_failed_exit_route_keeps_position_and_cannot_claim_sell(self):
        from types import SimpleNamespace
        from solana_sniper_paper import candidate
        from solana_market_readonly import run
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'s.sqlite3');bot=PersistentPaperBot(path)
            bot.process(candidate(MINT,pair_address=POOL));bot.close()
            reader=Reader();reader.discover=lambda *args:([],[],{})
            reader.market=lambda *args:dict(pairs=[dict(chainId='solana',pairAddress=POOL,
                baseToken=dict(address=MINT),priceUsd='1.3')])
            reader.exit_route=Mock(return_value=dict(verified=False,reasons=['sell_evidence_missing']))
            args=SimpleNamespace(state_db=path,rounds=1,interval=5,max_tokens=30,onchain_transactions=0,
                max_security=0,output=str(Path(d)/'e.json'))
            with patch('builtins.print'):evidence=run(args,reader_factory=lambda store:reader)
            self.assertEqual(evidence['rounds'][0]['marks'][0]['outcome']['action'],'PAPER_EXIT_BLOCKED_ROUTE')
            self.assertIn(MINT,evidence['summary']['open_positions'])

if __name__=='__main__':unittest.main(verbosity=2)
