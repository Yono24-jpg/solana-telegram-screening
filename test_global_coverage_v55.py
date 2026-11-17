"""Regression tests for bounded global-locale coverage and open-world news retrieval."""
import unittest
import global_intelligence as intel


class GlobalCoverageTests(unittest.TestCase):
    def test_twelve_locales_rotate_in_six_request_windows(self):
        first=intel.region_window(0)
        second=intel.region_window(300)
        repeated=intel.region_window(600)
        self.assertEqual(len(first),6)
        self.assertEqual(len(second),6)
        self.assertFalse({x[0] for x in first}&{x[0] for x in second})
        self.assertEqual({x[0] for x in first+second},{x[0] for x in intel.REGIONS})
        self.assertEqual({x[0] for x in first},{x[0] for x in repeated})

    def test_open_world_query_is_not_limited_to_known_categories(self):
        self.assertEqual(intel.news_query('US','open_world','trending viral news'),'when:2d')
        self.assertEqual(intel.news_query('DE','ai','artificial intelligence new technology'),
                         'artificial intelligence new technology when:2d')
        self.assertEqual(intel.news_query('CN','global','話題'),
                         '(話題) OR ('+intel.NATIVE_QUERIES['CN']+') when:2d')

    def test_locale_and_query_rotation_remain_bounded(self):
        for now in (0,300,600,900,1200):
            self.assertLessEqual(len(intel.region_window(now)),6)
            self.assertEqual(len({x[0] for x in intel.region_window(now)}),6)


if __name__=='__main__':
    unittest.main()
