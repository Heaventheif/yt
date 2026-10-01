"""اختبارات الترقية: أمان، ETag، كاش بالبايت، فك الروابط، الواجهة الثابتة، حدود الحجم."""
import os
import sys
import unittest
from unittest import mock

os.environ.update(API_KEY="k", ALLOW_PRIVATE_URLS="1", WARMUP="0", WEB_PUBLIC="1", RATE_LIMIT_PER_MIN="50",
                  KEEP_ALIVE_MINUTES="0", COOKIES_B64="", CORS_ORIGIN="https://example.com", TRUSTED_PROXY_HOPS="1",
                  DL_RATE_LIMIT_PER_MIN="3")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import app as appmod  # noqa: E402
import info_cache  # noqa: E402
from formats import detail_options  # noqa: E402
from url_utils import normalize_url, unwrap_url  # noqa: E402

INFO = {"title": "t", "uploader": "u", "duration": 10, "thumbnail": "https://i.ytimg.com/vi/x/hq.jpg", "extractor": "Youtube",
        "formats": [
            {"format_id": "18", "url": "http://x/a", "ext": "mp4", "protocol": "https", "vcodec": "avc1.42", "acodec": "mp4a", "height": 360, "tbr": 500, "filesize": 1000},
            {"format_id": "137", "url": "http://x/b", "ext": "mp4", "protocol": "https", "vcodec": "av01.0", "acodec": "none", "height": 1080, "fps": 60, "tbr": 4000, "filesize": 9000},
            {"format_id": "140", "url": "http://x/c", "ext": "m4a", "protocol": "https", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128, "tbr": 128, "filesize": 500},
            {"format_id": "hls", "url": "http://x/d.m3u8", "ext": "mp4", "protocol": "m3u8_native", "vcodec": "avc1", "acodec": "mp4a", "height": 720}]}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = appmod.app.test_client()

    def get(self, path, ip="5.5.5.5", **kw):
        h = {"X-Forwarded-For": ip}
        h.update(kw.pop("headers", {}))
        return self.c.get(path, headers=h, **kw)


