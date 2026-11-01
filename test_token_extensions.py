"""Synthetic adversarial regressions; these are not live BUY/SELL evidence."""
import base64
import struct
import unittest
import time
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sniper_token_extensions import audit_raw_mint,validate_quote,TOKEN_PROGRAM,TOKEN_2022
from solana_market_readonly import Reader,verify_stages,market_assessment
from solana_sniper_paper import candidate


def mint(extensions=(),owner=TOKEN_2022):
    data=bytearray(82);data[44]=6;data[45]=1
    if extensions:
        data+=bytes(83)+b'\x01'
        for kind,body in extensions:data+=struct.pack('<HH',kind,len(body))+body
    return dict(owner=owner,data=[base64.b64encode(data).decode(),'base64'])


def quote(a='A',b='B',amount=5000000):
    return dict(inputMint=a,outputMint=b,inAmount=str(amount),outAmount='4000000',
        otherAmountThreshold='3980000',swapMode='ExactIn',slippageBps=50,contextSlot=100,
        priceImpactPct='0.001',routePlan=[dict(percent=100,swapInfo=dict(inputMint=a,
        outputMint=b,inAmount=str(amount),outAmount='4000000',feeAmount='10',feeMint=a,ammKey='POOL'))])


class ExtensionTests(unittest.TestCase):
    def test_both_programs_without_extensions_can_pass(self):
        for owner in (TOKEN_PROGRAM,TOKEN_2022):
            self.assertTrue(audit_raw_mint(mint(owner=owner))['verified'])

    def test_metadata_only_does_not_block_2022(self):
        metadata=bytes(64)+struct.pack('<I',1)+b'A'+struct.pack('<I',1)+b'B'+struct.pack('<I',0)+struct.pack('<I',0)
        result=audit_raw_mint(mint([(18,bytes(64)),(19,metadata)]))
        self.assertTrue(result['verified']);self.assertEqual(result['transfer_fee_bps'],0)

    def test_all_unknown_or_restriction_types_rejected(self):
        for kind in (2,4,5,7,8,9,10,11,13,15,16,17,24,25,26,27,28,999):
            self.assertFalse(audit_raw_mint(mint([(kind,bytes(100))]))['verified'],kind)

    def test_transfer_fees_current_future_and_mutability(self):
        for current,future,authority,allowed in [(0,0,False,True),(1,0,False,False),
                    (0,1,False,False),(0,0,True,False),(10000,10000,False,False)]:
            body=(b'\x01'+bytes(31) if authority else bytes(32))+bytes(40)
            body+=struct.pack('<QQH',1,100,current)+struct.pack('<QQH',2,200,future)
            result=audit_raw_mint(mint([(1,body)]))
            self.assertEqual(result['verified'],allowed)
            self.assertEqual(result['transfer_fee_bps'],max(current,future))

    def test_active_delegate_hook_and_close_rejected(self):
        for kind,length in [(3,32),(12,32),(14,64)]:
            self.assertTrue(audit_raw_mint(mint([(kind,bytes(length))]))['verified'])
            self.assertFalse(audit_raw_mint(mint([(kind,b'\x01'+bytes(length-1))]))['verified'])
        self.assertTrue(audit_raw_mint(mint([(6,b'\x01')]))['verified'])
        self.assertFalse(audit_raw_mint(mint([(6,b'\x02')]))['verified'])

    def test_pausable_requires_no_authority_and_not_paused(self):
        self.assertTrue(audit_raw_mint(mint([(26,bytes(33))]))['verified'])
        for body in (bytes(32)+b'\x01',b'\x01'+bytes(32),bytes(32)+b'\x02',bytes(32)):
            self.assertFalse(audit_raw_mint(mint([(26,body)]))['verified'])

    def test_truncation_duplicate_unknown_hidden_after_metadata(self):
        for exts in [[(18,bytes(63))],[(18,bytes(64)),(18,bytes(64))],
                     [(18,bytes(64)),(999,b'')],[(19,bytes(80)+b'extra')]]:
            self.assertFalse(audit_raw_mint(mint(exts))['verified'])
        value=mint([(18,bytes(64))]);raw=base64.b64decode(value['data'][0])[:-1]
        value['data'][0]=base64.b64encode(raw).decode()
        self.assertFalse(audit_raw_mint(value)['verified'])

    def test_security_requires_raw_and_matching_authorities(self):
        reader=Reader();parsed=dict(owner=TOKEN_2022,data=dict(parsed=dict(type='mint',info=dict(
            isInitialized=True,mintAuthority=None,freezeAuthority=None))))
        def wrapped(value):return dict(context=dict(slot=100),value=value)
        with patch.object(reader,'rpc',side_effect=[wrapped(parsed),wrapped(mint([(18,bytes(64))]))]):
            result=reader.security('M');self.assertTrue(result['verified'])
        raw=mint();data=bytearray(base64.b64decode(raw['data'][0]));data[0]=1
        raw['data'][0]=base64.b64encode(data).decode()
        with patch.object(reader,'rpc',side_effect=[wrapped(parsed),wrapped(raw)]):
            self.assertFalse(reader.security('M')['verified'])

    def test_2022_verified_extensions_no_blanket_program_rejection(self):
        reader=Reader();reader.security=Mock(return_value=dict(verified=True,authority_data_verified=True,
            mint_revoked=True,freeze_revoked=True,raw=dict(owner=TOKEN_2022),extension_audit=dict(verified=True)))
        reader.mint_birth=Mock(return_value=dict(block_time=time.time()-600,signature='INIT'))
        checks,_=market_assessment(candidate())
        _,_,reasons,_=verify_stages(reader,'M',checks)
        self.assertEqual(reasons,[])
        self.assertEqual(checks['extensions']['status'],'pass')

    def test_quote_invalid_routes_fees_and_amounts_rejected(self):
        self.assertTrue(validate_quote(quote(),'A','B',5000000))
        for field,value in [('inputMint','C'),('inAmount','1'),('outAmount','0'),('otherAmountThreshold','1'),('routePlan',[]),
                            ('slippageBps',100),('priceImpactPct','nan'),('contextSlot',0),('contextSlot',True),('outAmount',4.5),('outAmount',str(2**80))]:
            q=quote();q[field]=value;self.assertFalse(validate_quote(q,'A','B',5000000),field)
        q=quote();q['routePlan'][0]['swapInfo']['feeAmount']='-1'
        self.assertFalse(validate_quote(q,'A','B',5000000))

    def test_live_v2_quotes_with_deprecated_fee_fields_absent_are_supported(self):
        # Saved read-only market evidence, not a hypothetical field schema.
        evidence=__import__('json').loads(Path('sniper_token2022_final_live.json').read_text())
        cases=[c for r in evidence['rounds'] for c in r['candidates']
            if c.get('sell_route',{}).get('buy_quote') and c['symbol']=='Pum Coin']
        self.assertTrue(cases)
        q=cases[0]['sell_route']['buy_quote']
        self.assertTrue(validate_quote(q,q['inputMint'],q['outputMint'],5000000))
        self.assertTrue(all('feeAmount' not in l['swapInfo'] for l in q['routePlan']))
        q=quote();q['routePlan'][0]['swapInfo'].pop('feeAmount')
        self.assertFalse(validate_quote(q,'A','B',5000000))

    def test_multihop_via_canonical_sol_and_conservation(self):
        q=quote();sol='So11111111111111111111111111111111111111112'
        q['routePlan'][0]['swapInfo'].update(outputMint=sol,outAmount='100',feeMint='A')
        q['routePlan'].append(dict(percent=100,swapInfo=dict(inputMint=sol,outputMint='B',
            inAmount='100',outAmount='4000000',feeAmount='1',feeMint=sol,ammKey='SECOND')))
        self.assertTrue(validate_quote(q,'A','B',5000000))
        q['routePlan'][1]['swapInfo']['inAmount']='101'
        self.assertFalse(validate_quote(q,'A','B',5000000))
        q['routePlan'][1]['swapInfo']['inputMint']='UNVERIFIED'
        self.assertFalse(validate_quote(q,'A','B',5000000))

    def test_quote_helper_uses_only_gets_without_wallet_or_transactions(self):
        reader=Reader()
        with patch.object(reader,'request',side_effect=[quote('A','B'),quote('B','A',3980000)]) as request:
            reader.quote('A','B',5000000);reader.quote('B','A',3980000,direct=True)
            self.assertEqual(request.call_count,2)
            for call in request.call_args_list:
                self.assertEqual(len(call.args),1);self.assertIn('/quote?',call.args[0])
                self.assertNotIn('wallet',call.args[0])
        with patch.object(reader,'request',return_value={}):
            self.assertFalse(reader.sell_route('M')['verified'])

    def test_rpc_fallback_only_on_network_failure_and_preserves_read_only_gate(self):
        from solana_market_readonly import PUBLIC_RPC,BACKUP_RPC
        reader=Reader();reader.rpc_url=reader.active_rpc_url=PUBLIC_RPC
        with patch.object(reader,'request',side_effect=[RuntimeError('network_timeout_or_unavailable'),{'result':[]}]) as request:
            self.assertEqual(reader.rpc('getSignaturesForAddress',['M',{'commitment':'finalized'}]),[])
            self.assertEqual([c.args[0] for c in request.call_args_list],[PUBLIC_RPC,BACKUP_RPC])
            self.assertEqual(reader.active_rpc_url,BACKUP_RPC)
        for url,error in [(PUBLIC_RPC,'HTTP_429'),('https://configured.invalid','network_timeout_or_unavailable')]:
            reader=Reader();reader.rpc_url=reader.active_rpc_url=url
            with patch.object(reader,'request',side_effect=RuntimeError(error)) as request:
                with self.assertRaises(RuntimeError):reader.rpc('getAccountInfo',['M'])
                self.assertEqual(request.call_count,1)
        with patch.object(reader,'request') as request:
            with self.assertRaises(ValueError):reader.rpc('sendTransaction',[])
            request.assert_not_called()

    def test_failed_age_rpc_does_not_inherit_another_mints_scan_diagnostic(self):
        reader=Reader();reader.last_birth_scan=dict(mint='PREVIOUS',pages=7)
        with patch.object(reader,'rpc',side_effect=RuntimeError('RPC_error_-1')):
            with self.assertRaises(RuntimeError):reader.mint_birth('CURRENT')
        self.assertEqual(reader.last_birth_scan['mint'],'CURRENT')
        self.assertNotIn('pages',reader.last_birth_scan)

    def test_runtime_blocks_missing_extensions_or_sell_route_before_buy(self):
        from solana_market_readonly import run
        now=time.time()
        pair=dict(chainId='solana',pairAddress='POOL',baseToken=dict(address='M',symbol='FIXTURE'),
            priceUsd='1',pairCreatedAt=(now-600)*1000,liquidity=dict(usd=12000),
            volume=dict(m5=1800),txns=dict(m5=dict(buys=18,sells=12)))
        for extensions,route in [(False,True),(True,False)]:
            reader=Reader();reader.discover=lambda *args:(['M'],[pair],{})
            reader.security=Mock(return_value=dict(verified=extensions,authority_data_verified=True,
                mint_revoked=True,freeze_revoked=True,raw=dict(owner=TOKEN_2022),
                extension_audit=dict(verified=extensions),observed_at=now))
            reader.mint_birth=Mock(return_value=dict(block_time=now-600,signature='INIT'))
            reader.sell_route=Mock(return_value=dict(verified=route,observed_at=now))
            with tempfile.TemporaryDirectory() as d:
                args=SimpleNamespace(state_db=str(Path(d)/'state.sqlite3'),rounds=1,interval=5,
                    max_security=1,max_tokens=30,onchain_transactions=0,output=str(Path(d)/'e.json'))
                with patch('solana_market_readonly.Reader',return_value=reader),patch('builtins.print'):
                    evidence=run(args)
            self.assertEqual(evidence['summary']['actions'],{'REJECT':1})
            self.assertEqual(evidence['summary']['open_positions'],{})
            self.assertEqual(evidence['summary']['security_pass_unique_by_program'][TOKEN_2022],0)
            if not extensions:reader.sell_route.assert_not_called()

    def test_discovery_sources_merge_positive_buy_hint_instead_of_erasing_it(self):
        from sniper_runtime import PersistentPaperBot
        address='A'*32
        data={'data':[dict(relationships=dict(base_token=dict(data=dict(id='solana_'+address))),
            attributes=dict(transactions=dict(m5=dict(buys=20))))]}
        with tempfile.TemporaryDirectory() as d:
            bot=PersistentPaperBot(str(Path(d)/'state.sqlite3'));reader=Reader(bot)
            with patch.object(reader,'new_pools',return_value=data),patch.object(reader,'recent_tokens',
                return_value=[dict(id=address)]),patch.object(reader,'market',return_value=[]):
                reader.discover(1,30,0)
            self.assertEqual(bot.cache_get('watch',address)['seed_buys'],20)
            bot.close()

    def test_jupiter_discovery_does_not_prove_age_or_security(self):
        reader=Reader();address='A'*32
        with patch.object(reader,'new_pools',return_value={'data':[]}),patch.object(reader,'recent_tokens',
            return_value=[dict(id=address,stats5m=dict(numBuys=20))]),patch.object(reader,'market',return_value=[]):
            mints,_,audit=reader.discover(1,30,0)
        self.assertIn(address,mints);self.assertEqual(audit['new_unique_addresses'],1)
        self.assertEqual(reader.proofs,{})

if __name__=='__main__':unittest.main(verbosity=2)
