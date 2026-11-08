import copy
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import bot
import evidence
import scanner_v2
import screening_rules as rules
import state_store
import telegram_check

MINT = 'A'*32
PAIR = 'B'*32
NOW = 1800000000


def pool(age=600):
    return {'chainId':'solana','pairAddress':PAIR,'pairCreatedAt':(NOW-age)*1000,
            'baseToken':{'address':MINT,'symbol':'TEST','name':'Test <coin>'},'priceUsd':'1.05',
            'liquidity':{'usd':30000},'marketCap':150000,'volume':{'m5':7000},
            'txns':{'m5':{'buys':50,'sells':15}},'priceChange':{'m5':5,'h1':10}}


def history():
    p=pool();p['priceUsd']='1';p['volume']['m5']=4000;p['txns']['m5']={'buys':30,'sells':10}
    return {PAIR:[scanner_v2.snapshot(p,NOW-300)]}


def sec():
    return {'score':100,'authority_verified':True,'complete':True,'reject':None,'risks':[],'top10_accounts_pct':20}


def social():
    return {'score':90,'complete':True,'risks':[],'metadata_links':{},'verified_links':{},
            'x':{'status':'observed'},'telegram':{'status':'public_posts'}}


def mint_age():
    return {'verified':True,'created_at':NOW-700,'age_seconds':700,'status':'finalized_initialize_mint'}


class Rules(unittest.TestCase):
    def test_age_boundaries_and_priority(self):
        for age in (59,86401): self.assertEqual(rules.market(pool(age),{},NOW)['reject'],'pool_age')
        for age in (60,3600,3601,86400):
            data=rules.market(pool(age),{},NOW)
            self.assertIsNone(data['reject']);self.assertEqual(data['priority'],age<=3600)
    def test_early_without_baseline_never_strong(self):
        m=rules.market(pool(90),{},NOW)
        self.assertFalse(m['strong']);self.assertIsNone(m['growth'])
        self.assertEqual(rules.choose_tier(m,sec(),social(),{'strong':True},mint_age()),'EARLY WATCH')
    def test_full_market_growth_and_separate_scores(self):
        m=rules.market(pool(),history(),NOW)
        self.assertTrue(m['strong']);self.assertGreaterEqual(m['score'],80)
        self.assertAlmostEqual(m['growth']['volume'],1.75)
        self.assertEqual(rules.choose_tier(m,sec(),social(),{'strong':True},mint_age()),'STRONG SIGNAL')
    def test_unknown_evidence_cannot_be_strong(self):
        base=[rules.market(pool(),history(),NOW),sec(),social(),{'strong':True},mint_age()]
        for index,key,value in [(0,'score',79),(1,'complete',False),(1,'score',79),(2,'complete',False),(2,'score',None),(2,'score',79),(3,'strong',False),(4,'verified',False)]:
            rows=copy.deepcopy(base);rows[index][key]=value
            if index==0: rows[0]['strong']=False
            self.assertEqual(rules.choose_tier(*rows),'EARLY WATCH')
    def test_hard_security_rejection_blocks_early_too(self):
        s=sec();s['reject']='mint_authority_active'
        self.assertIsNone(rules.choose_tier(rules.market(pool(),{},NOW),s,social(),{},{}))
    def test_late_price_surge_and_missing_data(self):
        for field in ('marketCap','priceUsd','liquidity','txns','pairCreatedAt'):
            p=pool();del p[field];self.assertIsNotNone(rules.market(p,{},NOW)['reject'])
        for v in (float('nan'),float('inf'),True,-1):
            p=pool();p['liquidity']['usd']=v;self.assertIsNotNone(rules.market(p,{},NOW)['reject'])
        p=pool();p['priceChange']['m5']=26;self.assertEqual(rules.market(p,{},NOW)['reject'],'late_or_falling_price')
    def test_slowing_transactions_stays_watch(self):
        p=pool();p['txns']['m5']['buys']=30
        self.assertFalse(rules.market(p,history(),NOW)['strong'])
    def test_same_mint_pool_history_required(self):
        h=history();h[PAIR][0]['mint']='C'*32
        self.assertFalse(rules.market(pool(),h,NOW)['strong'])
    def test_social_url_spoofs_and_private_invites_rejected(self):
        bad=['https://x.com.evil.com/valid','https://x.com@evil.com/valid','https://evil.com/x.com/valid','javascript:alert(1)','https://x.com:443/valid','https://x.com/i/communities/1','https://x.com/valid/status/123']
        for u in bad:self.assertIsNone(rules.canonical_social(u,'x'))
        for u in ('https://t.me/+secret','https://t.me/joinchat/secret','https://t.me/proxy','https://t.me.evil.com/groupname'):
            self.assertIsNone(rules.canonical_social(u,'telegram'))
        self.assertEqual(rules.canonical_social('https://twitter.com/ValidUser?x=1','x'),'https://x.com/validuser')
    def test_conflicting_metadata_has_no_guessed_official_link(self):
        p=pool();p['info']={'socials':[{'url':'https://x.com/userone'},{'url':'https://x.com/usertwo'}]}
        links,risks=rules.social_links(p)
        self.assertIsNone(links['x']);self.assertIn('x_metadata_conflict',risks)


