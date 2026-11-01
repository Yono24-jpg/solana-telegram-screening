"""New-pool source, inactive repeats, finalized-history and exit regressions."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from solana_market_readonly import Reader,run,market_assessment
from sniper_discovery_policy import hint_from_pair,hint_due,prioritized_watchlist
from sniper_runtime import PersistentPaperBot
from solana_sniper_paper import candidate
from test_sniper_runtime import tx
from test_discovery_policy import pool


class RelevanceBirthTests(unittest.TestCase):
    def test_repeated_inactivity_backs_off_and_activity_resets(self):
        hint=None
        for _ in range(4):hint=hint_from_pair(pool(volume=0,buys=0),10000,hint)
        self.assertEqual(hint['inactive_streak'],4)
        self.assertFalse(hint_due(hint,10120)[0])
        self.assertTrue(hint_due(hint,10301)[0])
        hint=hint_from_pair(pool(),10000,hint)
        self.assertEqual(hint['inactive_streak'],0)
        self.assertTrue(hint_due(hint,10016)[0])

    def test_fresh_buy_seed_wakes_inactive_but_not_known_old_pool(self):
        registry={'M':dict(last_seen=10000,seed_buys=2,seed_observed_at=10000)}
        inactive=hint_from_pair(pool(volume=0,buys=0),9900);inactive['inactive_streak']=4
        chosen,_=prioritized_watchlist(registry,{'M':inactive},0,10,10000)
        self.assertEqual(chosen,['M'])
        old=hint_from_pair(pool(age=80),9900)
        chosen,_=prioritized_watchlist(registry,{'M':old},0,10,10000)
        self.assertEqual(chosen,[])

    def test_new_active_addresses_before_known_inactive_fill(self):
        registry={'OLD':dict(last_seen=10000),'NEW':dict(last_seen=10000,seed_buys=1)}
        hints={'OLD':hint_from_pair(pool(volume=0,buys=0),9000)}
        chosen,_=prioritized_watchlist(registry,hints,0,1,10000)
        self.assertEqual(chosen,['NEW'])

    def test_spare_budget_does_not_fill_with_old_or_inactive_repeats(self):
        registry={m:dict(last_seen=10000) for m in ['new']+[f'old{i}' for i in range(20)]+[f'idle{i}' for i in range(10)]}
        registry['new']['seed_buys']=2
        hints={m:hint_from_pair(pool(age=80) if m.startswith('old') else pool(volume=0,buys=0),0) for m in registry if m!='new'}
        chosen,skipped=prioritized_watchlist(registry,hints,1,100,10000)
        self.assertEqual(len(chosen),3);self.assertIn('new',chosen)
        self.assertFalse(any(m.startswith('old') for m in chosen))
        self.assertEqual(sum(s['reason']=='old_pool_low_priority' for s in skipped),20)

    def test_new_pool_base_id_is_discovery_only_not_liquidity_or_age_proof(self):
        mint='1'*32
        data={'data':[{'attributes':{'transactions':{'m5':{'buys':15}},'reserve_in_usd':'99999999',
            'pool_created_at':'2026-10-31T22:00:00Z'},'relationships':{'base_token':{'data':{'id':'solana_'+mint}}}}]}
        with tempfile.TemporaryDirectory() as folder:
            store=PersistentPaperBot(Path(folder)/'s.sqlite3');reader=Reader(store)
            with patch.object(reader,'recent_tokens',return_value=[]),patch.object(reader,'new_pools',return_value=data),patch.object(reader,'market',return_value=[]):
                mints,_,audit=reader.discover(1,max_tokens=30,onchain_transactions=0)
            self.assertEqual(mints,[mint]);self.assertEqual(audit['new_unique_addresses'],1)
            seed=store.cache_get('watch',mint)
            self.assertEqual(seed['seed_buys'],15)
            self.assertNotIn('liquidity_usd',seed);self.assertNotIn('age_minutes',seed)
            self.assertIsNone(store.cache_get('birth',mint))
            with patch.object(reader,'recent_tokens',return_value=[]),patch.object(reader,'new_pools',return_value=data),patch.object(reader,'market',return_value=[]):
                self.assertEqual(reader.discover(2,30,0)[2]['new_unique_addresses'],0)
            store.close()

    def test_non_solana_base_id_is_not_imported(self):
        reader=Reader()
        with patch.object(reader,'recent_tokens',return_value=[]),patch.object(reader,'new_pools',return_value={'data':[{'relationships':{'base_token':{'data':{'id':'eth_'+'a'*40}}}}]}),patch.object(reader,'market',return_value=[]):
            self.assertEqual(reader.discover(1,30,0)[0],[])

    def test_null_transaction_is_retryable_not_permanently_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            store=PersistentPaperBot(Path(folder)/'s.sqlite3');reader=Reader(store)
            signature=dict(signature='SIG',slot=10,err=None)
            with patch.object(reader,'rpc',side_effect=[[signature],None]):
                self.assertIsNone(reader.mint_birth('M'))
            self.assertEqual(store.cache_get('birth_scan','M')['checked'],[])
            with patch.object(reader,'rpc') as rpc:
                self.assertIsNone(reader.mint_birth('M'));rpc.assert_not_called()
            future=time.time()+61
            with patch('solana_market_readonly.time.time',return_value=future),patch.object(reader,'rpc',return_value=tx()):
                self.assertEqual(reader.mint_birth('M')['signature'],'SIG')
            store.close()

    def test_init_after_first_page_budget_can_be_found_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            store=PersistentPaperBot(Path(folder)/'s.sqlite3');reader=Reader(store)
            pages=[[dict(signature=f'{n}_{i}',slot=10000-n*1000-i,err='failed') for i in range(1000)] for n in range(2)]
            with patch.object(reader,'rpc',side_effect=pages):self.assertIsNone(reader.mint_birth('M'))
            with patch.object(reader,'rpc',side_effect=[[dict(signature='SIG',slot=10,err=None)],tx()]):
                self.assertEqual(reader.mint_birth('M')['signature'],'SIG')
            self.assertEqual(store.cache_get('birth_scan','M')['pages'],3)
            store.close()

    def test_unavailable_transactions_do_not_starve_unchecked_init(self):
        with tempfile.TemporaryDirectory() as folder:
            store=PersistentPaperBot(Path(folder)/'s.sqlite3');reader=Reader(store)
            signatures=[dict(signature=s,slot=10 if s=='SIG' else n,err=None) for n,s in enumerate(['NULL1','NULL2','SIG'],1)]
            with patch.object(reader,'rpc',side_effect=[signatures,None,None]):self.assertIsNone(reader.mint_birth('M'))
            with patch('solana_market_readonly.time.time',return_value=time.time()+61),patch.object(reader,'rpc',return_value=tx()) as rpc:
                self.assertEqual(reader.mint_birth('M')['signature'],'SIG')
                self.assertEqual(rpc.call_args.args[1][0],'SIG')
            store.close()

    def test_position_exit_is_not_blocked_by_inactive_discovery_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'s.sqlite3';bot=PersistentPaperBot(path)
            bot.process(candidate('M',pair_address='PAIR_M'))
            hint=hint_from_pair(pool(age=80,volume=0,buys=0),time.time());hint['inactive_streak']=4
            bot.cache_put('market_hint','M',hint);bot.close()
            fake=Reader();fake.discover=lambda *args:([],[],{})
            fake.exit_route=lambda mint,quantity:dict(verified=True,observed_at=time.time())
            fake.market=lambda path:dict(pairs=[dict(chainId='solana',pairAddress='PAIR_M',
                baseToken=dict(address='M'),priceUsd='1.21')])
            args=SimpleNamespace(state_db=str(path),rounds=1,interval=5,max_tokens=30,onchain_transactions=0,
                                 max_security=1,output=str(Path(folder)/'out.json'))
            with patch('solana_market_readonly.Reader',return_value=fake),patch('builtins.print'):
                result=run(args)
            self.assertEqual(result['rounds'][0]['marks'][0]['outcome']['trigger'],'TP')
            self.assertEqual(result['summary']['position_price_checks'],1)
            self.assertEqual(result['summary']['open_positions'],{})


if __name__=='__main__':unittest.main(verbosity=2)
