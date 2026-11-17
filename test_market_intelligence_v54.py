import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import chain_intelligence as chain
import filter_audit as audit
import hunter_modes
import hunter_memory
import state_store
from test_global_v5 import market_pool
from test_upgrade import NOW
from vault_checks import b58encode

MINT=b58encode(bytes([71])*32)
PAIR=b58encode(bytes([72])*32)
SIG=b58encode(bytes([73])*64)
QUOTE=chain.QUOTE


def creation(spec):
    accounts=[b58encode(bytes([i+1])*32) for i in range(len(spec['accounts']))]
    roles=dict(zip(spec['accounts'],range(len(accounts))))
    for i,value in spec['fixed'].items():accounts[int(i)]=value
    for role in ('mint','base_mint','token_a_mint'):
        if role in roles:accounts[roles[role]]=MINT
    for role in ('quote_mint','token_b_mint'):
        if role in roles:accounts[roles[role]]=QUOTE
    for role in ('pool','bonding_curve'):
        if role in roles:accounts[roles[role]]=PAIR
    if 'mint_authority' in roles:accounts[roles['mint_authority']]=chain.PUMP_MINT_AUTHORITY
    ix={'programId':spec['program'],'accounts':accounts,'data':b58encode(bytes(spec['discriminator'])+bytes(320))}
    return {'blockTime':NOW-120,'meta':{'err':None},'transaction':{'signatures':[SIG],
            'message':{'instructions':[ix],'accountKeys':accounts}}}


class Protocols(unittest.TestCase):
    def specs(self):return [r for r in chain.LAYOUTS if r['name'].startswith(('create','initialize'))]
    def test_official_mint_authority_derivation(self):
        self.assertEqual(chain.PUMP_MINT_AUTHORITY,'TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM')
    def test_each_official_creation_layout_and_long_borsh_payload(self):
        for spec in self.specs():
            with self.subTest(protocol=spec['protocol'],name=spec['name']):
                rows=chain.parse_creation(creation(spec),SIG,NOW)
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['baseToken']['address'],MINT)
                self.assertNotIn('volume',rows[0]);self.assertNotIn('marketCap',rows[0])
    def test_spoofed_program_discriminator_fixed_account_and_failure_rejected(self):
        for spec in self.specs():
            for change in ('program','data','fixed','failed','signature','future','old','truncated'):
                tx=creation(spec);ix=tx['transaction']['message']['instructions'][0]
                if change=='program':ix['programId']=MINT
                if change=='data':ix['data']=b58encode(bytes(32))
                if change=='fixed':
                    i=next(iter(spec['fixed']));ix['accounts'][int(i)]=MINT
                if change=='failed':tx['meta']['err']={'error':True}
                if change=='signature':tx['transaction']['signatures']=[]
                if change=='future':tx['blockTime']=NOW+1
                if change=='old':tx['blockTime']=NOW-3601
                if change=='truncated':ix['accounts']=ix['accounts'][:3]
                with self.subTest(protocol=spec['protocol'],change=change):self.assertEqual(chain.parse_creation(tx,SIG,NOW),[])
    def test_inner_creation_instruction(self):
        spec=self.specs()[0];tx=creation(spec)
        tx['meta']['innerInstructions']=[{'instructions':tx['transaction']['message'].pop('instructions')}]
        self.assertEqual(len(chain.parse_creation(tx,SIG,NOW)),1)
    def test_bonding_curve_is_not_automatically_a_dex_pool(self):
        spec=next(s for s in self.specs() if s['protocol']=='pump')
        tx=creation(spec);api=SimpleNamespace(REQUEST_DEADLINE=None,DEX='https://dex.example',request=Mock(return_value=[]))
        provider=SimpleNamespace(api=api,rpc=Mock(side_effect=lambda m,p:[{'signature':SIG,'blockTime':NOW-120,'err':None}] if m=='getSignaturesForAddress' else tx))
        pools,stats,archived,leads=chain.discover(provider,{},NOW)
        self.assertEqual(pools,[]);self.assertEqual(len(leads),1)
        self.assertEqual(stats['unindexed_curve_leads'],1)
        self.assertEqual(stats['baseline_cpmm_leads'],0);self.assertEqual(stats['v54_leads'],1)
    def test_cache_survives_restart_and_retains_rotation(self):
        spec=next(s for s in self.specs() if s['protocol']=='pumpswap');tx=creation(spec)
        provider=SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None),rpc=Mock(side_effect=lambda m,p:[{'signature':SIG,'blockTime':NOW-120,'err':None}] if m=='getSignaturesForAddress' else tx))
        state={};chain.discover(provider,state,NOW)
        state=state_store.merge({},state,NOW+1)
        _,stats,_,_=chain.discover(provider,state,NOW+1)
        self.assertEqual(stats['transaction_reads'],0);self.assertGreater(stats['cache_hits'],0)
        self.assertEqual(state['chain_intelligence_v54']['rotation'],2)
    def test_unindexed_curve_rechecked_after_rpc_signature_is_cached(self):
        spec=next(s for s in self.specs() if s['protocol']=='pump');tx=creation(spec)
        api=SimpleNamespace(REQUEST_DEADLINE=None,DEX='https://dex.example',request=Mock(return_value=[]))
        provider=SimpleNamespace(api=api,rpc=Mock(side_effect=lambda m,p:[{'signature':SIG,'blockTime':NOW-120,'err':None}] if m=='getSignaturesForAddress' else tx))
        state={};chain.discover(provider,state,NOW)
        state=state_store.merge({},state,NOW+300)
        p=market_pool();p['baseToken']['address']=MINT;p['pairAddress']=b58encode(bytes([74])*32)
        p['pairCreatedAt']=(NOW+240)*1000;api.request.return_value=[p]
        rows,stats,_,_=chain.discover(provider,state,NOW+301)
        self.assertEqual(stats['transaction_reads'],0);self.assertEqual(stats['resolved_curve_mints'],1)
        self.assertEqual(rows[0]['pairCreatedAt'],p['pairCreatedAt']);self.assertNotEqual(rows[0]['pairAddress'],PAIR)
        self.assertEqual(state['chain_intelligence_v54']['curves'],{})
    def test_expired_deadline_never_reads_network(self):
        provider=SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=1),rpc=Mock())
        with patch.object(chain.time,'monotonic',return_value=2):chain.discover(provider,{},NOW)
        provider.rpc.assert_not_called()


