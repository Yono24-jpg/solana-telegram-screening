import copy
import datetime
import os
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import Mock,patch
import data_intelligence as di
import evidence
import hunter_memory
import social_intelligence
import state_store
import token_extensions
import test_global_v5 as fixtures
from test_upgrade import NOW,MINT,PAIR


class Providers(unittest.TestCase):
    def api(self):return SimpleNamespace(request=Mock(),REQUEST_DEADLINE=None)
    def token(self):return {'id':MINT,'usdPrice':1.05,'circSupply':100000,'mcap':105000,'fdv':999999,
                            'updatedAt':datetime.datetime.fromtimestamp(NOW-30,datetime.timezone.utc).isoformat()}
    def test_jupiter_cap_never_relabels_fdv_or_total_supply(self):
        self.assertEqual(di.cap_proof(self.token(),MINT,fixtures.market_pool(),NOW)['usd'],105000)
        for field in ('id','circSupply','mcap','updatedAt','usdPrice'):
            row=self.token();row[field]=None
            self.assertIsNone(di.cap_proof(row,MINT,fixtures.market_pool(),NOW))
    def test_wrong_price_supply_stale_or_future_cap_rejected(self):
        for field,value in [('circSupply',1),('usdPrice',100),('updatedAt','2000-01-01T00:00:00Z'),('updatedAt','2099-01-01T00:00:00Z')]:
            row=self.token();row[field]=value
            self.assertIsNone(di.cap_proof(row,MINT,fixtures.market_pool(),NOW))
    def test_enrichment_does_not_substitute_aggregate_pool_metrics(self):
        api=self.api();client=di.Client(api,{});row=self.token();row['stats5m']={'numBuys':999999}
        client.tokens_by_mint[MINT]=row;p=fixtures.market_pool();p['marketCap']=None;before=copy.deepcopy(p)
        with patch.object(di.time,'time',return_value=NOW),patch.dict(os.environ,{'BIRDEYE_API_KEY':''}):result=client.enrich([p])
        self.assertEqual(result['cap_recovered'],1);self.assertEqual(p['volume'],before['volume']);self.assertEqual(p['txns'],before['txns'])
    def test_rpc_429_falls_back_without_exposing_secret(self):
        api=self.api();api.request.side_effect=[urllib.error.HTTPError('hidden',429,'rate',{},None),{'result':{'value':'ok'}}]
        client=di.Client(api,{})
        with patch.dict(os.environ,{'HELIUS_API_KEY':'test-secret','SOLANA_RPC_URL':''}):
            self.assertEqual(client.rpc('getAccountInfo',[MINT]),{'value':'ok'})
        self.assertNotIn('test-secret',str(client.status));self.assertEqual(client.status['helius']['status'],'http_429')
    def test_rpc_null_or_error_does_not_become_proof(self):
        api=self.api();api.request.return_value={'result':None};client=di.Client(api,{})
        with patch.dict(os.environ,{'HELIUS_API_KEY':'','SOLANA_RPC_URL':''}),self.assertRaises(di.Unavailable):client.rpc('getTransaction',['signature'])
    def test_transaction_send_is_never_allowed(self):
        api=self.api()
        with self.assertRaises(di.Unavailable):di.Client(api,{}).rpc('sendTransaction',['data'])
        api.request.assert_not_called()
    def test_unapproved_host_and_http_blocked(self):
        for url in ('https://example.org','http://api.jup.ag/tokens/v2/search'):
            with self.assertRaises(di.Unavailable):di.Client(self.api(),{}).request('jupiter',url)
    def test_jupiter_spacing_and_backoff_prevent_retries(self):
        api=self.api();api.request.return_value=[];client=di.Client(api,{})
        with patch.object(di.time,'time',return_value=NOW):
            client.jupiter('/tokens/v2/recent')
            with self.assertRaisesRegex(di.Unavailable,'local_spacing'):client.jupiter('/tokens/v2/recent')
        self.assertEqual(api.request.call_count,1)
    def test_provider_401_is_visible_and_circuit_open(self):
        api=self.api();api.request.side_effect=urllib.error.HTTPError('hidden',401,'auth',{},None);client=di.Client(api,{})
        with patch.object(di.time,'time',return_value=NOW):
            with self.assertRaisesRegex(di.Unavailable,'http_401'):client.jupiter('/tokens/v2/recent')
            with self.assertRaisesRegex(di.Unavailable,'backoff'):client.jupiter('/tokens/v2/recent')
        self.assertEqual(api.request.call_count,1)
    def test_birdeye_unconfigured_does_not_make_authenticated_request(self):
        api=self.api()
        with patch.dict(os.environ,{'BIRDEYE_API_KEY':''}):self.assertIsNone(di.Client(api,{}).birdeye(MINT))
        api.request.assert_not_called()
    def test_rpc_hook_only_attaches_actual_client(self):
        api=self.api();api.request.return_value={'result':{'value':1}};api.DATA_INTELLIGENCE=Mock()
        self.assertEqual(evidence.rpc(api,'getAccountInfo',[]),{'value':1})
    def test_rate_state_survives_restart_and_is_bounded(self):
        state={'provider_state_v5':{'jupiter':{'at':NOW,'retry_after':NOW+120,'requests':1,'day':int(NOW//86400)}}}
        state=state_store.merge({},state,NOW)
        with patch.object(di.time,'time',return_value=NOW),self.assertRaisesRegex(di.Unavailable,'backoff'):
            di.Client(self.api(),state).jupiter('/tokens/v2/recent')


class ResearchTiers(unittest.TestCase):
    def test_internal_watch_never_implies_security_or_delivery(self):
        state={};n={'label':'NebulaFox','reject':None,'sources':[{'url':'https://example.org'}]}
        di.watch(state,fixtures.market_pool(),n,'insider_coverage_unavailable',NOW)
        row=next(iter(state['narrative_watch_v5'].values()))
        self.assertEqual(row['tier'],'NARRATIVE WATCH');self.assertFalse(row['security_verified']);self.assertTrue(row['internal_only'])
    def test_unverified_narrative_not_added(self):
        state={};di.watch(state,fixtures.market_pool(),{'reject':'narrative_unverified'},None,NOW)
        self.assertNotIn('narrative_watch_v5',state)
    def test_verified_tier_requires_explicit_gate_result_and_survives_merge(self):
        state={};di.watch(state,fixtures.market_pool(),{'label':'Fox'},'all_mandatory_gates_passed',NOW,verified=True)
        merged=state_store.merge({},state,NOW);row=next(iter(merged['narrative_watch_v5'].values()))
        self.assertEqual(row['tier'],'VERIFIED ALERT');self.assertFalse(row['internal_only'])
    def test_history_never_loosens_filters_using_future_or_unverified_safety(self):
        state={'memory_v5':{'x':{'at':NOW-300,'decision':'v5_market_cap','safety_complete':True,'samples':{}}}}
        result=di.history_review(state,NOW)
        self.assertFalse(result['filter_change']);self.assertEqual(result['groups']['v5_market_cap']['security_complete_at_first_observation'],0)
    def test_original_rejection_context_not_replaced_with_later_price(self):
        state={};p=fixtures.market_pool();hunter_memory.record(state,p,{},'v5_market_cap',NOW)
        p['marketCap']=999999;hunter_memory.record(state,p,{},'v5_market_cap',NOW+1)
        self.assertEqual(next(iter(state['memory_v5'].values()))['market_cap_at_observation'],150000)
    def test_executable_mint_never_passes_extension_gate(self):
        account=fixtures.account();account['executable']=True
        self.assertEqual(token_extensions.audit(account,MINT)['reject'],'mint_executable_or_unverified')
    def test_x_avatar_url_change_not_image_understanding(self):
        state={};public={'status':'unavailable','posts':[]}
        social={'x':{'status':'observed','user_id':'1','profile_image_url':'https://img/old'}}
        social_intelligence.observe(state,MINT,social,public,{},NOW)
        social['x']['profile_image_url']='https://img/new'
        result=social_intelligence.observe(state,MINT,social,public,{},NOW+300)
        self.assertTrue(result['x_profile_image_url_changed']);self.assertEqual(result['image_contents'],'not_analyzed')