class Evidence(unittest.TestCase):
    def trades(self,count=20):
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        rows=[]
        for i in range(count+3):
            buy=i<count
            rows.append({'attributes':{'tx_hash':'tx'+str(i),'tx_from_address':alphabet[i%len(alphabet)]*32,
                'kind':'buy' if buy else 'sell','volume_in_usd':str(100+i),'block_timestamp':datetime.fromtimestamp(NOW-20,timezone.utc).isoformat(),
                'to_token_address':MINT if buy else 'D'*32,'from_token_address':'D'*32 if buy else MINT}})
        return {'data':rows}
    def test_unique_buyer_count_and_duplicate_tx(self):
        data=self.trades();data['data'].append(data['data'][0])
        r=rules.trade_evidence(data,MINT,NOW)
        self.assertEqual(r['unique_buyers'],20);self.assertEqual(r['buy_transactions'],20);self.assertTrue(r['strong'])
    def test_wash_patterns_and_wrong_token(self):
        data=self.trades()
        for row in data['data'][:20]:row['attributes']['tx_from_address']='Z'*32
        r=rules.trade_evidence(data,MINT,NOW)
        self.assertEqual(r['unique_buyers'],1);self.assertFalse(r['strong'])
        self.assertFalse(rules.trade_evidence(self.trades(),'Z'*32,NOW)['strong'])
    def test_missing_wallet_and_old_trades_not_real_buyers(self):
        data=self.trades()
        for row in data['data']:del row['attributes']['tx_from_address']
        self.assertIsNone(rules.trade_evidence(data,MINT,NOW)['unique_buyers'])
        self.assertIsNone(rules.trade_evidence(self.trades(),MINT,NOW+301)['unique_buyers'])
    def test_anomalous_provider_trades_block_strong(self):
        data=self.trades(25);data['data'][0]['attributes']['is_anomalous']=True
        self.assertFalse(rules.trade_evidence(data,MINT,NOW)['strong'])
    def test_mint_history_limit_never_invents_age(self):
        with patch.object(evidence,'rpc',side_effect=lambda *args:[{'signature':'sig'+str(args[2][-1].get('before','')),'err':None}]*1000):
            self.assertFalse(evidence.mint_creation(MINT,bot,NOW)['verified'])
    def test_mint_initialization_proof(self):
        tx={'blockTime':NOW-700,'meta':{'err':None,'innerInstructions':[]},'transaction':{'message':{'instructions':[{'programId':bot.PROGRAM,'parsed':{'type':'initializeMint2','info':{'mint':MINT}}}]}}}
        with patch.object(evidence,'rpc',side_effect=[[{'signature':'oldest','err':None}],tx]):
            self.assertTrue(evidence.mint_creation(MINT,bot,NOW)['verified'])
        tx['transaction']['message']['instructions'][0]['parsed']['info']['mint']='D'*32
        with patch.object(evidence,'rpc',side_effect=[[{'signature':'oldest','err':None}],tx]):
            self.assertFalse(evidence.mint_creation(MINT,bot,NOW)['verified'])
    def test_x_disabled_never_networks_or_fabricates_score(self):
        with patch.dict(os.environ,{'X_READS_ENABLED':'0'}),patch.object(evidence,'public_read') as read:
            r=evidence.x_analysis('validuser',MINT,bot,NOW)
        read.assert_not_called();self.assertIsNone(r['score']);self.assertFalse(r['complete'])
    def test_x_available_checks_identity_activity_and_interactions(self):
        date=datetime.fromtimestamp(NOW-100,timezone.utc).isoformat()
        user={'data':{'id':'123','username':'validuser','description':MINT,'created_at':'2020-01-01T00:00:00Z'}}
        posts={'data':[{'author_id':'123','created_at':date,'text':'update '+str(i),'public_metrics':{'like_count':10,'reply_count':2,'retweet_count':1}} for i in range(5)]}
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'not-a-real-secret','X_READS_ENABLED':'1'}),patch.object(evidence,'public_read',side_effect=[user,posts]):
            r=evidence.x_analysis('validuser',MINT,bot,NOW)
        self.assertTrue(r['complete']);self.assertEqual(r['score'],100)
        user['data']['description']='different coin'
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'not-a-real-secret','X_READS_ENABLED':'1'}),patch.object(evidence,'public_read',side_effect=[user,posts]):
            self.assertFalse(evidence.x_analysis('validuser',MINT,bot,NOW)['complete'])
    def test_telegram_member_count_does_not_raise_score(self):
        date=datetime.fromtimestamp(NOW-100,timezone.utc).isoformat()
        markup=''.join('<div class="tgme_widget_message_text js-message_text">Update '+str(i)+'</div><time datetime="'+date+'"></time>' for i in range(5))
        scores=[]
        for members in (10,1000000):
            with patch.object(bot,'tg',side_effect=[{'type':'channel','username':'validuser','description':MINT},members]),patch.object(evidence,'public_read',return_value=markup):
                r=evidence.telegram_analysis('validuser',MINT,bot,NOW);scores.append(r['score'])
        self.assertEqual(scores,[100,100])
    def test_telegram_inaccessible_community_is_unknown(self):
        with patch.object(bot,'tg',side_effect=RuntimeError('unavailable')):
            r=evidence.telegram_analysis('validuser',MINT,bot,NOW)
        self.assertIsNone(r['score']);self.assertFalse(r['complete'])
    def test_distribution_and_rugcheck_failures_remain_explicit(self):
        with patch.object(evidence,'rpc',return_value={'value':{}}),patch.object(bot,'security_reason',return_value=None),patch.object(bot,'holder_concentration',side_effect=RuntimeError()),patch.object(bot,'request',side_effect=RuntimeError()):
            r=evidence.security(MINT,bot,NOW)
        self.assertFalse(r['complete']);self.assertEqual(r['score'],40);self.assertEqual(len(r['risks']),2)


