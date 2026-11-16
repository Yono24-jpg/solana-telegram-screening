import copy
import os
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock,patch
import birdeye_standard as bird
import data_intelligence as di
import state_store
from test_upgrade import MINT,NOW
from test_global_v5 import market_pool


class Standard(unittest.TestCase):
    def client(self,state=None):return di.Client(SimpleNamespace(REQUEST_DEADLINE=None),state if state is not None else {}).bird
    def overview(self):return {'success':True,'data':{'address':MINT,'price':1.05,'marketCap':105000,'circulatingSupply':100000,'liquidity':9999999,'v1hUSD':8888888,'lastTradeUnixTime':NOW}}
    def test_cache_reuse_does_not_spend_cu_and_has_exact_identity(self):
        client=self.client();client.transport=Mock(return_value=self.overview())
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':'test-secret','BIRDEYE_NETWORK_ENABLED':'1'}),patch.object(bird.time,'time',return_value=NOW):
            a=client.read(MINT);a['price']=0
            self.assertEqual(client.read(MINT)['price'],1.05)
        self.assertEqual(client.stats['reserved_cu'],18);self.assertEqual(client.stats['cache_hits'],1)
        self.assertNotIn('test-secret',str(client.record)+str(client.report()))
    def test_unknown_endpoint_and_unmetered_request_do_not_reach_network(self):
        client=self.client();client.transport=Mock()
        self.assertIsNone(client.read(MINT,'paid_unknown'));client.transport.assert_not_called()
        with self.assertRaises(di.Unavailable):client.parent.request('birdeye','https://public-api.birdeye.so/defi/price')
    def test_monthly_limit_survives_restart_and_inactivity(self):
        day=int(NOW//86400);state={'provider_state_v5':{'birdeye':{'at':NOW-3*86400,'cu_days':{str(day-3):23999}}}}
        state_store.migrate(state,NOW);client=self.client(state);client.transport=Mock()
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':'test'}),patch.object(bird.time,'time',return_value=NOW):self.assertIsNone(client.read(MINT,'price'))
        client.transport.assert_not_called();self.assertEqual(client.report()['estimated_cu_31d'],23999)
    def test_denied_overview_does_not_disable_allowed_price_and_both_are_metered(self):
        client=self.client();client.transport=Mock(side_effect=[urllib.error.HTTPError('private',403,'hidden',{},None),{'success':True,'data':{'value':1,'updateUnixTime':NOW}}])
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':'test'}),patch.object(bird.time,'time',return_value=NOW),patch.object(bird.time,'sleep') as sleep:
            self.assertIsNone(client.read(MINT));self.assertEqual(client.read(MINT,'price')['value'],1)
        sleep.assert_called_once();self.assertGreaterEqual(sleep.call_args.args[0],1)
        self.assertEqual(client.report()['reserved_cu'],21);self.assertEqual(client.record['endpoints']['overview']['status'],'http_403')
    def test_cache_and_market_evidence_expire_without_renewing_timestamp(self):
        client=self.client();client.transport=Mock(return_value=self.overview())
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':'test'}),patch.object(bird.time,'time',return_value=NOW):data=client.read(MINT)
        pool=market_pool();pool['marketCap']=None
        with patch.object(bird.time,'time',return_value=NOW+121):self.assertEqual(client.apply(pool,data),0)
        self.assertIsNone(pool['marketCap'])
    def test_only_consistent_circulating_cap_can_fill_not_pool_aggregates(self):
        client=self.client();data=self.overview()['data'];data['observed_at']=NOW;pool=market_pool();pool['marketCap']=None;before=copy.deepcopy(pool)
        with patch.object(bird.time,'time',return_value=NOW):self.assertEqual(client.apply(pool,data),1)
        self.assertEqual(pool['marketCap'],105000);self.assertEqual(pool['liquidity'],before['liquidity']);self.assertEqual(pool['volume'],before['volume']);self.assertEqual(pool['txns'],before['txns'])
        for field,value in [('address','C'*32),('circulatingSupply',None),('lastTradeUnixTime',NOW-121),('price',100),('isScaledUiToken',True)]:
            bad=dict(data);bad[field]=value;p=market_pool();p['marketCap']=None
            with patch.object(bird.time,'time',return_value=NOW):self.assertEqual(client.apply(p,bad),0)
            self.assertIsNone(p['marketCap'])
    def test_read_only_jobs_cannot_spend_outside_production_ledger(self):
        client=self.client();client.transport=Mock()
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':'test','BIRDEYE_NETWORK_ENABLED':'0'}):self.assertIsNone(client.read(MINT))
        client.transport.assert_not_called();self.assertEqual(client.stats['reserved_cu'],0)
    def test_expected_budget_is_not_outage_but_missing_pool_data_remains_degraded(self):
        report={'provider_status':{'birdeye':{'status':'cycle_budget'}},'market_hydration':{'incomplete_after':2}}
        self.assertEqual(di.source_failures(report,{}),{'market_data':'incomplete_mandatory_pool_fields'})
