"""Regression for real hydration outages, denied search and evaluator starvation."""
import copy
import datetime
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock,patch
import market_data as market
import hunter_memory
import social_intelligence as social
import security_v3 as security
import evidence
from test_upgrade import NOW,MINT,PAIR
from test_global_v5 import market_pool
import test_narrative_v3 as fixtures


class Hydration(unittest.TestCase):
    def setup_api(self,p):
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[]}))
        gecko=SimpleNamespace(request=Mock(return_value={'data':[]}))
        return api,gecko
    def test_token_endpoint_array_recovers_same_pool_and_ca(self):
        p=market_pool();p['marketCap']=None;api,g=self.setup_api(p)
        api.request.side_effect=lambda url: [market_pool()] if '/tokens/v1/' in url else {'pairs':[]}
        rows,stats=market.hydrate_incomplete([p],api,g,NOW)
        self.assertEqual(stats['recovered'],1);self.assertEqual(stats['missing_before'],{'marketCap':1})
        self.assertEqual(stats['sources']['dex_tokens']['status'],'ok')
    def test_wrong_pool_same_ca_cannot_repair(self):
        p=market_pool();p['marketCap']=None;api,g=self.setup_api(p);bad=market_pool();bad['pairAddress']='C'*32
        api.request.side_effect=lambda url: [bad] if '/tokens/v1/' in url else {'pairs':[]}
        rows,stats=market.hydrate_incomplete([p],api,g,NOW)
        self.assertEqual(stats['recovered'],0);self.assertEqual(stats['identity_rejections'],1)
    def test_denied_provider_and_null_cap_are_reported_not_safe(self):
        p=market_pool();p['marketCap']=None;api,g=self.setup_api(p)
        api.request.side_effect=urllib.error.HTTPError('https://internal',429,'limit',{},None)
        rows,stats=market.hydrate_incomplete([p],api,g,NOW)
        self.assertEqual(stats['sources']['dex_pairs']['status'],'http_429')
        self.assertEqual(stats['missing_after'],{'marketCap':1});self.assertEqual(stats['recovered'],0)
        self.assertNotIn('internal',str(stats))
    def cap(self):
        return {'platforms':{'solana':MINT},'last_updated':datetime.datetime.fromtimestamp(NOW-30,datetime.timezone.utc).isoformat(),
                'market_data':{'market_cap':{'usd':105000},'current_price':{'usd':1.05},'circulating_supply':100000}}
    def test_cap_requires_exact_ca_circulating_supply_price_and_recent_time(self):
        self.assertEqual(market.verified_cap(self.cap(),MINT,market_pool(),NOW)['usd'],105000)
        for kind in ('mint','supply','fdv','time','price'):
            data=self.cap()
            if kind=='mint':data['platforms']['solana']='C'*32
            if kind=='supply':data['market_data']['circulating_supply']=None
            if kind=='fdv':data['market_data']['fully_diluted_valuation']={'usd':105000};data['market_data']['market_cap']={}
            if kind=='time':data['last_updated']='2000-01-01T00:00:00Z'
            if kind=='price':data['market_data']['current_price']['usd']=2
            self.assertIsNone(market.verified_cap(data,MINT,market_pool(),NOW))
    def test_cap_enrichment_does_not_mix_pool_metrics(self):
        p=market_pool();p['marketCap']=None;api,g=self.setup_api(p)
        api.request.side_effect=lambda u:self.cap() if 'coingecko.com' in u else ([] if '/tokens/v1/' in u else {'pairs':[]})
        rows,stats=market.hydrate_incomplete([p],api,g,NOW)
        self.assertEqual(stats['recovered'],1);self.assertEqual(rows[0]['volume'],p['volume'])
        self.assertEqual(rows[0]['marketCapEvidence']['mint'],MINT)
    def test_conflict_cannot_be_erased_by_better_snapshot(self):
        p=market_pool();p['marketCap']=None;p['identityConflict']=True
        self.assertTrue(market.select_pool(p,market_pool())['identityConflict'])
        p=market_pool();q=market_pool();p['quoteToken']={'address':'C'*32};q['quoteToken']={'address':'D'*32}
        self.assertTrue(market.select_pool(p,q)['identityConflict'])


