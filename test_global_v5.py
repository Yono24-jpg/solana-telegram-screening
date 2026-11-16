"""Adversarial offline v5 tests. Every Telegram call is mocked."""
import base64
import copy
import io
import json
import os
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock,patch
from email.utils import formatdate
import bot
import evidence
import global_intelligence as intel
import hunter_memory
import hunter_modes
import scanner_v5
import security_v3
import social_intelligence
import state_store
import token_extensions as ext
import vault_checks
from test_upgrade import pool,NOW,MINT,PAIR
from test_narrative_v3 import report as risk_report
from signal_quality import snapshot


def articles(label='NebulaFox'):
    return [{'title':label+' '+suffix,'url':'https://'+host+'/news','publisher':host,'publisher_host':host,
             'published_at':NOW-60,'observed_at':NOW-30,'category':'emergent','region':'US'}
            for host,suffix in [('one.example','new game arrives'),('two.example','surprises fans worldwide')]]


def market_pool(age=600):
    p=pool();p['baseToken']['name']='NebulaFox';p['baseToken']['symbol']='NFOX'
    p['pairCreatedAt']=(NOW-age)*1000;p['volume']['h1']=10000;p['priceChange']['h24']=20
    return p


def account(entries=None,owner=ext.TOKEN2022):
    raw=bytearray(82);raw[45]=1;raw[36:44]=struct.pack('<Q',1000000)
    if entries is not None:
        raw+=bytes(83)+b'\x01'
        for kind,data in entries: raw+=struct.pack('<HH',kind,len(data))+data
    return {'owner':owner,'executable':False,'data':[base64.b64encode(raw).decode(),'base64']}


class Extensions(unittest.TestCase):
    def test_classic_and_extension_free(self):
        for owner in (ext.CLASSIC,ext.TOKEN2022): self.assertTrue(ext.audit(account(owner=owner),MINT)['complete'])
    def test_every_unsupported_extension_and_unknown_rejected(self):
        for kind in list(range(1,28))+[28,100,65535]:
            if kind in (18,19):continue
            with self.subTest(kind=kind): self.assertFalse(ext.audit(account([(kind,b'')]),MINT)['complete'])
    def test_immutable_self_pointed_metadata(self):
        mint=vault_checks.b58encode(bytes(range(32)));key=vault_checks.key_bytes(mint)
        strings=b''.join(struct.pack('<I',len(s))+s for s in (b'Test',b'T',b'https://example.org'))+bytes(4)
        a=account([(18,bytes(32)+key),(19,bytes(32)+key+strings)])
        self.assertTrue(ext.audit(a,mint)['complete'])
        for bad in [account([(18,b'x'*32+key)]),account([(18,bytes(32)+bytes(32))]),account([(19,b'x'*32+key+strings)]),account([(19,bytes(32)+key+strings+b'x')])]:
            self.assertFalse(ext.audit(bad,mint)['complete'])
    def test_duplicate_truncated_mutable_authority(self):
        self.assertFalse(ext.audit(account([(18,bytes(64)),(18,bytes(64))]),MINT)['complete'])
        for field in (0,46):
            a=account();b=bytearray(base64.b64decode(a['data'][0]));b[field]=1;a['data'][0]=base64.b64encode(b).decode()
            self.assertFalse(ext.audit(a,MINT)['complete'])
        a=account([(18,bytes(64))]);a['data'][0]=base64.b64encode(base64.b64decode(a['data'][0])[:-1]).decode()
        self.assertFalse(ext.audit(a,MINT)['complete'])
    def test_v3_default_still_rejects_token2022(self):
        r=risk_report();r['tokenProgram']=ext.TOKEN2022
        self.assertEqual(security_v3.report_gate(r,market_pool()),'v3_token_program_unsupported')
        self.assertIsNone(security_v3.report_gate(r,market_pool(),(ext.TOKEN2022,)))


