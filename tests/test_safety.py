"""اختبارات الأمان: SSRF، اختيار IP، حدود لكل IP، تنظيف اسم الملف."""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("WARMUP", "0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
import streaming
from url_safety import is_public_url


class UrlSafety(unittest.TestCase):
    def test_blocks_internal_targets(self):
        with mock.patch.object(config, "ALLOW_PRIVATE_URLS", False):
            for u in ("http://127.0.0.1:4416/get_pot", "http://localhost/", "http://169.254.169.254/latest/meta-data",
                      "http://10.0.0.5/x", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "file:///etc/passwd", "ftp://a.b/c"):
                self.assertFalse(is_public_url(u), u)

    def test_allows_public_ip(self):
        with mock.patch.object(config, "ALLOW_PRIVATE_URLS", False):
            self.assertTrue(is_public_url("https://1.1.1.1/x"))

    def test_allowlist(self):
        with mock.patch.object(config, "ALLOWED_HOSTS", ["youtube.com"]), mock.patch.object(config, "ALLOW_PRIVATE_URLS", True):
            self.assertTrue(is_public_url("https://www.youtube.com/watch?v=abc"))
            self.assertFalse(is_public_url("https://evil-youtube.com/"))


class PerIpSlots(unittest.TestCase):
    def test_per_ip_cap_and_release(self):
        with mock.patch.object(streaming, "PER_IP_STREAMS", 2):
            a, b = streaming.acquire_slot("9.9.9.9"), streaming.acquire_slot("9.9.9.9")
            self.assertIsNotNone(a and b)
            self.assertIsNone(streaming.acquire_slot("9.9.9.9"))
            other = streaming.acquire_slot("8.8.8.8")
            self.assertIsNotNone(other)
            a.release(); a.release()   # تحرير مزدوج لا يكسر العدّاد
            c = streaming.acquire_slot("9.9.9.9")
            self.assertIsNotNone(c)
            for s in (b, c, other):
                s.release()
            self.assertEqual(streaming._ip_active, {})


if __name__ == "__main__":
    unittest.main()