class StateAndDelivery(unittest.TestCase):
    def test_pending_reservation_suppresses_restart_duplicates(self):
        state=state_store.migrate({'delivery':{MINT+':EARLY WATCH':{'at':NOW,'status':'pending','reservation':'first'}}},NOW)
        restored=json.loads(json.dumps(state))
        self.assertTrue(state_store.already_delivered(restored,MINT,'EARLY WATCH',NOW+100))
        self.assertFalse(state_store.already_delivered(restored,MINT,'STRONG SIGNAL',NOW+100))
    def test_legacy_suppression_and_strong_blocks_later_watch(self):
        state=state_store.migrate({'sent':{MINT:NOW}},NOW)
        self.assertTrue(state_store.already_delivered(state,MINT,'EARLY WATCH',NOW))
        state['delivery'][MINT+':STRONG SIGNAL']={'at':NOW,'status':'sent'}
        self.assertTrue(state_store.already_delivered(state,MINT,'EARLY WATCH',NOW))
    def test_concurrent_reservations_keep_first_owner(self):
        remote={'delivery':{'k':{'at':NOW,'reservation':'first','status':'pending'}}}
        local={'delivery':{'k':{'at':NOW+1,'reservation':'second','status':'sent'}}}
        self.assertEqual(state_store.merge(remote,local,NOW+2)['delivery']['k']['reservation'],'first')
    def test_newest_admin_offset_controls_enabled(self):
        remote={'offset':10,'enabled':False};local={'offset':9,'enabled':True}
        self.assertFalse(state_store.merge(remote,local,NOW)['enabled'])
    def test_performance_records_actual_time_and_missed_windows(self):
        r={'at':NOW,'price':1}
        state_store.sample_performance(r,1.2,NOW+350)
        self.assertEqual(r['samples']['300']['change_pct'],20)
        self.assertEqual(r['samples']['300']['elapsed_seconds'],350)
        state_store.sample_performance(r,.5,NOW+5000)
        self.assertEqual(r['samples']['900']['status'],'missed')
        self.assertEqual(r['samples']['3600']['status'],'missed')
    def test_send_failure_is_not_retried_after_reload(self):
        state=state_store.migrate({},NOW)
        with patch.object(scanner_v2,'checkpoint'),patch.object(scanner_v2.time,'time',return_value=NOW),patch.object(bot,'tg',side_effect=TimeoutError()) as tg:
            args=(state,bot,123,pool(),rules.market(pool(),history(),NOW),sec(),social(),{'unique_buyers':20,'strong':True},mint_age(),'EARLY WATCH')
            self.assertFalse(scanner_v2.deliver(*args));self.assertFalse(scanner_v2.deliver(*args))
            tg.assert_called_once()
        self.assertEqual(state['delivery'][MINT+':EARLY WATCH']['status'],'unknown')
    def test_persistence_failure_prevents_message(self):
        state=state_store.migrate({},NOW)
        with patch.object(scanner_v2,'checkpoint',side_effect=RuntimeError()),patch.object(bot,'tg') as tg:
            with self.assertRaises(RuntimeError):
                scanner_v2.deliver(state,bot,123,pool(),{},sec(),social(),{},mint_age(),'EARLY WATCH')
        tg.assert_not_called()
    def test_verified_send_records_message_and_performance(self):
        state=state_store.migrate({},NOW)
        with patch.object(scanner_v2,'checkpoint'),patch.object(scanner_v2.time,'time',return_value=NOW),patch.object(bot,'tg',return_value={'message_id':55,'chat':{'id':123}}) as tg:
            self.assertTrue(scanner_v2.deliver(state,bot,123,pool(),rules.market(pool(),history(),NOW),sec(),social(),{'unique_buyers':20,'strong':True},mint_age(),'STRONG SIGNAL'))
        self.assertEqual(state['delivery'][MINT+':STRONG SIGNAL']['message_id'],55)
        self.assertIn(MINT+':STRONG SIGNAL',state['performance'])
        self.assertIn('Test &lt;coin&gt;',tg.call_args.kwargs['text'])
    def test_test_notification_sends_once_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'private-test-token','TELEGRAM_CHAT_ID':'-12345678'}),patch.object(telegram_check.Path,'mkdir'),patch.object(telegram_check.Path,'write_text'),patch.object(bot,'tg',side_effect=[{'is_bot':True,'username':'example_bot'},{'type':'channel','id':-12345678,'username':'examplechannel'},{'message_id':12,'chat':{'id':-12345678}}]) as tg:
            stdout=io.StringIO()
            with redirect_stdout(stdout):telegram_check.main()
        self.assertEqual([c.args[0] for c in tg.call_args_list],['getMe','getChat','sendMessage'])
        self.assertIn('TELEGRAM_TEST_OK message_id=12',stdout.getvalue())
        self.assertNotIn('private-test-token',stdout.getvalue());self.assertNotIn('-12345678',stdout.getvalue())


if __name__=='__main__':unittest.main()
