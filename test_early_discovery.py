"""Regression tests for missing DEX indexing, valuation honesty and new-mint gates."""
import copy
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import bot
import evidence
import market_data as data
import scanner_v2
import screening_rules as rules
import state_store
from test_upgrade import pool, history, sec, social, mint_age, NOW, MINT, PAIR

QUOTE = 'So11111111111111111111111111111111111111112'


def payload():
    return {'data':[{'type':'pool','attributes':{
        'address':PAIR, 'pool_created_at':datetime.fromtimestamp(NOW-600,timezone.utc).isoformat(),
        'base_token_price_usd':'1.05', 'market_cap_usd':None, 'fdv_usd':'150000', 'reserve_in_usd':'30000',
        'volume_usd':{'m5':'7000'}, 'price_change_percentage':{'m5':'5','h1':'10'},
        'transactions':{'m5':{'buys':50,'sells':15,'buyers':30,'sellers':10}}},
        'relationships':{'base_token':{'data':{'id':'solana_'+MINT}},'quote_token':{'data':{'id':'solana_'+QUOTE}},'dex':{'data':{'id':'pump-swap'}}}}],
        'included':[{'id':'solana_'+MINT,'attributes':{'address':MINT,'name':'New token','symbol':'NEW'}}]}


class IndependentFeeds(unittest.TestCase):
    def test_native_pool_preserves_missing_market_cap_and_present_fdv(self):
        p=data.gecko_pools(payload())[0]
        self.assertIsNone(p['marketCap']);self.assertEqual(p['fdv'],150000)
        self.assertEqual(p['baseToken']['address'],MINT);self.assertEqual(p['pairCreatedAt'],(NOW-600)*1000)
        self.assertEqual(data.missing_fields(p),[])
    def test_missing_volume_or_change_is_never_zero_filled(self):
        body=payload();body['data'][0]['attributes']['volume_usd']['m5']=None
        body['data'][0]['attributes']['price_change_percentage']['m5']=None
        p=data.gecko_pools(body)[0]
        self.assertIsNone(p['priceChange']['m5']);self.assertIn('volume.m5',data.missing_fields(p))
        self.assertEqual(rules.market(p,{},NOW)['reject'],'missing_market_data')
    def test_wrong_network_token_or_included_identity_is_rejected(self):
        body=payload();body['data'][0]['relationships']['base_token']['data']['id']='ethereum_'+MINT
        self.assertEqual(data.gecko_pools(body),[])
        body=payload();body['included'][0]['attributes']['address']='C'*32
        self.assertEqual(data.gecko_pools(body),[])
    def test_wrapped_sol_is_not_a_new_meme_token(self):
        body=payload();body['data'][0]['relationships']['base_token']['data']['id']='solana_'+QUOTE
        self.assertEqual(data.gecko_pools(body),[])
    def test_complete_native_snapshot_replaces_incomplete_dex(self):
        dex=pool();dex.pop('liquidity');dex['volume']['m5']=999999
        result=data.select_pool(dex,data.gecko_pools(payload())[0])
        self.assertEqual(result['dataSource'],'geckoterminal');self.assertEqual(result['volume']['m5'],7000)
        self.assertEqual(result['liquidity']['usd'],30000)
    def test_conflicting_mint_never_merges_market_data(self):
        native=data.gecko_pools(payload())[0];native['baseToken']['address']='C'*32
        p=data.select_pool(pool(),native)
        self.assertEqual(rules.market(p,{},NOW)['reject'],'invalid_identity')
    def test_age_fallback_requires_same_pool_and_mint(self):
        dex=pool();del dex['pairCreatedAt']
        p=data.select_pool(dex,data.gecko_pools(payload())[0])
        self.assertEqual(p['ageSource'],'geckoterminal');self.assertEqual(p['dataSource'],'dexscreener')
    def test_conflicting_age_blocks_strong(self):
        native=data.gecko_pools(payload())[0];native['pairCreatedAt']-=180000
        p=data.select_pool(pool(),native)
        self.assertTrue(p['ageConflict']);self.assertFalse(rules.market(p,history(),NOW)['strong'])
    def test_discover_keeps_gecko_pools_when_dex_has_not_indexed_them(self):
        def request(url):
            if '/new_pools?' in url:return payload()
            if '/latest/dex/pairs/' in url:return {'pairs':[]}
            return []
        api=SimpleNamespace(DEX=bot.DEX,request=request)
        pools,report=scanner_v2.discover(api)
        self.assertEqual(len(pools),1);self.assertEqual(report['gecko_independent_pools'],1)
        self.assertEqual(report['dex_pool_count'],0)
    def test_final_refresh_works_without_dex_index(self):
        api=SimpleNamespace(DEX=bot.DEX,request=Mock(return_value={'pairs':[]}))
        gecko=SimpleNamespace(request=Mock(return_value=payload()))
        result=data.refresh_pool(PAIR,MINT,api,gecko)
        self.assertEqual(result['dataSource'],'geckoterminal')
        with self.assertRaises(ValueError):data.refresh_pool(PAIR,'C'*32,api,gecko)
    def test_final_refresh_rejects_all_missing_sources(self):
        api=SimpleNamespace(DEX=bot.DEX,request=Mock(side_effect=TimeoutError()))
        gecko=SimpleNamespace(request=Mock(side_effect=TimeoutError()))
        with self.assertRaises(ValueError):data.refresh_pool(PAIR,MINT,api,gecko)
    def test_native_only_pool_can_send_labelled_watch_once_end_to_end(self):
        def request(url,*args):
            if url.startswith(data.GECKO):return payload()
            if '/latest/dex/pairs/' in url:return {'pairs':[]}
            return []
        state={'enabled':True};unknown=social();unknown.update(score=None,complete=False)
        with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}),patch.object(bot,'request',side_effect=request),patch.object(bot,'tg',return_value={'message_id':42,'chat':{'id':123}}) as tg,patch.object(scanner_v2.time,'time',return_value=NOW),patch.object(scanner_v2,'checkpoint'),patch.object(scanner_v2,'followup'),patch.object(evidence,'security',return_value=sec()),patch.object(evidence,'community',return_value=unknown),patch.object(evidence,'mint_creation',return_value=mint_age()),patch.object(evidence,'buyers',return_value={'strong':True,'unique_buyers':25}),patch.object(scanner_v2.Path,'mkdir'),patch.object(scanner_v2.Path,'write_text'):
            scanner_v2.run(state,123,bot)
            self.assertEqual(tg.call_count,1)
            self.assertIn('FDV (MC belum tersedia)',tg.call_args.kwargs['text'])
            self.assertIn('geckoterminal',tg.call_args.kwargs['text'])
            restored=json.loads(json.dumps(state));tg.reset_mock()
            scanner_v2.run(restored,123,bot)
            tg.assert_not_called()


