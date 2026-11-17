"""Regression tests for generic news fragments entering dynamic narrative search."""
import unittest
import global_intelligence as intel


class GenericHeadlineNoiseTests(unittest.TestCase):
    def test_generic_news_phrases_are_filtered_from_entities(self):
        rows=[{'title':'Former Robinhood Engineer Pleads Guilty in trading scheme - Example News'}]
        ai={'entities':['Former Robinhood','Robinhood Engineer Pleads','Pleads Guilty','November','Technology','Digital','Jensen Huang','NebulaFox']}
        labels=intel.entities(rows,ai)
        normalized={intel.normalize(x) for x in labels}
        for noise in ('former robinhood','robinhood engineer pleads','pleads guilty','november','technology','digital'):
            with self.subTest(noise=noise): self.assertNotIn(noise,normalized)
        self.assertIn('jensen huang',normalized)
        self.assertIn('nebulafx',normalized)

    def test_named_entity_is_not_removed_by_headline_verb_filter(self):
        for phrase in ('NVIDIA','Jensen Huang','NebulaFox','Grand Theft Auto'):
            with self.subTest(phrase=phrase): self.assertTrue(intel.entity_candidate(phrase))


if __name__=='__main__':
    unittest.main()
