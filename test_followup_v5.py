"""Production regressions: nonzero evaluator budget and source-bound multilingual names."""
import copy
import unittest
from unittest.mock import Mock,patch
import bot
import hunter_memory
import global_intelligence as intel
import scanner_v2
from test_global_v5 import market_pool,articles
from test_upgrade import MINT,PAIR,NOW


def memory(at=NOW-300):
    return {'memory_v5':{'one':{'at':at,'mint':MINT,'pair':PAIR,'price':1,'samples':{}}}}


class ForwardEvaluation(unittest.TestCase):
    def test_current_quote_evaluated_inside_twenty_second_budget(self):
        state=memory();api=Mock()
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=100):
            result=hunter_memory.followup(state,[market_pool()],api,None,120)
        self.assertEqual(state['memory_v5']['one']['samples']['300']['status'],'observed')
        self.assertEqual(state['memory_v5']['one']['samples']['300']['at'],NOW)
        self.assertEqual(result['quote_attempts'],0);api.request.assert_not_called()
    def test_missing_quotes_batched_and_identity_bound(self):
        state=memory();api=Mock();api.DEX=bot.DEX;api.request.return_value={'pairs':[market_pool()]}
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=100):
            result=hunter_memory.followup(state,[],api,None,120)
        self.assertEqual(result['quotes_recovered'],1);self.assertIn('300',state['memory_v5']['one']['samples'])
        bad=market_pool();bad['baseToken']['address']='C'*32;api.request.return_value={'pairs':[bad]};state=memory()
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=100):
            result=hunter_memory.followup(state,[],api,None,120)
        self.assertEqual(result['quotes_recovered'],0);self.assertNotIn('300',state['memory_v5']['one']['samples'])
    def test_late_windows_mark_missed_even_when_budget_exhausted(self):
        state=memory(NOW-2000);api=Mock()
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=121):
            hunter_memory.followup(state,[],api,None,120)
        self.assertEqual(state['memory_v5']['one']['samples']['300']['status'],'missed')
        self.assertEqual(state['memory_v5']['one']['samples']['900']['status'],'missed')
        api.request.assert_not_called()
    def test_failed_quote_does_not_starve_later_records(self):
        state=memory();state['memory_v5']['one']['last_quote_attempt_at']=NOW-60
        state['memory_v5']['two']={'at':NOW-300,'mint':'D'*32,'pair':'E'*32,'price':1,'samples':{}}
        api=Mock();api.DEX=bot.DEX;api.request.return_value={'pairs':[]}
        with patch.object(hunter_memory.time,'time',return_value=NOW),patch.object(hunter_memory.time,'monotonic',return_value=100):
            result=hunter_memory.followup(state,[],api,None,120)
        self.assertEqual(result['quote_attempts'],2)
        self.assertEqual(state['memory_v5']['two']['last_quote_attempt_at'],NOW)
    def test_legacy_performance_gets_a_usable_budget(self):
        r={'at':NOW-300,'mint':MINT,'pair':PAIR,'price':1,'samples':{}}
        api=Mock();api.REQUEST_DEADLINE=110
        with patch.object(scanner_v2.time,'monotonic',return_value=100),patch.object(scanner_v2.time,'time',return_value=NOW):
            scanner_v2.followup({'performance':{'one':r}},[market_pool()],api,NOW,reserve_seconds=1)
        self.assertIn('300',r['samples'])


class SourceQuality(unittest.TestCase):
    def test_publisher_suffix_does_not_create_entity(self):
        rows=articles();rows[0]['title']='New game event - NebulaFox Press';rows[1]['title']='Different movie - NebulaFox News'
        self.assertNotIn('NebulaFox',[t['label'] for t in intel.trends(rows,{},NOW)])
    def test_subdomains_are_one_publisher_not_two(self):
        rows=articles();rows[0]['publisher_host']='chinanews.com.cn';rows[1]['publisher_host']='gs.chinanews.com.cn'
        self.assertEqual(intel.trends(rows,{},NOW),[])
        self.assertEqual(intel.publisher_family('finance.sina.cn'),'sina.cn')
    def test_cjk_substrings_are_not_entities(self):
        rows=articles();rows[0]['title']='ゲームの歴史について紹介';rows[1]['title']='ブームが静かに広がる'
        self.assertNotIn('ーム',intel.entities(rows));self.assertNotIn('ーム',[t['label'] for t in intel.trends(rows,{},NOW)])
    def test_quoted_cjk_names_remain_dynamic(self):
        rows=articles();rows[0]['title']='新作「未来猫」が発表';rows[1]['title']='話題の「未来猫」が発売'
        self.assertIn('未来猫',[t['label'] for t in intel.trends(rows,{},NOW)])
    def test_generic_terms_social_and_download_spam_not_corroboration(self):
        rows=articles('Gameplay');self.assertEqual(intel.trends(rows,{},NOW),[])
        rows=articles();rows[1]['publisher_host']='x.com';self.assertEqual(intel.trends(rows,{},NOW),[])
        rows=articles();rows[1]['title']='NebulaFox full video twitter download'
        self.assertEqual(intel.trends(rows,{},NOW),[])
