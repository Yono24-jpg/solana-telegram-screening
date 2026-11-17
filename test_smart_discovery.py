import copy
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch
import market_data as market
import smart_discovery as smart
import state_store
import hunter_modes
from test_global_v5 import market_pool
from test_upgrade import NOW
from vault_checks import b58encode

PAIR = b58encode(bytes([11])*32)
MINT = b58encode(bytes([12])*32)
QUOTE = 'So11111111111111111111111111111111111111112'
SIG = b58encode(bytes([13])*64)


def transaction():
    keys = [b58encode(bytes([i+1])*32) for i in range(20)]
    keys[3:6] = [PAIR, MINT, QUOTE]
    keys[12] = smart.FEE
    return {'blockTime': NOW-120, 'meta': {'err': None, 'innerInstructions': []},
            'transaction': {'signatures': [SIG], 'message': {'instructions': [
                {'programId': smart.CPMM, 'accounts': keys, 'data': b58encode(smart.INIT+bytes(24))}]}}}


class OnChain(unittest.TestCase):
    def test_exact_initialize_has_no_market_or_security_claim(self):
        p = smart.parse_initialize(transaction(), SIG, NOW)[0]
        self.assertEqual((p['pairAddress'], p['baseToken']['address']), (PAIR, MINT))
        self.assertTrue(market.v3_missing_fields(p))
        self.assertEqual(hunter_modes.assess(p, {}, NOW, {})['reject'], 'v5_market_missing')
        self.assertNotIn('marketCap', p)

    def test_spoofed_program_discriminator_fee_signature_and_failed_tx_rejected(self):
        for field in ('program', 'data', 'fee', 'signature', 'failed', 'future', 'old', 'key', 'short'):
            tx = transaction(); ix = tx['transaction']['message']['instructions'][0]
            if field == 'program': ix['programId'] = MINT
            if field == 'data': ix['data'] = b58encode(bytes(32))
            if field == 'fee': ix['accounts'][12] = MINT
            if field == 'signature': tx['transaction']['signatures'] = []
            if field == 'failed': tx['meta']['err'] = {'InstructionError': [0, 'error']}
            if field == 'future': tx['blockTime'] = NOW+1
            if field == 'old': tx['blockTime'] = NOW-3601
            if field == 'key': ix['accounts'][3] = 'A'*32
            if field == 'short': ix['accounts'] = ix['accounts'][:13]
            with self.subTest(field=field): self.assertEqual(smart.parse_initialize(tx, SIG, NOW), [])

    def test_inner_instruction_and_quote_orientation(self):
        tx = transaction(); ix = tx['transaction']['message']['instructions'].pop()
        ix['accounts'][4:6] = [QUOTE, MINT]
        tx['meta']['innerInstructions'] = [{'index': 0, 'instructions': [ix]}]
        self.assertEqual(smart.parse_initialize(tx, SIG, NOW)[0]['baseToken']['address'], MINT)

    def provider(self):
        signatures = [{'signature': SIG, 'blockTime': NOW-120, 'err': None}]
        return SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None),
            rpc=Mock(side_effect=lambda method, params: signatures if method == 'getSignaturesForAddress' else transaction()))

    def test_signature_cache_survives_merge_and_does_not_refetch_transaction(self):
        provider = self.provider(); state = {}
        leads, stats = smart.rpc_discover(provider, state, NOW)
        self.assertEqual(len(leads), 1); self.assertEqual(stats['transaction_reads'], 1)
        state = state_store.merge({}, state, NOW+1)
        _, stats = smart.rpc_discover(provider, state, NOW+1)
        self.assertEqual(stats['transaction_reads'], 0); self.assertEqual(stats['cache_hits'], 1)
        self.assertEqual(provider.rpc.call_count, 3)

    def test_missing_tx_retries_later_without_marking_complete(self):
        provider = self.provider(); original = provider.rpc.side_effect
        provider.rpc.side_effect = lambda m, p: original(m, p) if m == 'getSignaturesForAddress' else None
        state = {}; _, stats = smart.rpc_discover(provider, state, NOW)
        self.assertEqual(stats['status'], 'partial_transaction_unavailable')
        self.assertFalse(state[smart.STATE_KEY]['signatures'][SIG]['done'])
        _, stats = smart.rpc_discover(provider, state, NOW+1)
        self.assertEqual(stats['transaction_reads'], 0)
        provider.rpc.side_effect = original
        leads, _ = smart.rpc_discover(provider, state, NOW+300)
        self.assertEqual(len(leads), 1)

    def test_expired_deadline_never_calls_rpc(self):
        provider = self.provider(); provider.api.REQUEST_DEADLINE = 1
        with patch.object(smart.time, 'monotonic', return_value=2):
            _, stats = smart.rpc_discover(provider, {}, NOW)
        provider.rpc.assert_not_called(); self.assertEqual(stats['status'], 'deadline')

    def test_read_limit_caps_at_six(self):
        provider = self.provider()
        provider.rpc.side_effect = lambda m,p: ([{'signature': b58encode(bytes([i])*64),
            'blockTime': NOW-60, 'err': None} for i in range(1, 30)] if m == 'getSignaturesForAddress' else transaction())
        _, stats = smart.rpc_discover(provider, {}, NOW, max_transactions=100)
        self.assertEqual(stats['transaction_reads'], 6)


