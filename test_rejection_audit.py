"""Audit and fail-closed nullable-data regression tests. No network access."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sniper_rejection_audit import audit
from solana_market_readonly import Reader, market_assessment, run
from solana_sniper_paper import candidate


class AuditTests(unittest.TestCase):
    def test_original_406_counts_and_independent_raw_reconciliation(self):
        evidence=json.loads(Path(__file__).with_name('sniper_market_evidence.json').read_text())
        result=audit(evidence)
        self.assertEqual((result['checks'],result['unique_mints']),(406,123))
        self.assertEqual(result['overlapping_counts']['liquidity'],{'fail':40,'unavailable':118,'pass':248})
        self.assertEqual(result['disjoint_decisions'],dict(observed_market_violation=398,
                            unavailable_data_only=4,token_2022_policy_only=4))
        self.assertEqual(result['raw_extraction_mismatches'],[])
        self.assertEqual(result['api']['failed_attempts'],0)
        self.assertEqual(result['overlapping_counts']['mint_age'],{'not_checked':406})

    def test_replay_original_406_keeps_all_rejections_without_relaxing_filters(self):
        evidence=json.loads(Path(__file__).with_name('sniper_market_evidence.json').read_text())['extended_runtime']
        checks=0;market_blocked=0;security_blocked=0
        for live in (evidence['live_observation'],evidence['live_after_restart']):
            for row in live['rounds']:
                for c in row['candidates']:
                    checks+=1
                    statuses,reasons=market_assessment(c['event'])
                    if reasons:market_blocked+=1
                    else:
                        self.assertEqual(c['security']['reason'],'unsupported_token_2022_extensions')
                        self.assertFalse(c['security']['verified'])
                        security_blocked+=1
        self.assertEqual((checks,market_blocked,security_blocked),(406,402,4))

    def test_unknown_liquidity_never_means_below_threshold(self):
        event=candidate(liquidity_usd=None)
        checks,reasons=market_assessment(event)
        self.assertEqual(checks['liquidity_usd']['status'],'unavailable')
        self.assertEqual(reasons,['liquidity_usd_unavailable'])
        checks,reasons=market_assessment(candidate(liquidity_usd=9999))
        self.assertEqual(checks['liquidity_usd']['status'],'fail')
        self.assertEqual(reasons,['liquidity_usd'])
        self.assertNotIn('liquidity_usd',market_assessment(candidate(liquidity_usd=10000))[1])

    def test_undefined_ratio_not_recorded_as_passing(self):
        checks,reasons=market_assessment(candidate(buys_5m=0,sells_5m=0))
        self.assertEqual(checks['buy_sell_ratio']['status'],'unavailable')
        self.assertIn('buys_5m',reasons)
        checks,reasons=market_assessment(candidate(buys_5m=12,sells_5m=0))
        self.assertEqual(checks['buy_sell_ratio']['status'],'pass_no_sells')
        self.assertEqual(reasons,[])

    def simulation(self, refreshed_liquidity=None, wrong_pair=False, count=1, low_volume=False):
        now=time.time()
        def pair(mint,liquidity):
            return dict(chainId='solana',pairAddress='PAIR_'+mint,baseToken=dict(address=mint,symbol=mint),
                priceUsd='1',pairCreatedAt=(now-600)*1000,liquidity=dict(usd=liquidity),
                volume=dict(m5=1499 if low_volume else 1800),txns=dict(m5=dict(buys=18,sells=12)))
        mints=[str(i) for i in range(count)]
        fake=Reader()
        fake.discover=lambda *args:(mints,[pair(m,None) for m in mints],{})
        fake.security=Mock(side_effect=AssertionError('Security cannot run until market metrics are verified'))
        def market(path):
            value=pair(path[-1],refreshed_liquidity)
            if wrong_pair:value['pairAddress']='DIFFERENT_POOL'
            return dict(pairs=[value])
        fake.market=Mock(side_effect=market)
        with tempfile.TemporaryDirectory() as folder:
            args=SimpleNamespace(state_db=str(Path(folder)/'paper.sqlite3'),rounds=1,interval=5,
                max_tokens=120,onchain_transactions=0,max_security=3,output=str(Path(folder)/'result.json'))
            with patch('solana_market_readonly.Reader',return_value=fake),patch('builtins.print'):
                result=run(args)
        return result,fake

    def test_same_pair_reread_still_null_remains_unavailable(self):
        result,reader=self.simulation()
        c=result['rounds'][0]['candidates'][0]
        self.assertEqual(c['outcome']['reasons'],['liquidity_usd_unavailable'])
        self.assertTrue(c['data_refresh']['still_unavailable'])
        self.assertEqual(result['summary']['actions'],{'REJECT':1})
        reader.security.assert_not_called()

    def test_same_pair_reread_proves_low_liquidity(self):
        result,reader=self.simulation(refreshed_liquidity=9999)
        c=result['rounds'][0]['candidates'][0]
        self.assertEqual(c['outcome']['reasons'],['liquidity_usd'])
        self.assertEqual(c['checks']['liquidity_usd']['value'],9999)
        reader.security.assert_not_called()

    def test_different_pool_cannot_fill_missing_metric(self):
        result,reader=self.simulation(refreshed_liquidity=12000,wrong_pair=True)
        c=result['rounds'][0]['candidates'][0]
        self.assertEqual(c['outcome']['reasons'],['liquidity_usd_unavailable'])
        self.assertEqual(c['data_refresh']['status'],'failed')
        reader.security.assert_not_called()

    def test_reread_budget_and_other_market_failures(self):
        result,reader=self.simulation(count=5)
        self.assertEqual(reader.market.call_count,3)
        self.assertEqual(result['summary']['actions'],{'REJECT':5})
        result,reader=self.simulation(low_volume=True)
        reader.market.assert_not_called()
        c=result['rounds'][0]['candidates'][0]
        self.assertIn('volume_5m_usd',c['outcome']['reasons'])
        self.assertIn('liquidity_usd_unavailable',c['outcome']['reasons'])


if __name__=='__main__':unittest.main(verbosity=2)