class Narratives(unittest.TestCase):
    def test_new_name_no_manual_alias(self):
        ts=intel.trends(articles(),{},NOW)
        self.assertIn('NebulaFox',[t['label'] for t in ts])
        n=intel.match(market_pool(),{'trends':ts},NOW)
        self.assertIsNone(n['reject']);self.assertIsNone(n['virality_score'])
    def test_unicode_survives(self):
        for word in ['猫咪','悟空','한국밈','未来猫']:
            self.assertTrue(intel.normalize(word)); self.assertTrue(intel.contains('新'+word+'ニュース',word))
        xml='<rss><item><title>日本の新しいゲーム未来猫が発表</title><link>https://example.org/n</link><source url="https://example.org">Publisher</source><pubDate>'+formatdate(NOW,usegmt=True)+'</pubDate></item></rss>'
        self.assertEqual(len(intel.narrative_v3.parse_feed(xml,'global',NOW,normalizer=intel.normalize)),1)
    def test_future_observation_or_publication_never_used(self):
        for key in ('published_at','observed_at'):
            rows=articles();rows[1][key]=NOW+1;self.assertEqual(intel.trends(rows,{},NOW),[])
    def test_single_publisher_and_syndication_not_trend(self):
        rows=articles();rows[1]['publisher_host']=rows[0]['publisher_host'];self.assertEqual(intel.trends(rows,{},NOW),[])
        rows=articles();rows[1]['title']=rows[0]['title'];self.assertEqual(intel.trends(rows,{},NOW),[])
    def test_unbacked_ai_entity_and_substring_not_match(self):
        self.assertEqual(intel.trends([],{'entities':['NebulaFox']},NOW),[])
        self.assertFalse(intel.contains('chaircoin','AI'))
    def test_parody_is_tentative(self):
        ts=intel.trends(articles(),{},NOW);p=market_pool();p['baseToken']['name']='NebulaFux'
        n=intel.match(p,{'trends':ts},NOW);self.assertEqual(n['relationship'],'possible_name_parody')
    def test_outage_honest_no_invented_entities(self):
        with patch.object(evidence,'public_read',side_effect=TimeoutError()),patch.dict(os.environ,{'ACTIONS_ID_TOKEN_REQUEST_TOKEN':''}):
            f=intel.collect(bot,{},NOW)
        self.assertFalse(f['llm_used']);self.assertEqual(f['trends'],[]);self.assertEqual(len(f['sources']),7)


class Modes(unittest.TestCase):
    def setUp(self): self.n={'reject':None,'relationship':'name_match'}
    def test_early_and_no_fdv_fallback(self):
        p=market_pool();self.assertIn('EARLY HUNTER',hunter_modes.assess(p,{},NOW,self.n)['modes'])
        p['marketCap']=None;p['fdv']=100000
        self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'v5_market_missing')
    def test_viral_requires_real_acceleration(self):
        p=market_pool(30*86400)
        self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'v5_viral_acceleration_unverified')
        old=snapshot(p,NOW-300);old.update(volume=p['volume']['m5']/2,buys=p['txns']['m5']['buys']/2,sells=p['txns']['m5']['sells']/2)
        result=hunter_modes.assess(p,{PAIR:[old]},NOW,self.n)
        self.assertEqual(result['modes'],['VIRAL HUNTER'])
        p['pairCreatedAt']=(NOW-90*86400-1)*1000;self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'v5_pool_age')
    def test_market_cap_and_price_limits(self):
        for cap in (19999,5000001):
            p=market_pool();p['marketCap']=cap;self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'v5_market_cap')
        for key in ('h1','h24'):
            p=market_pool();p['priceChange'][key]=None
            self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'v5_price_windows_missing')
        p=market_pool();p['priceChange']['h1']=100
        self.assertEqual(hunter_modes.assess(p,{},NOW,self.n)['reject'],'late_or_falling_price')
    def test_unknown_scores_are_unknown(self):
        s=hunter_modes.scores({}, {}, {}, {}, {})
        self.assertIsNone(s['virality']);self.assertIsNone(s['community']);self.assertIsNone(s['security'])


