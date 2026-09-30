import unittest

from extractor import ytdl_opts


class ExtractorOptionsTest(unittest.TestCase):
    def test_dash_is_not_skipped(self):
        skipped = ytdl_opts()["extractor_args"]["youtube"]["skip"]
        self.assertIn("hls", skipped)
        self.assertNotIn("dash", skipped)


if __name__ == "__main__":
    unittest.main()