class PublicSocial(unittest.TestCase):
    def test_denied_search_uses_official_actor_feeds_and_labels_scope(self):
        did='did:plc:'+'a'*24
        post={'uri':'at://'+did+'/app.bsky.feed.post/one','record':{'text':'NebulaFox '+MINT,'createdAt':datetime.datetime.fromtimestamp(NOW-30,datetime.timezone.utc).isoformat()},
              'author':{'did':did},'likeCount':3,'replyCount':1,'repostCount':2}
        def read(url,api):
            if 'searchPosts' in url:raise urllib.error.HTTPError(url,403,'denied',{},None)
            if 'searchActors' in url:return {'actors':[{'did':did}]}
            return {'feed':[{'post':post}]}
        with patch.object(evidence,'public_read',side_effect=read):result=social.sample(Mock(),'NebulaFox',MINT,NOW)
        self.assertEqual(result['status'],'observed');self.assertEqual(result['contract_mentions'],1)
        self.assertEqual(result['search_status'],'authentication_required_or_forbidden');self.assertIn('selection biased',result['scope'])
        self.assertEqual(result['organic_status'],'unknown')
    def test_no_author_access_remains_unavailable(self):
        with patch.object(evidence,'public_read',side_effect=TimeoutError()):self.assertEqual(social.sample(Mock(),'x',MINT,NOW)['status'],'unavailable')
    def test_changed_sampling_scope_does_not_become_growth(self):
        state={'social_v5':{MINT:{'at':NOW-300,'recent_count':1,'public_status':'observed','scope':'search'}}}
        result=social.observe(state,MINT,{}, {'status':'observed','scope':'feeds','posts':[]}, {},NOW)
        self.assertIsNone(result['mention_acceleration'])


class Evaluations(unittest.TestCase):
    def test_short_expiring_window_precedes_day_backlog(self):
        records={str(i):{'at':NOW-86400,'mint':MINT,'pair':str(i+1)*32,'price':1,'samples':{}} for i in range(65)}
        records['urgent']={'at':NOW-800,'mint':MINT,'pair':PAIR,'price':1,'samples':{}}
        api=Mock();api.DEX='https://dex.example';api.request.return_value={'pairs':[market_pool()]}
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=1):
            result=hunter_memory.followup({'memory_v5':records},[],api,None,10)
        self.assertEqual(records['urgent']['samples']['300']['status'],'observed')
        self.assertIn(PAIR,api.request.call_args_list[0].args[0]);self.assertLessEqual(result['quote_attempts'],60)
    def test_duplicate_cohorts_get_one_quote_all_updated(self):
        records={str(i):{'at':NOW-300-i,'mint':MINT,'pair':PAIR,'price':1,'samples':{}} for i in range(2)}
        api=Mock();api.DEX='https://dex.example';api.request.return_value={'pairs':[market_pool()]}
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=1):
            result=hunter_memory.followup({'memory_v5':records},[],api,None,10)
        self.assertEqual(result['quote_attempts'],1);self.assertTrue(all('300' in r['samples'] for r in records.values()))


class Funding(unittest.TestCase):
    def run_graph(self,source=None,missing=False):
        buyers,txs=fixtures.Security().sample()
        def rpc(api,method,args):
            if missing:return None
            if method=='getSignaturesForAddress':
                sig=next(k for k,v in txs.items() if v['transaction']['message']['accountKeys'][0]['pubkey']==args[0])
                return [{'signature':sig,'blockTime':NOW-10,'err':None}]
            tx=copy.deepcopy(txs[args[0]])
            if source:
                wallet=tx['transaction']['message']['accountKeys'][0]['pubkey']
                tx['transaction']['message']['accountKeys'].append({'pubkey':source,'signer':True})
                tx['transaction']['message']['instructions'].append({'programId':'1'*32,'parsed':{'type':'transfer','info':{'source':source,'destination':wallet,'lamports':100}}})
            return tx
        with patch.object(evidence,'rpc',side_effect=rpc):return security.funding_check(fixtures.report(),buyers,Mock(),NOW)
    def test_shared_funder_rejected(self):self.assertEqual(self.run_graph('Z'*32)['reject'],'shared_direct_funder_pattern')
    def test_developer_link_rejected(self):self.assertEqual(self.run_graph(fixtures.report()['creator'])['reject'],'developer_linked_buyer')
    def test_partial_graph_not_claimed_complete(self):self.assertFalse(self.run_graph()['complete_graph'])
    def test_unknown_rpc_rejects(self):
        with self.assertRaises(security.EvidenceMissing):self.run_graph(missing=True)