class Memory(unittest.TestCase):
    def test_security_cannot_be_borrowed_from_future(self):
        row={'observed_at':NOW,'pool':market_pool(),'articles':articles(),'security':{'complete':True},'security_observed_at':NOW+1}
        self.assertFalse(hunter_memory.replay([row])['decisions'][0]['accepted'])
        row['security_observed_at']=NOW
        self.assertTrue(hunter_memory.replay([row])['decisions'][0]['accepted'])
    def test_future_headlines_rejected_and_order_required(self):
        row={'observed_at':NOW,'pool':market_pool(),'articles':articles(),'security':{'complete':True},'security_observed_at':NOW}
        row['articles'][1]['observed_at']=NOW+1
        self.assertFalse(hunter_memory.replay([row])['decisions'][0]['accepted'])
        with self.assertRaises(ValueError):hunter_memory.replay([row,dict(row,observed_at=NOW-1)])
    def test_reject_reason_updated_but_first_price_preserved(self):
        state={};p=market_pool();hunter_memory.record(state,p,{},'awaiting_security',NOW)
        hunter_memory.record(state,p,{},'insider_coverage_unavailable',NOW+1)
        self.assertEqual(next(iter(state['memory_v5'].values()))['decision'],'insider_coverage_unavailable')
    def test_merge_preserves_v5_and_first_delivery_owner(self):
        a={'enabled':True,'memory_v5':{'x':{'at':NOW,'price':1,'samples':{'300':{'status':'observed'}}}},'delivery':{'health:1':{'at':NOW,'reservation':'first'}}}
        b={'memory_v5':{'x':{'at':NOW,'updated':NOW+1,'samples':{'900':{'status':'missed'}}}},'global_feed_v5':{'at':NOW,'value':{}},'delivery':{'health:1':{'at':NOW,'reservation':'second'}}}
        out=state_store.merge(a,b,NOW+2)
        self.assertEqual(len(out['memory_v5']['x']['samples']),2);self.assertEqual(out['delivery']['health:1']['reservation'],'first');self.assertIn('global_feed_v5',out)
    def test_horizon_late_observation_not_backdated(self):
        r={'at':NOW,'price':1};state_store.sample_performance(r,2,NOW+3600)
        self.assertEqual(r['samples']['300']['status'],'missed');self.assertEqual(r['samples']['3600']['at'],NOW+3600)


class Delivery(unittest.TestCase):
    def test_health_once_and_unknown_not_retried(self):
        state={'enabled':True};api=Mock();api.tg.return_value={'message_id':99,'chat':{'id':123}}
        with patch.object(scanner_v5.time,'time',return_value=NOW),patch.object(scanner_v5.legacy,'checkpoint'):
            self.assertEqual(scanner_v5.health(state,api,123,{'health':'degraded'})['status'],'sent')
            self.assertEqual(scanner_v5.health(state,api,123,{})['status'],'not_due');self.assertEqual(api.tg.call_count,1)
        state={'enabled':False};api.tg.side_effect=TimeoutError()
        with patch.object(scanner_v5.time,'time',return_value=NOW),patch.object(scanner_v5.legacy,'checkpoint'):
            self.assertEqual(scanner_v5.health(state,api,123,{})['status'],'unknown_no_retry')
            self.assertEqual(scanner_v5.health(state,api,123,{})['status'],'not_due')
    def test_no_candidate_send_without_security_all_modes(self):
        p=market_pool();p['_narrative_v3']={'reject':None};p['_security_v3']={'complete':False}
        api=Mock();state_store.migrate(state:={},NOW)
        self.assertFalse(scanner_v5.legacy.deliver(state,api,123,p,{}, {}, {}, {}, {},'GLOBAL SIGNAL',renderer=scanner_v5.render))
        api.tg.assert_not_called()
    def test_social_outage_is_not_organic(self):
        with patch.object(evidence,'public_read',side_effect=TimeoutError()):public=social_intelligence.sample(bot,'cat',MINT,NOW)
        self.assertEqual(public['status'],'unavailable');self.assertEqual(public['organic_status'],'unknown')
        out=social_intelligence.observe({},MINT,{},public,market_pool(),NOW)
        self.assertIsNone(out['virality_score']);self.assertEqual(out['image_contents'],'not_analyzed')