class EvidenceAndValuation(unittest.TestCase):
    def test_fdv_can_only_produce_watch_and_is_labelled(self):
        p=data.gecko_pools(payload())[0];m=rules.market(p,history(),NOW)
        self.assertIsNone(m['reject']);self.assertEqual(m['cap_basis'],'fdv_proxy');self.assertFalse(m['strong'])
        tier=rules.choose_tier(m,sec(),social(),{'strong':True},mint_age())
        self.assertEqual(tier,'EARLY WATCH')
        message=scanner_v2.render(p,m,sec(),social(),{'unique_buyers':25,'strong':True},mint_age(),tier)
        self.assertIn('FDV (MC belum tersedia)',message);self.assertIn('Sumber pasar: geckoterminal',message)
    def test_invalid_market_cap_does_not_fall_back_to_fdv(self):
        p=pool();p['fdv']=150000
        for cap in (False,-1,float('nan'),float('inf')):
            p['marketCap']=cap;self.assertIsNotNone(rules.market(p,{},NOW)['reject'])
    def test_old_mint_is_rejected_even_when_pool_is_new(self):
        age=mint_age();age['age_seconds']=86401
        m=rules.market(pool(),history(),NOW)
        self.assertIsNone(rules.choose_tier(m,sec(),social(),{'strong':True},age))
        self.assertEqual(rules.evidence_rejection(m,sec(),{},age),'token_older_than_24h')
    def test_mint_younger_than_pool_is_not_verified_consistent(self):
        age=mint_age();age['age_seconds']=60
        self.assertIsNone(rules.choose_tier(rules.market(pool(),{},NOW),sec(),social(),{},age))
    def test_known_suspicious_buying_blocks_both_alert_levels(self):
        for risk in ('volume_buy_terpusat','provider_anomalous_trade','nominal_transaksi_berulang'):
            buyers={'strong':False,'risks':[risk]}
            self.assertIsNone(rules.choose_tier(rules.market(pool(),history(),NOW),sec(),social(),buyers,mint_age()))
    def test_pumped_then_flat_does_not_look_like_an_early_entry(self):
        p=pool();p['priceChange']['h24']=1000
        self.assertEqual(rules.market(p,{},NOW)['reject'],'already_extended_24h')
    def test_account_existence_does_not_verify_project_identity(self):
        p=pool();p['info']={'socials':[{'url':'https://x.com/validuser'},{'url':'https://t.me/validuser'}]}
        other={'verified_link':True,'identity_consistent':False,'score':20,'complete':False}
        matched=dict(other,identity_consistent=True)
        with patch.object(evidence,'x_analysis',return_value=other),patch.object(evidence,'telegram_analysis',return_value=matched):
            social=evidence.community(p,bot,NOW)
        self.assertNotIn('x',social['verified_links']);self.assertIn('telegram',social['verified_links'])


