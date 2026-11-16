import copy
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import market_data as m
import narrative_v3 as n
import scanner_v2
import screening_rules as rules
from test_upgrade import pool,NOW,MINT,PAIR
from test_early_discovery import payload
from test_narrative_v3 import articles


def complete():
    p=pool();p['volume']['h1']=10000;return p


class MarketRepair(unittest.TestCase):
    def test_missing_hourly_volume_and_actual_cap_are_mandatory(self):
        p=complete();self.assertEqual(m.v3_missing_fields(p),[])
        p['volume'].pop('h1');p.pop('marketCap');p['fdv']=150000
        self.assertIn('volume.h1',m.v3_missing_fields(p));self.assertIn('marketCap',m.v3_missing_fields(p))
        self.assertIsNotNone(n.market_gate(p,NOW))
    def test_complete_gecko_replaces_fdv_only_dex_without_blending(self):
        dex=complete();dex.pop('marketCap');dex['volume']['m5']=999999
        gecko=dict(complete(),dataSource='geckoterminal');gecko['volume']['m5']=2222
        result=m.select_pool(dex,gecko)
        self.assertEqual(result['dataSource'],'geckoterminal');self.assertEqual(result['volume']['m5'],2222)
    def test_hourly_volume_missing_causes_snapshot_fallback(self):
        dex=complete();dex['volume'].pop('h1')
        gecko=dict(complete(),dataSource='geckoterminal')
        self.assertEqual(m.select_pool(dex,gecko)['dataSource'],'geckoterminal')
    def test_incomplete_sources_never_combined_into_fake_complete_snapshot(self):
        dex=complete();dex['priceChange'].pop('m5')
        gecko=dict(complete(),dataSource='geckoterminal');gecko.pop('marketCap');gecko['fdv']=150000
        result=m.select_pool(dex,gecko)
        self.assertTrue(m.v3_missing_fields(result));self.assertTrue(result.get('marketCap') is None or result['priceChange'].get('m5') is None)
    def test_later_incomplete_search_never_overwrites_good_discovery(self):
        bad=complete();bad.pop('marketCap');bad['volume']['m5']=999999
        result=m.merge_pools([complete(),bad])[0]
        self.assertEqual(result['marketCap'],150000);self.assertEqual(result['volume']['m5'],7000)
    def test_hydration_retries_present_pool_and_keeps_good_snapshot(self):
        p=complete();p['volume'].pop('h1')
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[complete()]}))
        gecko=SimpleNamespace(request=Mock(side_effect=AssertionError('no fallback needed')))
        rows,stats=m.hydrate_incomplete([p],api,gecko,NOW)
        self.assertEqual(stats['recovered'],1);self.assertFalse(m.v3_missing_fields(rows[0]));gecko.request.assert_not_called()
    def test_hydration_falls_back_to_coherent_gecko_and_rejects_wrong_identity(self):
        p=complete();p.pop('marketCap')
        body=payload();body['data'][0]['attributes']['market_cap_usd']='150000';body['data'][0]['attributes']['volume_usd']['h1']='10000'
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[]}))
        gecko=SimpleNamespace(request=Mock(return_value=body))
        rows,stats=m.hydrate_incomplete([p],api,gecko,NOW)
        self.assertEqual(stats['recovered'],1);self.assertEqual(rows[0]['dataSource'],'geckoterminal')
        body['included'][0]['attributes']['address']='C'*32
        rows,stats=m.hydrate_incomplete([p],api,gecko,NOW)
        self.assertEqual(stats['recovered'],0);self.assertIsNone(rows[0].get('marketCap'))
    def test_refresh_does_not_stop_at_fdv_only_snapshot(self):
        p=complete();p.pop('marketCap');p['fdv']=150000
        body=payload();body['data'][0]['attributes']['market_cap_usd']='150000';body['data'][0]['attributes']['volume_usd']['h1']='10000'
        api=SimpleNamespace(DEX='https://dex.example',request=Mock(return_value={'pairs':[p]}))
        gecko=SimpleNamespace(request=Mock(return_value=body))
        result=m.refresh_pool(PAIR,MINT,api,gecko)
        gecko.request.assert_called_once();self.assertEqual(result['marketCap'],150000)
    def test_new_trending_feed_finds_pool_outside_newest_pages(self):
        def request(url,*args):
            if 'trending_pools' in url:return payload()
            if '/latest/dex/pairs/' in url:return {'pairs':[]}
            return {'data':[]} if 'new_pools' in url else []
        api=SimpleNamespace(DEX='https://dex.example',request=request)
        pools,report=scanner_v2.discover(api)
        self.assertEqual(report['sources']['gecko_trending'],'ok');self.assertEqual(len(pools),1)


class NarrativeRepair(unittest.TestCase):
    def test_fivem_alias_requires_independent_current_gta_news(self):
        p=complete();p['baseToken'].update(name='GRAND THEFT CRYPTO',symbol='FiveM')
        self.assertIsNone(n.match(p,{'articles':articles()},NOW)['reject'])
        self.assertEqual(n.match(p,{'articles':[]},NOW)['reject'],'narrative_unverified')
    def test_queries_cover_canonical_topic_outside_top_five_and_aliases(self):
        topics=[{'label':x,'aliases':n.ALIASES.get(x,(x,)),'score':100,'sources':[]} for x in ('GTA','Minecraft','OpenAI','Gemini','Elon Musk','Anthropic')]
        f={'_prepared_trends':topics}
        queries=n.search_queries(f,NOW)
        self.assertIn('Anthropic',queries);self.assertIn('Rockstar',queries);self.assertIn('FiveM',queries)
        self.assertLessEqual(len(queries),12)
    def test_cyber_name_is_not_falsely_certified_by_a_generic_game_label(self):
        p=complete();p['baseToken'].update(name='Cyber Dacity Coin',symbol='CYBERDACITY')
        self.assertEqual(n.match(p,{'articles':articles()},NOW)['reject'],'narrative_unverified')

if __name__=='__main__':unittest.main()