class Queue(unittest.TestCase):
    def partial(self, pair=PAIR, age=600):
        p = market_pool(age); p['pairAddress'] = pair; p['baseToken']['address'] = MINT
        p['priceChange']['m5'] = None
        return p

    def test_absent_queue_retains_only_identity_never_stale_market_values(self):
        state = {}; p = self.partial(); smart.prepare([p], state, NOW)
        merged = state_store.merge({}, state, NOW+1)
        rows = smart.prepare([], merged, NOW+300)
        self.assertEqual(len(rows), 1)
        for key in ('priceUsd', 'liquidity', 'volume', 'marketCap', 'txns', 'priceChange'):
            self.assertNotIn(key, rows[0])

    def test_young_first_and_request_only_updates_due_records(self):
        old = self.partial(b58encode(bytes([15])*32), 7200); young = self.partial()
        state = {}; rows = smart.prepare([old, young], state, NOW)
        api = SimpleNamespace(DEX='https://dex.example', REQUEST_DEADLINE=None,
                              request=Mock(return_value={'pairs': []}))
        gecko = SimpleNamespace(state=state, request=Mock(return_value={'data': []}))
        with patch.object(market.time, 'time', return_value=NOW):
            _, stats = smart.recover(rows, state, api, gecko, NOW)
        self.assertEqual(stats['selected_young'], 1)
        first_url = api.request.call_args_list[0].args[0]
        self.assertLess(first_url.index(PAIR), first_url.index(old['pairAddress']))
        self.assertEqual(state[smart.STATE_KEY]['queue'][PAIR]['next_at'], NOW+295)
        self.assertEqual(state[smart.STATE_KEY]['queue'][old['pairAddress']]['next_at'], NOW+895)
        api.request.reset_mock()
        with patch.object(market.time, 'time', return_value=NOW+1):
            _, stats = smart.recover(rows, state, api, gecko, NOW+1)
        api.request.assert_not_called(); self.assertEqual(stats['due'], 0)

    def test_deadline_preserves_queue_rotation(self):
        state = {}; rows = smart.prepare([self.partial()], state, NOW)
        api = SimpleNamespace(DEX='https://dex.example', REQUEST_DEADLINE=1, request=Mock())
        gecko = SimpleNamespace(state=state, request=Mock())
        with patch.object(market.time, 'monotonic', return_value=2):
            smart.recover(rows, state, api, gecko, NOW)
        self.assertNotIn('last_attempt', state[smart.STATE_KEY]['queue'][PAIR])
        api.request.assert_not_called()

    def test_wrong_mint_response_cannot_recover(self):
        p = self.partial(); donor = copy.deepcopy(p); donor['priceChange']['m5'] = 1
        donor['baseToken']['address'] = QUOTE; state = {}; rows = smart.prepare([p], state, NOW)
        api = SimpleNamespace(DEX='https://dex.example', REQUEST_DEADLINE=None,
                              request=Mock(return_value={'pairs': [donor]}))
        gecko = SimpleNamespace(state=state, request=Mock(return_value={'data': []}))
        with patch.object(market.time, 'time', return_value=NOW):
            result, stats = smart.recover(rows, state, api, gecko, NOW)
        self.assertTrue(market.v3_missing_fields(result[0])); self.assertGreater(stats['identity_rejections'], 0)

    def test_same_cohort_denominator_and_missing_pool_do_not_disappear(self):
        p = self.partial(); full = copy.deepcopy(p); full['priceChange']['m5'] = 1
        state = {}; smart.cohort_start(state, [p], NOW)
        out = smart.comparison(state, [p], [full], NOW)
        self.assertEqual(out['paired']['recovered'], 1); self.assertEqual(out['fixed']['current_complete'], 1)
        smart.cohort_start(state, [market_pool()], NOW+300)
        out = smart.comparison(state, [], [], NOW+300)
        self.assertEqual(out['fixed']['total'], 1); self.assertEqual(out['fixed']['absent'], 1)
        self.assertEqual(out['fixed']['current_complete'], 0)

    def test_queue_and_signature_state_are_bounded_and_expire(self):
        state = {}; pools = [self.partial(b58encode(i.to_bytes(32, 'big'))) for i in range(1, 401)]
        smart.prepare(pools, state, NOW)
        self.assertEqual(len(state[smart.STATE_KEY]['queue']), 300)
        smart.state_for(state, NOW+86401)
        self.assertEqual(state[smart.STATE_KEY]['queue'], {})