class SecurityTests(Base):
    def setUp(self):
        # الإعدادات تُقرأ عند أول استيراد (قد يسبقنا test_api)، لذا نثبّتها صراحة هنا
        for target, val in (("app.DL_RATE_LIMIT", 3), ("security.TRUSTED_PROXY_HOPS", 1)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def test_security_headers_and_csp(self):
        r = self.get("/")
        self.assertEqual(r.status_code, 200)
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("unsafe-inline", self.get("/docs").headers["Content-Security-Policy"])

    def test_index_has_no_inline_script_or_style(self):
        html = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotIn("<style", html)
        self.assertNotRegex(html, r"\son\w+=")

    def test_xff_spoofing_cannot_bypass_limits(self):
        """مع TRUSTED_PROXY_HOPS=1 يُؤخذ آخر عنوان (يضيفه الوسيط الموثوق) لا الأول المزوَّر."""
        codes = [self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1&check=1", headers={"X-Forwarded-For": f"9.9.9.{i}, 7.7.7.7"}).status_code
                 for i in range(6)]
        self.assertIn(429, codes)

    def test_dl_rate_limited_but_range_chunks_not_counted(self):
        for _ in range(3):
            self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1", ip="6.6.6.6")
        self.assertEqual(self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1", ip="6.6.6.6").status_code, 429)
        r = self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1", ip="6.6.6.6")
        self.assertEqual(r.headers.get("Retry-After"), "60")
        mid = self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1", ip="6.6.6.6", headers={"Range": "bytes=4194304-8388607"})
        self.assertNotEqual(mid.status_code, 429)

    def test_rate_buckets_are_independent(self):
        for _ in range(4):
            self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=1", ip="6.6.6.7")
        self.assertNotEqual(self.get("/web/info?url=http://127.0.0.1:1/a.mp4", ip="6.6.6.7").status_code, 429)

    def test_url_validation(self):
        base = "/web/info?url="
        self.assertEqual(self.get(base + "https://example.com/" + "a" * 2100).status_code, 400)
        self.assertEqual(self.get(base + "https://user:pw@example.com/v").status_code, 400)
        self.assertEqual(self.get(base + "https://example.com/%00x").status_code, 400)
        self.assertEqual(self.get("/web/dl?url=http://127.0.0.1:1/a.mp4&fid=" + "1" * 41, ip="4.4.4.4").status_code, 400)

    def test_key_query_toggle(self):
        with mock.patch("security.ALLOW_KEY_QUERY", False):
            self.assertEqual(self.get("/info?url=http://127.0.0.1:1/a&key=k").status_code, 401)
        self.assertNotEqual(self.get("/info?url=http://127.0.0.1:1/a", headers={"X-API-Key": "k"}).status_code, 401)

    def test_thumb_proxy_rejects_private_and_bad_input(self):
        with mock.patch("app.is_public_url", return_value=False):
            self.assertEqual(self.get("/web/thumb?u=http://10.0.0.1/x.jpg").status_code, 400)
        self.assertEqual(self.get("/web/thumb?u=file:///etc/passwd").status_code, 400)

    def test_telemetry_whitelist(self):
        import observability
        before = observability.snapshot().get("dl_ok", {"n": 0})["n"]
        self.c.post("/web/telemetry", data='[{"e":"dl_ok","v":1},{"e":"evil","v":9},{"e":"dl_ok","x":1}]',
                    headers={"X-Forwarded-For": "3.3.3.3"})
        self.assertEqual(observability.snapshot()["dl_ok"]["n"], before + 1)
        self.assertNotIn("evil", observability.snapshot())
        self.assertEqual(self.c.post("/web/telemetry", data="{{bad", headers={"X-Forwarded-For": "3.3.3.4"}).status_code, 204)

    def test_metrics_requires_key(self):
        self.assertEqual(self.get("/metrics").status_code, 401)
        self.assertEqual(self.get("/metrics", headers={"X-API-Key": "k"}).status_code, 200)


class InfoEtagTests(Base):
    def test_etag_304_and_thumbnail_rewrite_and_detail(self):
        with mock.patch("app.get_info", return_value=INFO):
            r = self.get("/web/info?url=https://www.youtube.com/watch?v=abcdefghijk", ip="2.1.1.1")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json["thumbnail"].startswith("/web/thumb?u="))
            self.assertIsNone(r.json["detail"])
            self.assertIn("max-age", r.headers["Cache-Control"])
            tag = r.headers["ETag"]
            again = self.get("/web/info?url=https://www.youtube.com/watch?v=abcdefghijk", ip="2.1.1.1", headers={"If-None-Match": tag})
            self.assertEqual(again.status_code, 304)
            d = self.get("/web/info?url=https://www.youtube.com/watch?v=abcdefghijk&detail=all", ip="2.1.1.1").json["detail"]
            self.assertEqual({x["fid"] for x in d}, {"18", "137", "140"})   # HLS مستبعد

    def test_detail_options_shape(self):
        rows = detail_options(INFO)
        top = rows[0]
        self.assertEqual((top["fid"], top["codec"], top["fps"], top["kind"]), ("137", "AV1", 60, "video"))
        self.assertEqual(rows[-1]["kind"], "audio")


class PlaylistTests(Base):
    def test_pagination(self):
        page = {"title": "L", "count": 60, "items": [{"id": str(i)} for i in range(25)]}
        with mock.patch("app.get_playlist", return_value=page) as gp:
            j = self.get("/web/playlist?list=PLabcdefghijk&cursor=0&limit=25", ip="8.1.1.1").json
            self.assertEqual(j["next_cursor"], "25")
            gp.assert_called_with("PLabcdefghijk", 0, 25)
        last = {"title": "L", "count": 30, "items": [{"id": "z"}] * 5}
        with mock.patch("app.get_playlist", return_value=last):
            self.assertIsNone(self.get("/web/playlist?list=PLabcdefghijk&cursor=25&limit=25", ip="8.1.1.2").json["next_cursor"])
        self.assertEqual(self.get("/web/playlist?list=bad", ip="8.1.1.3").status_code, 400)
        self.assertEqual(self.get("/web/playlist?list=PLabcdefghijk&cursor=x", ip="8.1.1.4").status_code, 400)


class ByteCacheTests(unittest.TestCase):
    def test_byte_cap_and_lru(self):
        c = info_cache.ByteTTLCache(60, 1000, 600)
        blob = {"x": "a" * 190}                                     # ≈ 200 بايت لكل عنصر
        for k in "abcd":
            c.put(k, blob)
        self.assertLessEqual(c.bytes, 600)
        self.assertIsNone(c.get("a"))                               # الأقدم أُخلي
        self.assertIsNotNone(c.get("d"))
        c.put("d", blob)                                            # استبدال لا يضاعف العدّ
        self.assertLessEqual(c.bytes, 600)

    def test_ttl_expiry_releases_bytes(self):
        c = info_cache.ByteTTLCache(0, 10, 10_000)
        c.put("a", {"x": 1})
        self.assertIsNone(c.get("a"))
        self.assertEqual(c.bytes, 0)


class DeepLinkTests(unittest.TestCase):
    CASES = {
        "https://www.google.com/url?q=https%3A%2F%2Fyoutu.be%2FdQw4w9WgXcQ&sa=D": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "شاهد هذا https://youtu.be/dQw4w9WgXcQ?si=abc الآن.": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "vnd.youtube://dQw4w9WgXcQ": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "intent://www.youtube.com/watch?v=dQw4w9WgXcQ#Intent;scheme=https;package=com.google.android.youtube;end": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/attribution_link?a=x&u=/watch%3Fv%3DdQw4w9WgXcQ%26feature%3Dshare": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/redirect?q=https%3A%2F%2Fvimeo.com%2F123&event=x": "https://vimeo.com/123",
        "https://m.youtube.com/shorts/abcDEF12345": "https://www.youtube.com/watch?v=abcDEF12345",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDx": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }

    def test_corpus(self):
        for src, want in self.CASES.items():
            self.assertEqual(normalize_url(unwrap_url(src), check_dns=False), want, src)

    def test_unwrap_is_bounded(self):
        loop = "https://www.google.com/url?q=" + "https%3A%2F%2Fwww.google.com%2Furl%3Fq%3D" * 6 + "x"
        unwrap_url(loop)   # لا يدور إلى ما لا نهاية


class StaticTests(Base):
    def test_static_assets_and_sw_headers(self):
        sw = self.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw.headers["Cache-Control"], "no-cache")
        self.assertEqual(sw.headers["Service-Worker-Allowed"], "/")
        for p in ("/static/app.js", "/static/app.css", "/static/ledger.js", "/manifest.webmanifest"):
            self.assertEqual(self.get(p).status_code, 200, p)
        self.assertEqual(self.get("/share?t=hello%20https://youtu.be/x").status_code, 303)

    def test_shell_budget(self):
        """الواجهة المخزّنة مسبقا يجب أن تبقى تحت حصة SHELL (8MB) من ميزانية 500MB."""
        total = sum(os.path.getsize(os.path.join(ROOT, "static", f)) for f in os.listdir(os.path.join(ROOT, "static")))
        self.assertLess(total, 8_000_000)
        self.assertLess(total, 150_000)   # ميزانية JS/CSS الفعلية: صغيرة جدا


if __name__ == "__main__":
    unittest.main()