def swap_tx():
    spec=next(s for s in chain.LAYOUTS if s['protocol']=='pumpswap' and s['name']=='buy')
    tx=creation(spec);a=tx['transaction']['message']['instructions'][0]['accounts'];roles=dict(zip(spec['accounts'],range(len(a))))
    base_idx=roles['pool_base_token_account'];quote_idx=roles['pool_quote_token_account']
    def balances(base,quote):return [
        {'accountIndex':base_idx,'mint':MINT,'uiTokenAmount':{'amount':str(base),'decimals':6}},
        {'accountIndex':quote_idx,'mint':QUOTE,'uiTokenAmount':{'amount':str(quote),'decimals':9}}]
    tx['meta'].update(preTokenBalances=balances(1000000000,10000000000),postTokenBalances=balances(900000000,11000000000))
    return tx


class ChainMetrics(unittest.TestCase):
    def pool(self):return {'pairAddress':PAIR,'baseToken':{'address':MINT},'quoteToken':{'address':QUOTE}}
    def test_exact_vault_delta_units_and_direction_no_usd(self):
        r=chain.reserve_trade(swap_tx(),SIG,self.pool(),NOW)
        self.assertEqual(r['kind'],'buy');self.assertEqual(r['base_reserve_change'],-100)
        self.assertEqual(r['quote_reserve_change'],1);self.assertNotIn('usd',r)
    def test_ambiguous_duplicate_swap_wrong_vault_mint_and_failed_tx_rejected(self):
        for change in ('duplicate','mint','account','failed','sign','time'):
            tx=swap_tx()
            if change=='duplicate':tx['transaction']['message']['instructions']*=2
            if change=='mint':tx['meta']['postTokenBalances'][0]['mint']=QUOTE
            if change=='account':tx['meta']['postTokenBalances'][0]['accountIndex']=999
            if change=='failed':tx['meta']['err']={'failed':True}
            if change=='sign':tx['meta']['postTokenBalances'][0]['uiTokenAmount']['amount']='1100000000'
            if change=='time':tx['blockTime']=NOW-301
            with self.subTest(change=change):self.assertIsNone(chain.reserve_trade(tx,SIG,self.pool(),NOW))
    def test_sample_does_not_mutate_pool_or_claim_full_window(self):
        p=market_pool();p.update(pairAddress=PAIR,dexId='pumpswap',baseToken={'address':MINT},quoteToken={'address':QUOTE})
        before=copy.deepcopy(p)
        provider=SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None),rpc=Mock(side_effect=lambda m,p:[{'signature':SIG,'blockTime':NOW-120,'err':None}] if m=='getSignaturesForAddress' else swap_tx()))
        out=chain.sample_market(provider,[p],NOW)
        self.assertEqual(out['buys'],1);self.assertFalse(out['complete_window'])
        self.assertIsNone(out['usd_volume']);self.assertIsNone(out['usd_liquidity']);self.assertEqual(p,before)