if __name__=='__main__':unittest.main()

class PipelineV5(unittest.TestCase):
    def test_market_candidate_still_cannot_send_when_insiders_unknown(self):
        p=market_pool();f={'trends':intel.trends(articles(),{},NOW),'sources':{},'ai':{'status':'not_configured'}}
        api=Mock();api.REQUEST_DEADLINE=None
        state={'enabled':True}
        with tempfile.TemporaryDirectory() as tmp, patch.object(scanner_v5.time,'time',return_value=NOW), \
             patch.object(scanner_v5.intelligence,'collect',return_value=f), \
             patch.object(scanner_v5.legacy,'discover',return_value=([p],{'sources':{}})), \
             patch.object(scanner_v5.intelligence,'search_pools',return_value=[]), \
             patch.object(scanner_v5.social_intelligence,'discover_contracts',return_value=([],{'status':'unavailable'})), \
             patch.object(scanner_v5.market_data,'hydrate_incomplete',side_effect=lambda pools,*a:(pools,{})), \
             patch.object(scanner_v5.market_data,'refresh_watchlist',side_effect=lambda pools,*a,**k:pools), \
             patch.object(scanner_v5.hunter_memory,'followup'), \
             patch.object(scanner_v5.evidence,'security',return_value={'complete':True,'score':100}), \
             patch.object(scanner_v5.evidence,'buyers',return_value={'strong':True}), \
             patch.object(scanner_v5.security_v3,'inspect',return_value={'complete':False,'reject':'insider_coverage_unavailable'}), \
             patch.object(scanner_v5.legacy,'checkpoint'), \
             patch.object(scanner_v5.legacy,'deliver') as send, \
             patch.object(scanner_v5,'Path',side_effect=lambda name:__import__('pathlib').Path(tmp)/name),redirect_stdout(io.StringIO()):
            result=scanner_v5.run(state,123,api,dry_run=True)
        self.assertEqual(result['sent'],0);self.assertEqual(result['rejected'],{'insider_coverage_unavailable':1})
        send.assert_not_called();api.tg.assert_not_called()
    def test_off_mode_skips_discovery(self):
        api=Mock();api.REQUEST_DEADLINE=None
        with tempfile.TemporaryDirectory() as tmp,patch.object(scanner_v5,'Path',side_effect=lambda name:__import__('pathlib').Path(tmp)/name), \
             patch.object(scanner_v5.intelligence,'collect') as collect,patch.object(scanner_v5.legacy,'checkpoint'),redirect_stdout(io.StringIO()):
            out=scanner_v5.run({'enabled':False},123,api,dry_run=True)
        self.assertEqual(out['health'],'paused');collect.assert_not_called();api.tg.assert_not_called()

class SocialSequences(unittest.TestCase):
    def test_unique_buyer_acceleration_requires_observed_separated_samples(self):
        state={}
        self.assertIsNone(social_intelligence.observe_buyers(state,MINT,{'unique_buyers':10},NOW)['unique_buyer_acceleration'])
        self.assertEqual(social_intelligence.observe_buyers(state,MINT,{'unique_buyers':20},NOW+300)['unique_buyer_acceleration'],2)
        self.assertIsNone(social_intelligence.observe_buyers(state,MINT,{'unique_buyers':None},NOW+600)['unique_buyer_acceleration'])
    def test_avatar_change_is_url_only_organic_stays_unknown(self):
        public={'status':'observed','posts':[{'at':NOW,'uri':'one','author':'did:plc:one','avatar_url':'https://cdn.example/one'}],'interactions':1,'contract_mentions':0}
        state={};social_intelligence.observe(state,MINT,{},public,{},NOW)
        public['posts'][0]['avatar_url']='https://cdn.example/two'
        result=social_intelligence.observe(state,MINT,{},public,{},NOW+300)
        self.assertEqual(result['avatar_url_changes'],['did:plc:one']);self.assertEqual(result['image_contents'],'not_analyzed');self.assertEqual(result['organic_status'],'unknown')
