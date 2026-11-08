"""Regression tests for optional social evidence in strong-signal classification."""
import unittest
from unittest.mock import patch
from screening_rules import choose_tier


class OptionalSocialTests(unittest.TestCase):
    def setUp(self):
        self.market = {'strong': True, 'age_seconds': 600}
        self.security = {'complete': True, 'score': 90}
        self.buyers = {'strong': True}
        self.mint_age = {'verified': True, 'age_seconds': 660}

    def classify(self, social):
        with patch('screening_rules.evidence_rejection', return_value=None):
            return choose_tier(self.market, self.security, social, self.buyers, self.mint_age)

    def test_unavailable_social_does_not_block_strong(self):
        self.assertEqual('STRONG SIGNAL', self.classify({'complete': False, 'score': None, 'risks': []}))

    def test_verified_weak_social_downgrades(self):
        self.assertEqual('EARLY WATCH', self.classify({'complete': True, 'score': 45, 'risks': []}))

    def test_social_risk_downgrades(self):
        self.assertEqual('EARLY WATCH', self.classify({'complete': False, 'score': None, 'risks': ['identity_conflict']}))

    def test_verified_strong_social(self):
        self.assertEqual('STRONG SIGNAL', self.classify({'complete': True, 'score': 90, 'risks': []}))


if __name__ == '__main__':
    unittest.main()