class GateAudit(unittest.TestCase):
    def test_all_gate_values_visible_after_first_rejection(self):
        p=market_pool();p['marketCap']=100;p['liquidity']['usd']=1;p['priceChange']['m5']=200
        r=audit.evaluate(p,{},NOW,{'reject':'no_narrative'})
        self.assertEqual(r['primary_rejection'],'v5_market_cap')
        self.assertIn('liquidity_usd',r['failed']);self.assertIn('price_change_m5',r['failed'])
        self.assertEqual(r['security_stage'],'not_reached')
    def test_decision_parity_and_score_formula(self):
        p=market_pool();n={'reject':None};old=hunter_modes.assess(p,{},NOW,n)
        r=audit.evaluate(p,{},NOW,n)
        self.assertIsNone(r['primary_rejection']);self.assertEqual(r['primary_rejection'],old['reject'])
        score=next(c for c in r['checks'] if c['gate']=='market_score')
        self.assertEqual(score['observed'],old['score'])
    def test_unknown_fields_not_filled_and_narrative_not_invented(self):
        p=market_pool();p['liquidity']['usd']=None;before=copy.deepcopy(p)
        r=audit.evaluate(p,{},NOW,{'reject':'historical_narrative_not_archived'})
        self.assertIn('liquidity_usd',r['unknown']);self.assertIn('narrative',r['unknown']);self.assertEqual(p,before)
    def test_internal_watch_never_verifies_security_or_calls_telegram(self):
        p=market_pool();state={};r=audit.evaluate(p,{},NOW,{'reject':'no_narrative'})
        audit.observe_research(state,p,r,{},NOW)
        row=next(iter(state['market_research_v54']['rows'].values()))
        self.assertTrue(row['internal_only']);self.assertFalse(row['security_verified'])
        self.assertIn('market_research_v54',state_store.merge({},state,NOW))
    def test_frozen_replay_does_not_accept_future_safety(self):
        p=market_pool();out=audit.replay([{'pool':p,'observed_at':NOW,'security':{'complete':True},'security_observed_at':NOW+1}])
        self.assertTrue(out['decision_parity']);self.assertFalse(out['security_relaxed'])
        self.assertGreater(out['new_check_count'],out['old_primary_reason_count'])
    def test_original_decision_is_preserved_separately(self):
        state={};p=market_pool();hunter_memory.record(state,p,{},'first',NOW)
        hunter_memory.record(state,p,{},'later',NOW+1)
        row=next(iter(state['memory_v5'].values()))
        self.assertEqual(row['initial_decision'],'first');self.assertEqual(row['decision'],'later')
    def test_extreme_observations_are_not_proved_missed_safe_trades(self):
        state={'memory_v5':{'one':{'best_observed_pct':3000000}}}
        r=audit.gainer_review(state,[],[],NOW)
        self.assertEqual(r['historical_extreme_unverified'],1);self.assertIsNone(r['proved_missed_safe_trades'])
    def test_current_cycle_record_not_counted_as_previously_seen(self):
        p=market_pool();p['priceChange']['h1']=60
        pair=p['pairAddress'];mint=p['baseToken']['address']
        state={'memory_v5':{'one':{'pair':pair,'mint':mint,'at':NOW-1}}}
        r=audit.gainer_review(state,[p],[],NOW)
        self.assertFalse(r['provider_reported_risers'][0]['seen_before'])
        state['memory_v5']['one']['at']=NOW-301
        self.assertTrue(audit.gainer_review(state,[p],[],NOW)['provider_reported_risers'][0]['seen_before'])


if __name__=='__main__':unittest.main()
