import copy
import unittest
from unittest.mock import patch
import bot
from signal_quality import assess, observe, snapshot, merge_observations, MAX_PAIRS, MAX_SNAPSHOTS

class Quality(unittest.TestCase):
    def setUp(self):
        self.now=2000
        self.pool={'chainId':'solana','pairAddress':'pair','pairCreatedAt':1000000,
                   'baseToken':{'address':'mint','symbol':'A<&'},'priceUsd':'1.05',
                   'liquidity':{'usd':20000},'volume':{'m5':2500},'marketCap':100000,
                   'txns':{'m5':{'buys':25,'sells':10}},'priceChange':{'m5':3,'h1':12}}
        baseline=copy.deepcopy(self.pool)
        baseline['priceUsd']='1'
        baseline['volume']['m5']=1500
        self.history={'pair':[snapshot(baseline,1700)]}
    def test_growth_is_transparent_and_bounded(self):
        reason,detail=assess(self.pool,self.history,self.now)
        self.assertIsNone(reason)
        self.assertGreaterEqual(detail['score'],70)
        self.assertLessEqual(detail['score'],100)
        self.assertAlmostEqual(detail['price_change'],5)
        self.assertAlmostEqual(detail['volume_growth'],2500/1500)
        self.assertEqual(detail['comparison_minutes'],5)
    def test_cold_start_and_overlapping_windows_are_silent(self):
        self.assertEqual(assess(self.pool,{},self.now)[0],'awaiting_comparison')
        for age in (299,901,-1):
            history=copy.deepcopy(self.history)
            history['pair'][0]['t']=self.now-age
            self.assertEqual(assess(self.pool,history,self.now)[0],'awaiting_comparison')
    def test_reject_deterioration_and_late_entry(self):
        cases=[('late_price_surge',lambda p:p['priceChange'].update(m5=15.01)),
               ('late_price_surge',lambda p:p['priceChange'].update(h1=60.01)),
               ('weak_price_momentum',lambda p:p['priceChange'].update(m5=-0.1)),
               ('price_ran_ahead',lambda p:p.update(priceUsd='1.16')),
               ('price_falling_since_comparison',lambda p:p.update(priceUsd='0.94')),
               ('liquidity_withdrawal',lambda p:p['liquidity'].update(usd=17999)),
               ('insufficient_sell_activity',lambda p:p['txns']['m5'].update(sells=2)),
               ('volume_not_growing',lambda p:p['volume'].update(m5=1649)),
               ('buy_activity_fading',lambda p:p['txns']['m5'].update(buys=24))]
        for expected,change in cases:
            with self.subTest(reason=expected):
                p=copy.deepcopy(self.pool);change(p)
                self.assertEqual(assess(p,self.history,self.now)[0],expected)
    def test_missing_or_invalid_values_never_make_signal(self):
        for value in ('nan','inf',None,True,0,-1):
            p=copy.deepcopy(self.pool);p['priceUsd']=value
            self.assertEqual(assess(p,self.history,self.now)[0],'missing_quality_metrics')
        p=copy.deepcopy(self.pool);del p['priceChange']['h1']
        self.assertEqual(assess(p,self.history,self.now)[0],'missing_quality_metrics')
        history=copy.deepcopy(self.history);history['pair'][0]['mint']='other-mint'
        self.assertEqual(assess(self.pool,history,self.now)[0],'awaiting_comparison')
    def test_observation_merge_survives_restart_and_is_bounded(self):
        state={'observations':self.history}
        observe(state,[self.pool,None],self.now)
        restored=merge_observations(self.history,state['observations'],now=self.now)
        self.assertEqual(len(restored['pair']),2)
        self.assertIsNone(assess(self.pool,restored,self.now)[0])
        self.assertEqual(merge_observations(restored,restored,now=self.now),restored)
        self.assertEqual(merge_observations(restored,now=self.now+1801),{})
        oversized={str(i):[dict(self.history['pair'][0],t=self.now-j) for j in range(30)] for i in range(300)}
        bounded=merge_observations(oversized,now=self.now)
        self.assertEqual(len(bounded),MAX_PAIRS)
        self.assertTrue(all(len(rows)==MAX_SNAPSHOTS for rows in bounded.values()))
    def test_nearby_observations_do_not_evict_baseline(self):
        state={'observations':self.history}
        observe(state,[self.pool],self.now)
        observe(state,[self.pool],self.now+10)
        self.assertEqual(len(state['observations']['pair']),2)
        self.assertIsNone(assess(self.pool,state['observations'],self.now+10)[0])
    def test_scan_cold_start_persists_history_without_alert_or_rpc(self):
        state={'sent':{}}
        with patch.object(bot,'discover',return_value=[self.pool]),patch.object(bot.time,'time',return_value=self.now),patch.object(bot,'save') as save,patch.object(bot,'request') as rpc,patch.object(bot,'tg') as telegram:
            bot.scan(state,'chat')
        save.assert_called_once()
        rpc.assert_not_called();telegram.assert_not_called()
        self.assertIn('pair',state['observations'])
    def test_watchlist_keeps_pool_after_discovery_feed_drops_it(self):
        with patch.object(bot,'request',return_value={'pairs':[self.pool]}) as request:
            pools=bot.refresh_watchlist([],{'observations':self.history},self.now)
        self.assertEqual(pools,[self.pool])
        self.assertIn('/solana/pair',request.call_args.args[0])
        with patch.object(bot,'request') as request:
            self.assertEqual(bot.refresh_watchlist([self.pool],{'observations':self.history},self.now),[self.pool])
        request.assert_not_called()
    def test_expired_pool_does_not_renew_observations(self):
        state={}
        p=copy.deepcopy(self.pool);p['pairCreatedAt']=(self.now-18001)*1000
        observe(state,[p],self.now)
        self.assertEqual(state['observations'],{})
    def test_scan_refresh_deterioration_cannot_send_alert(self):
        state={'sent':{},'observations':self.history}
        refreshed=copy.deepcopy(self.pool)
        refreshed['priceChange']['m5']=30
        def request(url,data=None):
            if data: return {'result':{'value':[{}]}}
            if '/latest/dex/pairs/' in url: return {'pairs':[refreshed]}
            return {'risks':[],'score_normalised':20}
        with patch.object(bot,'discover',return_value=[self.pool]),patch.object(bot.time,'time',return_value=self.now),patch.object(bot,'save'),patch.object(bot,'request',side_effect=request),patch.object(bot,'security_reason',return_value=None),patch.object(bot,'holder_concentration',return_value=20),patch.object(bot,'tg') as telegram:
            bot.scan(state,'chat')
        telegram.assert_not_called()
    def test_full_verified_alert_contains_reasons_and_records_delivery(self):
        state={'sent':{},'observations':self.history}
        def request(url,data=None):
            if data: return {'result':{'value':[{}]}}
            if '/latest/dex/pairs/' in url: return {'pairs':[self.pool]}
            return {'risks':[],'score_normalised':20}
        with patch.object(bot,'discover',return_value=[self.pool]),patch.object(bot.time,'time',return_value=self.now),patch.object(bot,'save'),patch.object(bot,'request',side_effect=request),patch.object(bot,'security_reason',return_value=None),patch.object(bot,'holder_concentration',return_value=20),patch.object(bot,'tg',return_value={'message_id':123}) as telegram:
            bot.scan(state,'chat')
        telegram.assert_called_once()
        text=telegram.call_args.kwargs['text']
        for fragment in ('Skor filter','ALASAN LOLOS','1.67×','A&lt;&amp;','axiom.trade','bukan probabilitas'):
            self.assertIn(fragment,text)
        self.assertEqual(state['sent'],{'mint':self.now})

if __name__=='__main__': unittest.main()
