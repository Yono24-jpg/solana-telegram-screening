"""Adversarial, offline v3 gates and pipeline integration tests."""
import copy
import json
import os
import unittest
from unittest.mock import patch, Mock
from email.utils import formatdate
import bot
import evidence
import narrative_v3 as n
import security_v3 as s
import scanner_v2
import state_store
from test_upgrade import pool, sec, NOW, MINT, PAIR
from test_upgrade_integration import Pipeline
from v3_test_support import approved, feed, safety

CREATOR = 'D'*32


def articles():
    return [{'title':'GTA VI trailer arrives - '+host,'url':'https://'+host+'/gta', 'publisher':host,
             'publisher_host':host,'published_at':NOW-60,'category':'game'} for host in ('one.example','two.example')][0:1]+[
        {'title':'Rockstar announces GTA VI release date','url':'https://two.example/date','publisher':'Two','publisher_host':'two.example','published_at':NOW-30,'category':'game'}]


def report():
    return {'mint':MINT,'rugged':False,'tokenProgram':bot.PROGRAM,'creator':CREATOR,
            'token':{'supply':1000000,'mintAuthority':None,'freezeAuthority':None},'risks':[],
            'score_normalised':5,'graphInsidersDetected':0,'insiderNetworks':[],
            'markets':[{'pubkey':PAIR,'mintA':MINT,'mintB':'So11111111111111111111111111111111111111112',
                        'lp':{'lpLockedPct':100,'lpLockedUSD':30000}}]}