class PersistenceAndBudgets(unittest.TestCase):
    def test_rate_limit_survives_restart_and_counts_failures(self):
        state={'gecko_requests':[NOW-10+i/100 for i in range(8)]}
        api=SimpleNamespace(request=Mock(side_effect=TimeoutError()))
        with patch.object(data.time,'time',return_value=NOW):
            client=data.GeckoClient(api,state)
            with self.assertRaises(TimeoutError):client.request(data.GECKO+'/test')
            restored=json.loads(json.dumps(state));client=data.GeckoClient(api,restored)
            with self.assertRaises(RuntimeError):client.request(data.GECKO+'/test')
        self.assertEqual(api.request.call_count,1);self.assertEqual(client.limited,1)
    def test_rate_budget_recovers_without_sleep_after_a_minute(self):
        state={'gecko_requests':[NOW-61+i/100 for i in range(9)]}
        api=SimpleNamespace(request=Mock(return_value={}))
        with patch.object(data.time,'time',return_value=NOW):data.GeckoClient(api,state).request(data.GECKO+'/test')
        self.assertEqual(len(state['gecko_requests']),1)
    def test_pool_remains_watched_after_leaving_latest_feed(self):
        state={};data.retain_watchlist(state,[pool()],NOW)
        state=json.loads(json.dumps(state))
        api=SimpleNamespace(DEX=bot.DEX,request=Mock(return_value={'pairs':[]}))
        gecko=SimpleNamespace(request=Mock(return_value=payload()))
        refreshed=data.refresh_watchlist([],state,api,gecko,NOW+1800)
        self.assertEqual(len(refreshed),1);self.assertEqual(refreshed[0]['baseToken']['address'],MINT)
        data.retain_watchlist(state,[],NOW+86400)
        self.assertEqual(state['pool_watchlist'],{})
    def test_durable_merge_retains_budget_watchlist_and_remote_off(self):
        local={'offset':1,'enabled':True,'gecko_requests':[NOW-1]};data.retain_watchlist(local,[pool()],NOW)
        remote={'offset':2,'enabled':False,'gecko_requests':[NOW-2,NOW-1]}
        merged=state_store.merge(remote,local,NOW)
        self.assertFalse(merged['enabled']);self.assertIn(PAIR,merged['pool_watchlist'])
        self.assertEqual(merged['gecko_requests'],[NOW-2,NOW-1])
    def test_performance_separates_tiers_and_excludes_missed_prices(self):
        first={'tier':'EARLY WATCH','at':NOW,'price':1,'samples':{}}
        second={'tier':'STRONG SIGNAL','at':NOW,'price':1,'samples':{}}
        state_store.sample_performance(first,1.2,NOW+310)
        state_store.sample_performance(second,.4,NOW+5000)
        report=state_store.performance_summary({'performance':{'a':first,'b':second}})
        self.assertEqual(report['EARLY WATCH']['windows_seconds']['300']['median_change_pct'],20)
        self.assertIsNone(report['STRONG SIGNAL']['windows_seconds']['300']['median_change_pct'])
        self.assertEqual(second['worst_observed_pct'],-60)


if __name__=='__main__':unittest.main()
