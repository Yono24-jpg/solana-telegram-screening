"""Priority/scheduling and complete security-stage regressions; no network."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from sniper_discovery_policy import pool_priority,source_schedule,hint_from_pair,hint_due,prioritized_watchlist
from solana_market_readonly import Reader,TOKEN_PROGRAM,TOKEN_2022,transaction_proof,verify_stages,market_assessment
from sniper_runtime import PersistentPaperBot
from solana_sniper_paper import candidate
from test_sniper_runtime import tx


def pool(name='P',age=10,volume=1800,buys=18,sells=12,liquidity=12000,now=10000):
    return dict(pairAddress=name,pairCreatedAt=(now-age*60)*1000,liquidity=dict(usd=liquidity),
                volume=dict(m5=volume),txns=dict(m5=dict(buys=buys,sells=sells)))


class DiscoveryTests(unittest.TestCase):
    def test_young_active_before_old_despite_old_high_liquidity(self):
        young=pool('young');old=pool('old',age=80,liquidity=1000000)
        self.assertLess(pool_priority(young,10000),pool_priority(old,10000))

    def test_market_pass_before_young_inactive_or_missing_liquidity(self):
        self.assertLess(pool_priority(pool(),10000),pool_priority(pool(volume=0,buys=0),10000))
        self.assertLess(pool_priority(pool(),10000),pool_priority(pool(liquidity=None),10000))

    def test_priority_does_not_prove_mint_age_or_allow_unknown_data(self):
        checks,reasons=market_assessment(candidate(liquidity_usd=None))
        self.assertIn('liquidity_usd_unavailable',reasons)
        self.assertEqual(checks['mint_age']['status'],'not_checked')
        # A young pool may belong to an old mint; final proof still rejects it.
        reader=Reader();reader.security=Mock(return_value=self.security())
        reader.mint_birth=Mock(return_value=dict(block_time=time.time()-7200,signature='OLD'))
        checks,_=market_assessment(candidate())
        _,_,reasons,_=verify_stages(reader,'M',checks)
        self.assertIn('age_minutes',reasons)

    @staticmethod
    def security(owner=TOKEN_PROGRAM,mint_revoked=True,freeze_revoked=True):
        return dict(verified=owner==TOKEN_PROGRAM,authority_data_verified=True,
                    mint_revoked=mint_revoked,freeze_revoked=freeze_revoked,
                    raw=dict(owner=owner),extension_audit=dict(verified=owner==TOKEN_PROGRAM),observed_at=time.time())

    def test_token2022_unknown_extensions_rejected_even_with_valid_age_and_revocations(self):
        reader=Reader();reader.security=Mock(return_value=self.security(TOKEN_2022))
        reader.mint_birth=Mock(return_value=dict(block_time=time.time()-600,signature='INIT2022'))
        checks,_=market_assessment(candidate())
        _,_,reasons,errors=verify_stages(reader,'M',checks)
        self.assertEqual(reasons,['extensions_unverified'])
        self.assertEqual(errors,[])
        self.assertEqual(checks['mint_age']['status'],'pass')
        self.assertTrue(all(checks[k]['attempted'] for k in ('mint_age','mint_authority','freeze_authority','token_program')))
        reader.mint_birth.assert_called_once_with('M',program_id=TOKEN_2022)

    def test_authority_failures_do_not_skip_age_attempt(self):
        reader=Reader();reader.security=Mock(return_value=self.security(mint_revoked=False,freeze_revoked=False))
        reader.mint_birth=Mock(return_value=dict(block_time=time.time()-600,signature='INIT'))
        checks,_=market_assessment(candidate())
        _,_,reasons,_=verify_stages(reader,'M',checks)
        self.assertIn('mint_revoked',reasons);self.assertIn('freeze_revoked',reasons)
        reader.mint_birth.assert_called_once()

    def test_unknown_age_never_passes_and_api_errors_mark_stages_unavailable(self):
        reader=Reader();reader.security=Mock(side_effect=RuntimeError('RPC_error_-1'))
        reader.mint_birth=Mock(return_value=None)
        checks,_=market_assessment(candidate())
        _,_,reasons,errors=verify_stages(reader,'M',checks)
        self.assertIn('mint_age_unverified',reasons)
        self.assertIn('mint_authority_unverified',reasons)
        self.assertEqual(errors[0]['stage'],'account_state')
        self.assertTrue(all(checks[k]['attempted'] for k in ('mint_age','mint_authority','freeze_authority','token_program')))

    def test_age_rpc_failure_is_recorded_without_masking_token2022(self):
        reader=Reader();reader.security=Mock(return_value=self.security(TOKEN_2022))
        reader.mint_birth=Mock(side_effect=RuntimeError('RPC_error_-2'))
        checks,_=market_assessment(candidate())
        _,_,reasons,errors=verify_stages(reader,'M',checks)
        self.assertIn('extensions_unverified',reasons)
        self.assertIn('mint_age_unverified',reasons)
        self.assertEqual(errors[0]['stage'],'mint_initialization')

    def test_token2022_age_proof_requires_explicit_program_and_matching_signature(self):
        data=tx(program=TOKEN_2022)
        self.assertIsNone(transaction_proof(data,'M','SIG'))
        proof=transaction_proof(data,'M','SIG',TOKEN_2022)
        self.assertEqual(proof['program_id'],TOKEN_2022)
        self.assertIsNone(transaction_proof(data,'M','OTHER',TOKEN_2022))

    def test_old_cooldown_does_not_invent_freshness(self):
        hint=hint_from_pair(pool(age=70),10000)
        self.assertEqual(hint_due(hint,10015),(False,'old_pool_cooldown'))
        self.assertTrue(hint_due(hint,11801)[0])
        self.assertEqual(hint['inspected_at'],10000)

    def test_cooldown_and_hints_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.sqlite3'
            bot=PersistentPaperBot(path);bot.cache_put('market_hint','old',hint_from_pair(pool(age=70),10000));bot.close()
            bot=PersistentPaperBot(path)
            self.assertFalse(hint_due(bot.cache_get('market_hint','old'),10015)[0]);bot.close()

    def test_unseen_reserve_and_known_old_are_not_lexical_priority(self):
        now=10000
        registry={name:dict(last_seen=now,first_seen=now) for name in ('AAA_old','ZZZ_young','NEW_unseen')}
        hints={'AAA_old':hint_from_pair(pool(age=70),now),'ZZZ_young':hint_from_pair(pool(),now-20)}
        chosen,skipped=prioritized_watchlist(registry,hints,0,2,now)
        self.assertEqual(set(chosen),{'ZZZ_young','NEW_unseen'})
        self.assertEqual(skipped,[dict(mint='AAA_old',reason='old_pool_cooldown')])

    def test_primary_feed_always_polled_slow_sources_are_occasional(self):
        for index in range(12):
            sources=source_schedule(index)
            self.assertIn('/token-profiles/latest/v1',sources)
            self.assertFalse(any(q in sources for q in ('/latest/dex/search?q=SOL','/latest/dex/search?q=USDC','/latest/dex/search?q=Raydium')))
        self.assertGreater(len(source_schedule(0)),len(source_schedule(1)))

    def test_pending_verification_prioritized_before_rechecking_completed_peer(self):
        registry={m:dict(first_seen=10000,last_seen=10000) for m in ('pending','checked')}
        hints={'pending':hint_from_pair(pool(volume=1800),9980),'checked':hint_from_pair(pool(volume=100000),9980)}
        hints['pending']['verification_attempt']=0;hints['checked']['verification_attempt']=9990
        chosen,_=prioritized_watchlist(registry,hints,0,1,10000)
        self.assertEqual(chosen,['pending'])

    def test_cached_token2022_birth_cannot_be_reused_as_legacy_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            store=PersistentPaperBot(Path(folder)/'state.sqlite3')
            proof=transaction_proof(tx(program=TOKEN_2022),'M','SIG',TOKEN_2022)
            store.cache_put('birth','M',proof)
            reader=Reader(store)
            with self.assertRaises(RuntimeError):reader.mint_birth('M')
            with patch.object(reader,'rpc') as rpc:
                self.assertEqual(reader.mint_birth('M',TOKEN_2022)['program_id'],TOKEN_2022)
                rpc.assert_not_called()
            store.close()


if __name__=='__main__':unittest.main(verbosity=2)
