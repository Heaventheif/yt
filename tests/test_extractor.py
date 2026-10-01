"""ترتيب محاولات يوتيوب: بلا كوكيز أولا (تبقي عملاء الصيغ المنفصلة)، ثم بالكوكيز كاحتياط."""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("WARMUP", "0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import extractor  # noqa: E402


def _fmt(fid, vcodec, acodec, ext="mp4", height=None):
    return {"format_id": fid, "url": "https://x/" + fid, "ext": ext, "protocol": "https", "vcodec": vcodec,
            "acodec": acodec, "height": height, "tbr": 1, "abr": 1, "filesize": 1, "filesize_approx": None,
            "http_headers": {}, "fps": 25}


WEAK = {"title": "t", "uploader": None, "duration": 1, "thumbnail": None, "extractor": "Youtube",
        "formats": [_fmt("18", "avc1", "mp4a", height=360)]}
RICH = {**WEAK, "formats": WEAK["formats"] + [_fmt("137", "avc1", "none", height=1080), _fmt("140", "none", "mp4a", "m4a")]}


class YoutubeAttempts(unittest.TestCase):
    def setUp(self):
        extractor._last_good_client = None
        self.calls = []

    def _run(self, results):
        """results: قائمة بما يرجعه كل استدعاء extract_raw (استثناء أو info)"""
        it = iter(results)

        def fake(url, clients=None, cookies=True):
            self.calls.append((clients, cookies))
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(extractor, "extract_raw", fake):
            return extractor._extract_youtube("https://www.youtube.com/watch?v=abcdefghijk")

    def test_order_starts_without_cookies(self):
        order = extractor._client_order()
        self.assertEqual(order[0], (["default", "android_vr"], False))
        self.assertEqual(order[1], (None, True))
        self.assertTrue(all(c for _, c in order[1:]))

    def test_no_cookiefile_when_cookies_disabled(self):
        with tempfile.NamedTemporaryFile() as tf, mock.patch.object(extractor, "COOKIES_PATH", tf.name):
            self.assertIn("cookiefile", extractor.ytdl_opts(cookies=True))
            self.assertNotIn("cookiefile", extractor.ytdl_opts(cookies=False))

    def test_first_attempt_rich_is_returned_once(self):
        self.assertIs(self._run([RICH]), RICH)
        self.assertEqual(self.calls, [(["default", "android_vr"], False)])

    def test_bot_check_falls_back_to_cookies(self):
        info = self._run([RuntimeError("Sign in to confirm you're not a bot"), RICH])
        self.assertIs(info, RICH)
        self.assertEqual(self.calls[1], (None, True))

    def test_weak_everywhere_returns_weak_after_all_attempts(self):
        n = len(extractor._client_order())
        self.assertIs(self._run([WEAK] * n), WEAK)
        self.assertEqual(len(self.calls), n)

    def test_weak_then_rich_prefers_rich(self):
        self.assertIs(self._run([WEAK, RICH]), RICH)


class RedirectResolution(unittest.TestCase):
    def test_facebook_share_is_resolved_before_extraction(self):
        share = "https://www.facebook.com/share/v/19Kaih4jUf/"
        reel = "https://www.facebook.com/reel/4527590257510541/"
        response = mock.MagicMock(status_code=302, headers={"Location": reel})
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with mock.patch.object(extractor.sess, "get", return_value=response), \
                mock.patch.object(extractor, "is_public_url", return_value=True):
            self.assertEqual(extractor._resolve_redirects(share), reel)

    def test_non_share_urls_are_not_requested(self):
        with mock.patch.object(extractor.sess, "get") as get:
            url = "https://www.facebook.com/reel/123/"
            self.assertEqual(extractor._resolve_redirects(url), url)
            get.assert_not_called()

    def test_private_redirect_falls_back_to_original(self):
        share = "https://www.facebook.com/share/v/abc/"
        response = mock.MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/"})
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with mock.patch.object(extractor.sess, "get", return_value=response), \
                mock.patch.object(extractor, "is_public_url", return_value=False):
            self.assertEqual(extractor._resolve_redirects(share), share)


if __name__ == "__main__":
    unittest.main()
