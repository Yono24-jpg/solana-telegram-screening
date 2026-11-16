import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import data_intelligence as di
import global_intelligence as intel
import market_data as market
import scanner_v2
import scanner_v5
import security_v3 as security
import evidence
import state_store
import test_narrative_v3 as fixture
from test_global_v5 import market_pool,articles
from test_upgrade import MINT,NOW,PAIR


class Snapshots(unittest.TestCase):
    def proof(self):return {'provider':'jupiter_tokens_v2','mint':MINT,'usd':105000,'price_usd':1.05,'circulating_supply':100000,'updated_at':NOW-10,'observed_at':NOW-5}
    def candidates(self):
        a=market_pool();a['marketCap']=105000;a['marketCapEvidence']=self.proof();a['priceChange']['m5']=None
        b=market_pool();b['marketCap']=None;b['dataSource']='geckoterminal';b['volume']['m5']=2222
        return a,b
    def test_valid_cap_survives_snapshot_selection_without_pool_metric_blending(self):
        a,b=self.candidates()
        with patch.object(market.time,'time',return_value=NOW):r=market.select_pool(a,b)
        self.assertEqual(r['marketCap'],105000);self.assertEqual(r['volume']['m5'],2222)
        self.assertEqual(r['dataSource'],'geckoterminal');self.assertFalse(market.v3_missing_fields(r))
    def test_stale_wrong_mint_supply_price_or_future_proof_never_fills(self):
        for field,value in [('mint','C'*32),('updated_at',NOW-121),('observed_at',NOW+1),('circulating_supply',1),('price_usd',100)]:
            a,b=self.candidates();a['marketCapEvidence'][field]=value
            with patch.object(market.time,'time',return_value=NOW):r=market.select_pool(a,b)
            self.assertTrue(market.v3_missing_fields(r))
    def test_valuation_conflict_is_sticky_through_every_snapshot(self):
        a,b=self.candidates();a['valuationConflict']=True
        with patch.object(market.time,'time',return_value=NOW):r=market.select_pool(a,b)
        self.assertTrue(r['valuationConflict'])
    def test_retry_rotation_survives_state_merge(self):
        a=market_pool();a['marketCap']=None;b=copy.deepcopy(a);b['pairAddress']='C'*32
        state={};api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[]}))
        gecko=SimpleNamespace(state=state,request=Mock(return_value={'data':[]}))
        with patch.object(market.time,'time',return_value=NOW):market.hydrate_incomplete([a,b],api,gecko,NOW,limit=1)
        merged=state_store.merge({},state,NOW);gecko.state=merged
        with patch.object(market.time,'time',return_value=NOW+300):market.hydrate_incomplete([a,b],api,gecko,NOW+300,limit=1)
        self.assertEqual(set(gecko.state['provider_state_v5']['hydration']['attempts']),{PAIR,'C'*32})


class FreePolicy(unittest.TestCase):
    def test_priority_news_covers_game_ai_anime_even_during_another_rotation(self):
        with patch.object(evidence,'public_read',side_effect=TimeoutError()),patch.dict(os.environ,{'ACTIONS_ID_TOKEN_REQUEST_TOKEN':''}):f=intel.collect(SimpleNamespace(),{},NOW)
        for name in ('US:games','US:ai','US:screen'):self.assertIn(name,f['sources'])
        self.assertEqual(f['trends'],[])
    def test_newest_pool_page_is_requested_before_promotional_and_trending_feeds(self):
        calls=[]
        def read(url):calls.append(url);return {'data':[]} if 'geckoterminal' in url else []
        api=SimpleNamespace(DEX='https://dex.example',request=read)
        scanner_v2.discover(api,SimpleNamespace(request=read))
        self.assertIn('/new_pools?page=1',calls[0])
    def test_x_saved_key_and_enabled_variable_cannot_enable_paid_reads_in_v51(self):
        state={'enabled':False}
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'test-secret','X_READS_ENABLED':'1'}),patch.object(scanner_v5,'write_report'):
            result=scanner_v5.run(state,None,SimpleNamespace(),dry_run=True)
            self.assertFalse(result['capabilities']['x_reads_enabled']);self.assertEqual(os.environ['X_READS_ENABLED'],'0')
            with patch.object(evidence,'public_read') as read:evidence.x_analysis('handle',MINT,SimpleNamespace(),NOW)
            read.assert_not_called()
    def test_birdeye_skips_multi_missing_pools_and_prefers_cap_only_snapshot(self):
        parent=di.Client(SimpleNamespace(REQUEST_DEADLINE=None),{});a=market_pool();a['marketCap']=None;a['priceChange']['m5']=None
        b=market_pool();b['marketCap']=None;b['baseToken']['address']='C'*32
        with patch.object(parent.bird,'read',return_value=None) as read:parent.bird.enrich([a,b])
        self.assertEqual({call.args[0] for call in read.call_args_list},{'C'*32})


class WalletSecurity(unittest.TestCase):
    def test_one_creator_cosigner_anywhere_in_verified_sample_rejects(self):
        buyers,txs=fixture.Security().sample();creator=fixture.CREATOR
        txs[buyers['transactions'][-1]['signature']]['transaction']['message']['accountKeys'].append({'pubkey':creator,'signer':True})
        with patch.object(evidence,'rpc',side_effect=lambda a,m,p:txs[p[0]]):r=security.transaction_sample(fixture.pool(),buyers,None,NOW,creator=creator)
        self.assertEqual(r['reject'],'creator_cosigned_sample_trade')
    def test_three_verified_roundtrip_wallets_reject(self):
        buyers,txs=fixture.Security().sample()
        for sell,buy in zip(buyers['transactions'][:3],buyers['transactions'][3:6]):
            old=sell['wallet'];new=buy['wallet'];sell['wallet']=new;tx=txs[sell['signature']]
            tx['transaction']['message']['accountKeys'][0]['pubkey']=new
            for name in ('preTokenBalances','postTokenBalances'):tx['meta'][name][0]['owner']=new
        with patch.object(evidence,'rpc',side_effect=lambda a,m,p:txs[p[0]]):r=security.transaction_sample(fixture.pool(),buyers,None,NOW)
        self.assertEqual(r['reject'],'repeated_roundtrip_wallet_pattern')
