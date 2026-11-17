"""Regression tests for honest social-source availability and paid X read policy."""
import os
import urllib.error
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import evidence
import social_intelligence as social
from test_upgrade import NOW, MINT


class SocialAvailabilityTests(unittest.TestCase):
    def setUp(self): self.api=SimpleNamespace(REQUEST_DEADLINE=None, DEX='https://api.dexscreener.com')

    def test_successful_empty_bluesky_search_is_not_reported_as_observed_posts(self):
        with patch.object(evidence,'public_read',return_value={'posts':[]}):
            result=social.sample(self.api,'novel trend',MINT,NOW)
        self.assertEqual(result['search_status'],'ok')
        self.assertEqual(result['status'],'no_matching_posts')
        self.assertEqual(result['unique_authors'],0)
        self.assertEqual(result['posts'],[])

    def test_forbidden_search_with_empty_public_author_fallback_is_not_a_hit(self):
        did='did:plc:'+'a'*24
        def public_read(url,api):
            if 'feed.searchPosts' in url: raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
            if 'actor.searchActors' in url: return {'actors':[{'did':did}]}
            if 'feed.getAuthorFeed' in url: return {'feed':[]}
            raise AssertionError('unexpected endpoint')
        with patch.object(evidence,'public_read',side_effect=public_read):
            result=social.sample(self.api,'novel trend',MINT,NOW)
        self.assertEqual(result['search_status'],'authentication_required_or_forbidden')
        self.assertEqual(result['author_feeds_read'],1)
        self.assertEqual(result['status'],'no_matching_posts')
        self.assertEqual(result['contract_mentions'],0)

    def test_contract_discovery_reports_empty_sample_separately(self):
        empty={'status':'no_matching_posts','posts':[],'search_status':'authentication_required_or_forbidden',
               'scope':'up to 2 query-matched public author feeds; selection biased','author_feeds_read':2,
               'unique_authors':0,'contract_mentions':0}
        with patch.object(social,'sample',return_value=empty):
            pools,report=social.discover_contracts(self.api,{'trends':[{'label':'novel trend'}]},NOW)
        self.assertEqual(pools,[])
        self.assertEqual(report['status'],'sampled_no_matching_posts')
        self.assertEqual(report['sources'],{'novel trend':'no_matching_posts'})

    def test_x_bearer_present_but_paid_reads_disabled_makes_zero_requests(self):
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'placeholder-not-a-real-secret','X_READS_ENABLED':'0'}):
            with patch.object(evidence,'public_read') as request:
                result=evidence.x_analysis('influencer',MINT,self.api,NOW)
        request.assert_not_called()
        self.assertEqual(result['status'],'reads_disabled_paid_policy')
        self.assertFalse(result['complete'])

    def test_missing_x_bearer_is_reported_without_request(self):
        with patch.dict(os.environ,{'X_BEARER_TOKEN':'','X_READS_ENABLED':'0'}):
            with patch.object(evidence,'public_read') as request:
                result=evidence.x_analysis('influencer',MINT,self.api,NOW)
        request.assert_not_called()
        self.assertEqual(result['status'],'token_missing')


if __name__=='__main__': unittest.main()
