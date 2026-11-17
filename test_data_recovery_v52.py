"""Production recovery telemetry and young partial-pool regressions."""
import copy
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock,patch
import market_data as market
from test_global_v5 import market_pool
from test_upgrade import NOW,PAIR,MINT


class RecoveryTelemetry(unittest.TestCase):
    def pools(self,count):
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        result=[]
        for i in range(count):
            p=market_pool();p['pairAddress']='A'*30+alphabet[i//58]+alphabet[i%58]
            p['priceChange']['m5']=None;result.append(p)
        return result
    def test_every_batch_row_and_error_remains_visible(self):
        pools=self.pools(41)
        def request(url):
            if '/tokens/v1/' in url:return []
            pairs=url.rsplit('/',1)[-1].split(',')
            if len(pairs)==1:raise urllib.error.HTTPError('https://hidden',429,'rate',{},None)
            return {'pairs':[p for p in pools if p['pairAddress'] in pairs]}
        api=SimpleNamespace(DEX='https://dex.example',request=request)
        gecko=SimpleNamespace(state={},request=Mock(return_value={'data':[]}))
        _,stats=market.hydrate_incomplete(pools,api,gecko,NOW)
        source=stats['sources']['dex_pairs']
        self.assertEqual(source['attempts'],3);self.assertEqual(source['successes'],2)
        self.assertEqual(source['total_rows'],40);self.assertEqual(source['rows'],20)
        self.assertEqual(source['status'],'http_429')
        self.assertEqual(source['status_counts'],{'ok':2,'http_429':1})
        self.assertEqual(stats['attempted_pools'],41)
    def test_expired_deadline_does_not_consume_retry_rotation(self):
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(),REQUEST_DEADLINE=10)
        gecko=SimpleNamespace(state={},request=Mock())
        with patch.object(market.time,'monotonic',return_value=10):
            _,stats=market.hydrate_incomplete(self.pools(41),api,gecko,NOW)
        api.request.assert_not_called();gecko.request.assert_not_called()
        self.assertEqual(gecko.state['provider_state_v5']['hydration']['attempts'],{})
        self.assertEqual(stats['attempted_pools'],0);self.assertTrue(stats['deadline_exhausted'])
    def test_mid_scan_deadline_records_only_attempted_batch(self):
        api=SimpleNamespace(DEX='https://dex.example',REQUEST_DEADLINE=10)
        def request(url):api.REQUEST_DEADLINE=1;return {'pairs':[]}
        api.request=Mock(side_effect=request)
        gecko=SimpleNamespace(state={},request=Mock())
        with patch.object(market.time,'monotonic',return_value=2),patch.object(market.time,'time',return_value=NOW+1):
            _,stats=market.hydrate_incomplete(self.pools(41),api,gecko,NOW)
        self.assertEqual(api.request.call_count,1);gecko.request.assert_not_called()
        attempts=gecko.state['provider_state_v5']['hydration']['attempts']
        self.assertEqual(len(attempts),20);self.assertEqual(set(attempts.values()),{NOW+1})
        self.assertEqual(stats['attempted_pools'],20);self.assertTrue(stats['deadline_exhausted'])


class YoungPartialWatchlist(unittest.TestCase):
    def partial(self):
        p=market_pool();p['pairCreatedAt']=(NOW-600)*1000
        p['liquidity']['usd']=None;p['priceChange']['m5']=None
        return p
    def test_young_missing_liquidity_retained_but_known_weak_pool_rejected(self):
        p=self.partial();state={};market.retain_watchlist(state,[p],NOW)
        self.assertIn(PAIR,state['pool_watchlist'])
        for age,lp,volume in [(3601,None,7000),(600,4999,7000),(600,None,499)]:
            q=copy.deepcopy(p);q['pairCreatedAt']=(NOW-age)*1000
            q['liquidity']['usd']=lp;q['volume']['m5']=volume;fresh={}
            market.retain_watchlist(fresh,[q],NOW)
            self.assertNotIn(PAIR,fresh['pool_watchlist'])
    def test_partial_refresh_improvement_survives_without_fake_completeness(self):
        p=self.partial();state={};market.retain_watchlist(state,[p],NOW)
        improved=copy.deepcopy(p);improved['liquidity']['usd']=30000
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[improved]}))
        gecko=SimpleNamespace(request=Mock(return_value={'data':[]}))
        rows=market.refresh_watchlist([],state,api,gecko,NOW+300)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['liquidity']['usd'],30000)
        self.assertIn('priceChange.m5',market.v3_missing_fields(rows[0]));gecko.request.assert_called_once()
        # A duplicate partial feed does not replace the more complete snapshot.
        self.assertEqual(market.merge_pools(rows+[p])[0]['liquidity']['usd'],30000)


if __name__=='__main__':unittest.main()
