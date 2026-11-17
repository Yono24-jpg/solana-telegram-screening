"""Regression tests for the final-edition bounded coverage fixes."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import chain_intelligence as chain
import data_intelligence as di
from test_market_intelligence_v54 import MINT, PAIR, QUOTE, SIG, creation
from test_upgrade import NOW
from vault_checks import b58encode


class FinalEditionCoverage(unittest.TestCase):
    def test_all_supported_creation_indexes_are_sampled_each_cycle(self):
        calls = []

        def rpc(method, params):
            calls.append((method, params))
            if method == 'getSignaturesForAddress':
                return []
            raise AssertionError(method)

        providers = SimpleNamespace(api=SimpleNamespace(REQUEST_DEADLINE=None), rpc=rpc)
        _, stats, _, _ = chain.discover(providers, {}, NOW)
        self.assertEqual(stats['signature_reads'], 4)
        self.assertEqual(set(stats['source_order']),
                         {'pump', 'pumpswap', 'raydium', 'meteora'})
        self.assertEqual(set(stats['sources']),
                         {'pump', 'pumpswap', 'raydium', 'meteora'})

    def test_jupiter_cap_batch_uses_documented_100_mint_limit(self):
        api = SimpleNamespace(request=Mock(return_value=[]), REQUEST_DEADLINE=None)
        client = di.Client(api, {})
        mints = [b58encode(bytes([index + 1]) * 32) for index in range(100)]
        with patch.dict(os.environ, {'JUPITER_API_KEY': ''}):
            client.token_rows(mints)
        self.assertEqual(api.request.call_count, 1)
        query = parse_qs(urlsplit(api.request.call_args[0][0]).query)['query'][0]
        self.assertEqual(len(query.split(',')), 100)

    def test_meteora_swap_sample_is_exact_and_stays_out_of_usd_claims(self):
        spec = next(row for row in chain.LAYOUTS
                    if row['protocol'] == 'meteora' and row['name'] == 'swap')
        tx = creation(spec)
        accounts = tx['transaction']['message']['instructions'][0]['accounts']
        roles = dict(zip(spec['accounts'], range(len(accounts))))
        def balances(base, quote):
            return [
                {'accountIndex': roles['token_a_vault'], 'mint': MINT,
                 'uiTokenAmount': {'amount': str(base), 'decimals': 6}},
                {'accountIndex': roles['token_b_vault'], 'mint': QUOTE,
                 'uiTokenAmount': {'amount': str(quote), 'decimals': 9}},
            ]
        tx['meta'].update(preTokenBalances=balances(1_000_000_000, 10_000_000_000),
                          postTokenBalances=balances(900_000_000, 11_000_000_000))
        result = chain.reserve_trade(tx, SIG,
                                     {'pairAddress': PAIR,
                                      'baseToken': {'address': MINT},
                                      'quoteToken': {'address': QUOTE}}, NOW)
        self.assertEqual(result['protocol'], 'meteora')
        self.assertEqual(result['kind'], 'buy')
        self.assertNotIn('usd', result)
        self.assertNotIn('volume_usd', result)


if __name__ == '__main__':
    unittest.main()
