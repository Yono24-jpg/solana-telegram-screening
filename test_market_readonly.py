"""Deterministic regression tests; never contacts a network."""
import ast
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from solana_sniper_paper import PaperBot, candidate, self_test
from solana_market_readonly import Reader, TOKEN_PROGRAM, TOKEN_2022, decode_security, decode_birth, metrics


class ReadOnlyTests(unittest.TestCase):
    def test_original_regressions(self):
        self_test()

    def test_security_missing_fields_is_not_revocation(self):
        value = dict(owner=TOKEN_PROGRAM, data={'parsed':{'type':'mint','info':{'isInitialized':True}}})
        self.assertFalse(decode_security(value)['verified'])
        value['data']['parsed']['info'].update(mintAuthority=None, freezeAuthority=None)
        self.assertTrue(decode_security(value)['verified'])
        self.assertTrue(decode_security(value)['mint_revoked'])
        value['data']['parsed']['info']['freezeAuthority'] = 'ACTIVE_AUTHORITY'
        self.assertFalse(decode_security(value)['freeze_revoked'])

    def test_token_2022_authorities_visible_but_not_approved(self):
        value = dict(owner=TOKEN_2022, data={'parsed':{'type':'mint','info':{
            'isInitialized':True,'mintAuthority':None,'freezeAuthority':None}}})
        decoded=decode_security(value)
        self.assertTrue(decoded['authority_data_verified'])
        self.assertTrue(decoded['mint_revoked'])
        self.assertTrue(decoded['freeze_revoked'])
        self.assertFalse(decoded['verified'])
        value['owner'] = 'TOKEN_2022_OR_OTHER'
        self.assertFalse(decode_security(value)['verified'])

    def test_birth_requires_successful_exact_mint_initialize(self):
        instruction = dict(programId=TOKEN_PROGRAM, parsed=dict(type='initializeMint2',info=dict(mint='M')))
        tx = dict(blockTime=100, meta=dict(err=None), transaction=dict(message=dict(instructions=[instruction])))
        self.assertEqual(decode_birth(tx,'M'), 100)
        self.assertIsNone(decode_birth(tx,'OTHER'))
        tx['meta']['err'] = 'FAILED'
        self.assertIsNone(decode_birth(tx,'M'))
        tx['meta'] = dict(err=None, innerInstructions=[dict(instructions=[instruction])])
        tx['transaction']['message']['instructions'] = []
        self.assertEqual(decode_birth(tx,'M'),100)

    def test_rpc_trade_methods_blocked_before_http(self):
        reader = Reader()
        with patch.object(reader,'request') as request:
            for method in ('sendTransaction','sendBundle','requestAirdrop','simulateTransaction'):
                with self.assertRaises(ValueError):
                    reader.rpc(method,[])
            request.assert_not_called()

    def test_market_path_blocks_trade_and_external_hosts(self):
        reader = Reader()
        with self.assertRaises(ValueError):
            reader.market('https://evil.invalid/send')
        with self.assertRaises(ValueError):
            reader.market('/swap')

    def test_unknown_mint_age_stays_unknown(self):
        pair = dict(chainId='solana',baseToken=dict(address='M'),priceUsd='1',pairCreatedAt=900000,
                    liquidity=dict(usd=12000), volume=dict(m5=1800), txns=dict(m5=dict(buys=18,sells=12)))
        event=metrics(pair,1000)
        self.assertAlmostEqual(event['pool_age_minutes'],100/60)
        self.assertIsNone(event['age_minutes'])
        event.update(mint_revoked=True,freeze_revoked=True)
        self.assertIn('mint_age_unverified',PaperBot().process(event)['reasons'])

    def test_costs_slippage_and_gap_exit(self):
        bot=PaperBot(fee=.013,fixed=.05,slippage_bps=50)
        bot.process(candidate())
        self.assertAlmostEqual(bot.positions['SYNTHETIC_A']['cost'],5.115)
        # +20% quote is insufficient for +20% from an entry filled 0.5% higher.
        event=dict(type='price',mint='SYNTHETIC_A',price=1.2,now=1001,observed_at=1001)
        self.assertEqual(bot.process(event)['action'],'HOLD')
        event.update(price=.8,now=1002,observed_at=1002)
        sell=bot.process(event)
        self.assertEqual(sell['trigger'],'SL')
        expected=(5/1.005)*.8*.995*.987-.05-5.115
        self.assertAlmostEqual(sell['net_pnl_usd'],expected,places=6)

    def test_position_limit_many_candidates(self):
        bot=PaperBot()
        actions=[bot.process(candidate(str(i)))['action'] for i in range(100)]
        self.assertEqual(actions.count('PAPER_BUY'),2)
        self.assertEqual(len(bot.positions),2)

    def test_no_signing_dependency(self):
        for name in ('solana_sniper_paper.py','solana_market_readonly.py'):
            tree=ast.parse(Path(__file__).with_name(name).read_text())
            imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
            imports += [a.name for node in ast.walk(tree) if isinstance(node,ast.Import) for a in node.names]
            self.assertFalse(any(i.startswith(('solders','solana','web3')) for i in imports
                                 if i != 'solana_sniper_paper'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