class GeckoPolicy(unittest.TestCase):
    def test_smart_cap_is_five_actual_calls_with_12_second_spacing(self):
        api = SimpleNamespace(request=Mock(return_value={'data': []}))
        state = {}
        clock = [NOW]
        sleeps = []
        def sleep(delay):
            sleeps.append(delay)
            clock[0] += delay
        client = market.GeckoClient(api, state, paced=True, smart=True)
        with patch.object(market.time, 'time', side_effect=lambda: clock[0]), \
             patch.object(market.time, 'sleep', side_effect=sleep):
            for _ in range(5): client.request(market.GECKO+'/test')
            with self.assertRaisesRegex(RuntimeError, 'gecko_free_budget'):
                client.request(market.GECKO+'/test')
        self.assertEqual(api.request.call_count, 5)
        self.assertEqual(sleeps, [12, 12, 12, 12])
        self.assertEqual(len(state['gecko_requests']), 5)
        self.assertTrue(all(b-a >= 12 for a,b in zip(state['gecko_requests'], state['gecko_requests'][1:])))

    def test_429_exponential_backoff_survives_merge(self):
        api = SimpleNamespace(request=Mock(side_effect=urllib.error.HTTPError('hidden',429,'rate',{},None)))
        state = {}
        for offset, delay in [(0,300), (301,600), (902,1200)]:
            with patch.object(market.time, 'time', return_value=NOW+offset):
                with self.assertRaises(urllib.error.HTTPError):
                    market.GeckoClient(api, state, smart=True).request(market.GECKO+'/test')
            self.assertEqual(state['gecko_retry_after'], NOW+offset+delay)
            state = state_store.merge({}, state, NOW+offset)
            self.assertEqual(state['gecko_retry_after'], NOW+offset+delay)


if __name__ == '__main__': unittest.main()