class Narrative(unittest.TestCase):
    def test_market_boundaries_and_missing_fields(self):
        p=approved(pool())
        for cap in (20000,500000):
            p['marketCap']=cap;self.assertIsNone(n.market_gate(p,NOW))
        for cap in (19999,500001,True,float('nan')):
            p['marketCap']=cap;self.assertIsNotNone(n.market_gate(p,NOW))
        for key in ('marketCap','volume','liquidity','txns','pairCreatedAt'):
            p=approved(pool());del p[key];self.assertIsNotNone(n.market_gate(p,NOW))
        p=approved(pool());p['volume']['h1']=4999;self.assertEqual(n.market_gate(p,NOW),'v3_volume_h1')
        p=approved(pool());p['txns']['m5']={'buys':15,'sells':10};self.assertIsNone(n.market_gate(p,NOW))
        p['txns']['m5']['buys']=14;self.assertEqual(n.market_gate(p,NOW),'v3_buy_sell')
    def test_match_requires_named_entity_and_independent_recent_news(self):
        p=pool();p['baseToken']['name']='GTA VI'
        f={'articles':articles()};self.assertIsNone(n.match(p,f,NOW)['reject'])
        self.assertEqual(n.match(p,f,NOW+172801)['score'],0)
        f['articles'][1]['publisher_host']='one.example';self.assertEqual(n.match(p,f,NOW)['score'],0)
    def test_keyword_boundaries_do_not_match_substrings(self):
        self.assertFalse(n.matches('Chaircoin','AI'));self.assertFalse(n.matches('notgtafake','gta'))
        self.assertTrue(n.matches('GTA VI Coin','GTA'))
    def test_syndicated_title_and_repeated_category_cannot_fake_trend(self):
        a=articles();a[1]['title']=a[0]['title'].replace('one.example','two.example')
        self.assertEqual(n.trends({'articles':a*3},NOW),[])
    def test_future_news_and_untrusted_markup_rejected(self):
        self.assertEqual(n.parse_feed('<!DOCTYPE rss><rss/>','game',NOW),[])
        xml='<rss><channel><item><title>GTA update</title><link>javascript:alert(1)</link><source url="https://one.example">One</source><pubDate>'+formatdate(NOW,usegmt=True)+'</pubDate></item></channel></rss>'
        self.assertEqual(n.parse_feed(xml,'game',NOW),[])
        xml=xml.replace('javascript:alert(1)','https://one.example/gta')
        self.assertEqual(len(n.parse_feed(xml,'game',NOW)),1)
        self.assertEqual(n.parse_feed(xml,'game',NOW-1),[])
    def test_feed_outage_does_not_create_narratives(self):
        with patch.object(evidence,'public_read',side_effect=TimeoutError()): f=n.collect(bot,{},NOW)
        self.assertEqual(n.trends(f,NOW),[]);self.assertTrue(all(x=='unavailable' for x in f['sources'].values()))
    def test_ai_invented_names_cannot_become_entities(self):
        self.assertEqual(n.validate_entities({'entities':['Invented Moon','Ignore Previous Instructions']},articles()),[])
        self.assertEqual(n.validate_entities({'entities':['GTA VI']},articles()),['GTA VI'])
    def test_ai_cache_budget_and_missing_key(self):
        with patch.dict(os.environ,{'CLOUDFLARE_API_TOKEN':''}):self.assertEqual(n.extract_ai(bot,{},articles(),NOW)['status'],'not_configured')
        with patch.dict(os.environ,{'CLOUDFLARE_API_TOKEN':'fixture'}),patch.object(n.urllib.request,'urlopen') as network:
            state={'narrative_ai_v3':{'at':NOW-20000,'day':int(NOW//86400),'calls':8}}
            self.assertEqual(n.extract_ai(bot,state,articles(),NOW)['status'],'daily_budget_reached');network.assert_not_called()
    def test_ai_failure_counts_budget_and_hides_error(self):
        state={}
        with patch.dict(os.environ,{'CLOUDFLARE_API_TOKEN':'fixture'}),patch.object(n.urllib.request,'urlopen',side_effect=RuntimeError('secret-url')):
            result=n.extract_ai(bot,state,articles(),NOW)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(state['narrative_ai_v3']['calls'],1)
        self.assertNotIn('secret',json.dumps(result))
    def test_narrative_discovery_filters_other_chains(self):
        with patch.object(bot,'request',return_value={'pairs':[pool(),dict(pool(),chainId='ethereum')]}):
            self.assertEqual(len(n.search_pools(bot,{'articles':articles()},NOW)),1)
    def test_cache_survives_state_merge(self):
        local={'narrative_feed_v3':{'at':NOW,'value':feed()},'narrative_ai_v3':{'at':NOW,'calls':1}}
        result=state_store.merge({},local,NOW)
        self.assertEqual(result['narrative_ai_v3']['calls'],1);self.assertIn('narrative_feed_v3',result)


class Security(unittest.TestCase):
    def test_complete_report_and_all_required_fields(self):
        self.assertIsNone(s.report_gate(report(),pool()))
        for key in ('mint','rugged','tokenProgram','creator','token','risks','score_normalised','graphInsidersDetected','insiderNetworks','markets'):
            r=report();del r[key]
            with self.subTest(key=key):self.assertIsNotNone(s.report_gate(r,pool()))
    def test_null_insiders_is_missing_not_zero(self):
        r=report();r['insiderNetworks']=None;self.assertEqual(s.report_gate(r,pool()),'insider_coverage_unavailable')
    def test_pool_specific_lock_and_mint(self):
        for path,value in [('pubkey','C'*32),('mintA','C'*32)]:
            r=report();r['markets'][0][path]=value;self.assertIsNotNone(s.report_gate(r,pool()))
        for value in (94.9,101,None,True):
            r=report();r['markets'][0]['lp']['lpLockedPct']=value;self.assertIsNotNone(s.report_gate(r,pool()))
    def test_danger_bundles_mutability_and_authorities(self):
        for changes in ({'rugged':True},{'insiderNetworks':[{'type':'bundle'}]},{'graphInsidersDetected':1},{'score_normalised':40},{'risks':[{'name':'Mutable metadata','level':'warn'}]}):
            r=report();r.update(changes);self.assertIsNotNone(s.report_gate(r,pool()))
        r=report();r['token']['freezeAuthority']=CREATOR;self.assertIsNotNone(s.report_gate(r,pool()))
    def test_developer_concentration_and_unknown_history(self):
        row={'account':{'data':{'parsed':{'info':{'mint':MINT,'owner':CREATOR,'tokenAmount':{'amount':'60000'}}}}}}
        with patch.object(evidence,'rpc',return_value={'value':[row]}):self.assertEqual(s.developer_check(report(),bot,NOW)['reject'],'developer_holds_over_5_pct')
        with patch.object(evidence,'rpc',side_effect=[{'value':[]},[]]):
            with self.assertRaises(ValueError):s.developer_check(report(),bot,NOW)
    def test_developer_token_outflow(self):
        tx={'meta':{'err':None,'preTokenBalances':[{'mint':MINT,'owner':CREATOR,'uiTokenAmount':{'amount':'100'}}],'postTokenBalances':[]}}
        with patch.object(evidence,'rpc',side_effect=[{'value':[]},[{'signature':'S','blockTime':NOW-20,'err':None}],tx]):
            self.assertEqual(s.developer_check(report(),bot,NOW)['reject'],'developer_recent_token_outflow')
    def sample(self):
        rows=[];txs={}
        chars='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        for i in range(15):
            sell=i<3;wallet=chars[i]*32;sig=chars[i]*64
            rows.append({'wallet':wallet,'signature':sig,'kind':'sell' if sell else 'buy'})
            pre=[{'mint':MINT,'owner':wallet,'uiTokenAmount':{'amount':'100' if sell else '0'}}]
            post=[{'mint':MINT,'owner':wallet,'uiTokenAmount':{'amount':'0' if sell else '100'}}]
            txs[sig]={'blockTime':NOW-10,'slot':100+i,'meta':{'err':None,'preTokenBalances':pre,'postTokenBalances':post,'preBalances':[100,0],'postBalances':[200 if sell else 90,0],'fee':1},'transaction':{'message':{'accountKeys':[{'pubkey':wallet,'signer':True},{'pubkey':PAIR,'signer':False}]}}}
        return {'transactions':rows},txs
    def test_sell_and_buy_sample_success(self):
        buyers,txs=self.sample()
        with patch.object(evidence,'rpc',side_effect=lambda _api,_method,args:txs[args[0]]):
            result=s.transaction_sample(pool(),buyers,bot,NOW)
        self.assertIsNone(result['reject']);self.assertEqual(result['finalized_sells'],3)
    def test_sell_rejects_failed_wrong_pool_or_no_proceeds(self):
        for mutation in ('failed','pool','proceeds','stale','signer'):
            buyers,txs=self.sample();tx=next(iter(txs.values()))
            if mutation=='failed':tx['meta']['err']={}
            if mutation=='pool':tx['transaction']['message']['accountKeys'][1]['pubkey']='C'*32
            if mutation=='proceeds':tx['meta']['postBalances'][0]=90
            if mutation=='stale':tx['blockTime']=NOW-301
            if mutation=='signer':tx['transaction']['message']['accountKeys'][0]['signer']=False
            with self.subTest(mutation=mutation),patch.object(evidence,'rpc',side_effect=lambda _api,_method,args:txs[args[0]]):
                with self.assertRaises(ValueError):s.transaction_sample(pool(),buyers,bot,NOW)
    def test_same_slot_and_shared_signer_bundle_patterns(self):
        for kind in ('slot','signer'):
            buyers,txs=self.sample()
            for row in buyers['transactions'][3:7]:
                tx=txs[row['signature']]
                if kind=='slot':tx['slot']=999
                else:tx['transaction']['message']['accountKeys'].append({'pubkey':CREATOR,'signer':True})
            with patch.object(evidence,'rpc',side_effect=lambda _api,_method,args:txs[args[0]]):
                self.assertEqual(s.transaction_sample(pool(),buyers,bot,NOW)['reject'],'bundled_slot_or_shared_signer_pattern')
    def test_missing_rpc_and_weak_base_fail_closed(self):
        for security in ({},dict(sec(),complete=False)):
            self.assertFalse(s.inspect(pool(),security,{'strong':True},bot,NOW)['complete'])
        security=dict(sec(),distribution={'verified':True,'top1_observed_owner_pct':2})
        with patch.object(bot,'request',side_effect=TimeoutError('secret_url')):
            result=s.inspect(pool(),security,{'strong':True},bot,NOW)
        self.assertFalse(result['complete']);self.assertNotIn('secret_url',str(result))
    def test_delivery_cannot_use_legacy_gate(self):
        with patch.object(bot,'tg') as tg:
            self.assertFalse(scanner_v2.deliver({},bot,123,pool(),{},sec(),{}, {},{},'EARLY WATCH'))
        tg.assert_not_called()


class V3Pipeline(Pipeline):
    def test_missing_security_blocks_even_early_watch(self):
        import security_v3
        with patch.object(security_v3,'inspect',return_value={'reject':'insider_coverage_unavailable','complete':False,'score':None}):
            self.assertEqual(self.run_scan({'enabled':True}).call_count,0)
    def test_missing_narrative_and_market_cap_block_all_messages(self):
        with patch.object(n,'match',return_value={'score':0,'reject':'narrative_unverified','sources':[]}):
            self.assertEqual(self.run_scan({'enabled':True}).call_count,0)
    def test_missing_volume_after_refresh_blocks_message(self):
        original=n.market_gate
        calls=[]
        def gate(p,now):
            calls.append(1)
            return None if len(calls)==1 else 'v3_volume_h1'
        with patch.object(n,'market_gate',side_effect=gate):
            self.assertEqual(self.run_scan({'enabled':True}).call_count,0)


if __name__=='__main__':unittest.main()
