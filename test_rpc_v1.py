"""V1-only RPC regressions: compatibility must not bypass evidence gates."""
import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chain_intelligence as chain
import bot
import data_intelligence as di
import evidence
import security_v3
import test_market_intelligence_v54 as protocol
import test_narrative_v3 as security_fixtures
from test_global_v5 import market_pool
from test_upgrade import MINT, NOW, pool


def require_v1(params):
    if params[-1].get('maxSupportedTransactionVersion') != 1:
        raise di.Unavailable('rpc_transaction_version_unsupported')
    if params[-1].get('encoding') != 'jsonParsed':
        raise di.Unavailable('expected_resolved_accounts')


class TransactionV1(unittest.TestCase):
    def test_creation_discovery_reads_v1_and_preserves_unverified_status(self):
        spec = next(r for r in chain.LAYOUTS if r['protocol'] == 'pumpswap' and r['name'] == 'create_pool')
        tx = protocol.creation(spec)
        tx['version'] = 1
        tx['transaction']['message']['transactionConfig'] = {'computeUnitLimit': 200000}

        def rpc(method, params):
            if method == 'getSignaturesForAddress':
                return [{'signature': protocol.SIG, 'blockTime': NOW-120, 'err': None}]
            require_v1(params)
            return copy.deepcopy(tx)

        providers = SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None), rpc=rpc)
        rows, stats, _, leads = chain.discover(providers, {}, NOW)
        self.assertEqual(stats['transaction_reads'], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(leads), 1)
        self.assertNotIn('liquidity', rows[0])
        self.assertIn('no market or safety assertion', rows[0]['discoveryEvidence']['scope'])
        tx['meta']['err'] = {'InstructionError': [0, 'InvalidArgument']}
        self.assertEqual(chain.discover(providers, {}, NOW)[0], [])

    def test_v1_reserve_sample_is_still_partial_and_wrong_mint_is_refused(self):
        p = market_pool()
        p.update(pairAddress=protocol.PAIR, dexId='pumpswap',
                 baseToken={'address': protocol.MINT}, quoteToken={'address': protocol.QUOTE})
        tx = protocol.swap_tx()
        tx['version'] = 1

        def rpc(method, params):
            if method == 'getSignaturesForAddress':
                return [{'signature': protocol.SIG, 'blockTime': NOW-120, 'err': None}]
            require_v1(params)
            return copy.deepcopy(tx)

        provider = SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None), rpc=rpc)
        result = chain.sample_market(provider, [p], NOW)
        self.assertEqual(result['buys'], 1)
        self.assertIsNone(result['usd_volume'])
        self.assertFalse(result['complete_window'])
        tx['meta']['postTokenBalances'][0]['mint'] = protocol.QUOTE
        self.assertEqual(chain.sample_market(provider, [p], NOW)['trades'], [])

    def test_v1_developer_outflow_stays_rejected(self):
        tx = {'version': 1, 'meta': {'err': None, 'preTokenBalances': [
            {'mint': MINT, 'owner': security_fixtures.CREATOR, 'uiTokenAmount': {'amount': '100'}}],
            'postTokenBalances': []}}

        def rpc(_api, method, params):
            if method == 'getTokenAccountsByOwner': return {'value': []}
            if method == 'getSignaturesForAddress':
                return [{'signature': 'oldest', 'blockTime': NOW-20, 'err': None}]
            require_v1(params)
            return tx

        with patch.object(evidence, 'rpc', side_effect=rpc):
            result = security_v3.developer_check(security_fixtures.report(), Mock(), NOW)
        self.assertEqual(result['reject'], 'developer_recent_token_outflow')

    def test_v1_sell_evidence_checks_signers_and_proceeds(self):
        buyers, txs = security_fixtures.Security().sample()
        for tx in txs.values(): tx['version'] = 1

        def rpc(_api, method, params):
            require_v1(params)
            return txs[params[0]]

        with patch.object(evidence, 'rpc', side_effect=rpc):
            result = security_v3.transaction_sample(pool(), buyers, Mock(), NOW)
            self.assertEqual(result['finalized_sells'], 3)
            next(iter(txs.values()))['meta']['postBalances'][0] = 90
            with self.assertRaisesRegex(ValueError, 'sell_proceeds_unverified'):
                security_v3.transaction_sample(pool(), buyers, Mock(), NOW)

    def test_v1_mint_proof_still_requires_initializing_the_exact_mint(self):
        tx = {'version': 1, 'blockTime': NOW-700, 'meta': {'err': None}, 'transaction': {
            'message': {'instructions': [{'programId': 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
                'parsed': {'type': 'initializeMint2', 'info': {'mint': MINT}}}]}}}

        def rpc(_api, method, params):
            if method == 'getSignaturesForAddress': return [{'signature': 'oldest', 'err': None}]
            require_v1(params)
            return tx

        with patch.object(evidence, 'rpc', side_effect=rpc):
            self.assertTrue(evidence.mint_creation(MINT, bot, NOW)['verified'])
            tx['transaction']['message']['instructions'][0]['parsed']['info']['mint'] = 'D'*32
            self.assertFalse(evidence.mint_creation(MINT, bot, NOW)['verified'])

    def test_v1_shared_direct_funder_remains_rejected(self):
        buyers, txs = security_fixtures.Security().sample()
        source = 'Z'*32

        def rpc(_api, method, params):
            if method == 'getSignaturesForAddress':
                sig = next(k for k, tx in txs.items()
                           if tx['transaction']['message']['accountKeys'][0]['pubkey'] == params[0])
                return [{'signature': sig, 'blockTime': NOW-10, 'err': None}]
            require_v1(params)
            tx = copy.deepcopy(txs[params[0]])
            tx['version'] = 1
            message = tx['transaction']['message']
            wallet = message['accountKeys'][0]['pubkey']
            message['accountKeys'].append({'pubkey': source, 'signer': True})
            message['instructions'].append({'programId': '1'*32, 'parsed': {'type': 'transfer',
                'info': {'source': source, 'destination': wallet, 'lamports': 100}}})
            return tx

        with patch.object(evidence, 'rpc', side_effect=rpc):
            result = security_v3.funding_check(security_fixtures.report(), buyers, Mock(), NOW)
        self.assertEqual(result['reject'], 'shared_direct_funder_pattern')

    def test_unsupported_future_versions_remain_unavailable_and_do_not_leak_messages(self):
        api = SimpleNamespace(REQUEST_DEADLINE=None, request=Mock(return_value={
            'error': {'code': -32015, 'message': 'secret-url-and-key'}}))
        with patch.dict(os.environ, {'HELIUS_API_KEY': '', 'SOLANA_RPC_URL': ''}):
            client = di.Client(api, {})
            with self.assertRaises(di.Unavailable):
                client.rpc('getTransaction', ['signature', {'encoding': 'jsonParsed',
                    'commitment': 'finalized', 'maxSupportedTransactionVersion': 1}])
        self.assertEqual(client.status['solana_rpc']['status'], 'rpc_transaction_version_unsupported')
        self.assertEqual(client.usage()['rpc_errors_by_code'], {'solana_rpc': {'-32015': 1}})
        self.assertNotIn('secret', str(client.status)+str(client.usage()))

    def test_finalized_jsonparsed_legacy_v0_v1_responses_keep_cache_identity(self):
        for version in ('legacy', 0, 1):
            api = SimpleNamespace(REQUEST_DEADLINE=None, request=Mock(return_value={
                'result': {'version': version, 'slot': 123, 'meta': {'err': None}}}))
            with self.subTest(version=version), patch.dict(os.environ, {'HELIUS_API_KEY': '', 'SOLANA_RPC_URL': ''}):
                client = di.Client(api, {})
                args = ['signature', {'encoding': 'jsonParsed', 'commitment': 'finalized',
                                      'maxSupportedTransactionVersion': 1}]
                self.assertEqual(client.rpc('getTransaction', args)['version'], version)
                client.rpc('getTransaction', args)
                self.assertEqual(api.request.call_count, 1)
