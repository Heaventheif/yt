"""اختبارات سلوك API (black-box) — يجب أن تنجح قبل وبعد أي إعادة هيكلة.
تشغيل:  python -m unittest discover -s tests -v
"""
import os
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.update(API_KEY="k", WARMUP="0", WEB_PUBLIC="1", RATE_LIMIT_PER_MIN="4",
                  CHUNK_MB="0.25", KEEP_ALIVE_MINUTES="0", COOKIES_B64="", CORS_ORIGIN="https://example.com")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA = bytes((i * 31 + 7) % 256 for i in range(700_003))  # ~3 أجزاء بحجم 0.25MB


class FileServer(BaseHTTPRequestHandler):
    hits = 0
    fail_gets = 0      # عدد طلبات GET القادمة التي سترد 403

    def log_message(self, *a):
        pass

    def _send(self, code, a, b, headers_only):
        FileServer.hits += 1
        self.send_response(code)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(DATA)}")
        self.end_headers()
        if not headers_only:
            self.wfile.write(DATA[a:b + 1])

    def do_HEAD(self):
        self._send(200, 0, len(DATA) - 1, True)

    def do_GET(self):
        if FileServer.fail_gets > 0:
            FileServer.fail_gets -= 1
            FileServer.hits += 1
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if m:
            a = int(m[1])
            b = min(int(m[2]) if m[2] else len(DATA) - 1, len(DATA) - 1)
            self._send(206, a, b, False)
        else:
            self._send(200, 0, len(DATA) - 1, False)


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FileServer)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.src = f"http://127.0.0.1:{cls.srv.server_address[1]}/a.mp4"
        import app
        cls.c = app.app.test_client()
        cls.H = {"X-API-Key": "k"}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def fid(self):
        return self.get(f"/info?url={self.src}").json["video"][0]["fid"]

    def get(self, path, key=True, ip="1.1.1.1", **kw):
        h = dict(self.H) if key else {}
        h["X-Forwarded-For"] = ip
        h.update(kw.pop("headers", {}))
        return self.c.get(path, headers=h, **kw)

    # ---- عام ----
    def test_health_public(self):
        r = self.get("/health", key=False)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["ok"] and "yt_dlp" in r.json)

    def test_pages(self):
        for p in ("/", "/docs", "/encode"):
            self.assertEqual(self.get(p, key=False).status_code, 200, p)

    def test_auth(self):
        self.assertEqual(self.get(f"/info?url={self.src}", key=False).status_code, 401)
        self.assertEqual(self.get(f"/info?url={self.src}&key=k", key=False).status_code, 200)
        self.assertEqual(self.get(f"/info?url={self.src}&key=bad", key=False).status_code, 401)

    def test_bad_url(self):
        self.assertEqual(self.get("/info?url=notaurl").status_code, 400)
        self.assertEqual(self.get("/web/info?url=").status_code, 400)
        self.assertEqual(self.get("/web/dl?url=&fid=0").status_code, 400)
        self.assertEqual(self.get(f"/web/dl?url={self.src}&fid=a/b").status_code, 400)

    def test_cors(self):
        r = self.c.open("/info", method="OPTIONS", headers={"Origin": "https://example.com"})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "https://example.com")
        self.assertIn("X-API-Key", r.headers["Access-Control-Allow-Headers"])
        r = self.get(f"/info?url={self.src}")
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "https://example.com")
        self.assertIn("Content-Disposition", r.headers["Access-Control-Expose-Headers"])

    # ---- info / link ----
    def test_info_and_cache(self):
        r = self.get(f"/info?url={self.src}")
        self.assertEqual(r.status_code, 200)
        j = r.json
        self.assertTrue(j["ok"])
        self.assertEqual(len(j["video"]), 1)
        self.assertEqual(j["audio"], [])
        self.assertEqual(j["video"][0]["fid"], self.fid())
        before = FileServer.hits
        self.assertEqual(self.get(f"/info?url={self.src}").status_code, 200)
        self.assertEqual(FileServer.hits, before, "الطلب الثاني يجب أن يأتي من الكاش")

    def test_link(self):
        j = self.get(f"/link?url={self.src}&type=video&q=480").json
        self.assertTrue(j["ok"])
        self.assertEqual(j["url"], self.src)
        self.assertEqual(j["ext"], "mp4")

    def test_link_audio_missing(self):
        r = self.get(f"/link?url={self.src}&type=audio")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json["ok"])

    # ---- تنزيل ----
    def test_stream_full(self):
        r = self.get(f"/stream?url={self.src}&type=video&q=480")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(), DATA)
        self.assertEqual(r.headers["Content-Length"], str(len(DATA)))
        self.assertEqual(r.headers["Content-Type"], "video/mp4")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(r.headers["Accept-Ranges"], "bytes")

    def test_stream_range(self):
        r = self.get(f"/stream?url={self.src}", headers={"Range": "bytes=1000-299999"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.get_data(), DATA[1000:300000])
        self.assertEqual(r.headers["Content-Range"], f"bytes 1000-299999/{len(DATA)}")

    def test_stream_open_ended_range(self):
        r = self.get(f"/stream?url={self.src}", headers={"Range": "bytes=650000-"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.get_data(), DATA[650000:])

    def test_web_dl_check_and_unknown_fid(self):
        j = self.get(f"/web/dl?url={self.src}&fid={self.fid()}&check=1", key=False, ip="2.2.2.2").json
        self.assertEqual(j, {"ok": True, "size": len(DATA)})
        r = self.get(f"/web/dl?url={self.src}&fid=999", key=False, ip="2.2.2.3")
        self.assertEqual(r.status_code, 404)

    def test_web_dl_body(self):
        r = self.get(f"/web/dl?url={self.src}&fid={self.fid()}", key=False)
        self.assertEqual(r.get_data(), DATA)

    def test_stream_recovers_when_link_expires(self):
        """أول طلب للمصدر 403 => إعادة استخراج ثم نجاح"""
        self.fid()  # يملأ الكاش
        FileServer.fail_gets = 1
        r = self.get(f"/stream?url={self.src}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(), DATA)

    def test_stream_fails_when_source_keeps_refusing(self):
        self.fid()
        FileServer.fail_gets = 2
        r = self.get(f"/stream?url={self.src}")
        self.assertEqual(r.status_code, 502)
        self.assertIn("403", r.json["error"])
        FileServer.fail_gets = 0

    def test_slot_released_after_failures(self):
        """الخانات لا تتسرب: عدد كبير من الطلبات الفاشلة ثم نجاح"""
        for _ in range(8):  # أكثر من MAX_DOWNLOADS الافتراضي (6)
            FileServer.fail_gets = 2
            self.get(f"/stream?url={self.src}")
        FileServer.fail_gets = 0
        self.assertEqual(self.get(f"/stream?url={self.src}").status_code, 200)

    # ---- واجهة عامة + حد الطلبات ----
    def test_web_info_rate_limit(self):
        codes = [self.get(f"/web/info?url={self.src}", key=False, ip="9.9.9.9").status_code
                 for _ in range(6)]
        self.assertEqual(codes, [200, 200, 200, 200, 429, 429])
        # IP آخر غير متأثر
        self.assertEqual(self.get(f"/web/info?url={self.src}", key=False, ip="9.9.9.8").status_code, 200)


class UrlUtilsTest(unittest.TestCase):
    def test_cases(self):
        from url_utils import normalize_url as n
        cases = {
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&si=1": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?si=x": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abcDEF12345": "https://www.youtube.com/watch?v=abcDEF12345",
            "http://m.facebook.com/watch/?v=1&utm_source=x": "https://www.facebook.com/watch?v=1",
            "https://mobile.twitter.com/u/status/1?s=20": "https://x.com/u/status/1",
            "https://en.m.wikipedia.org/wiki/Cat": "https://en.wikipedia.org/wiki/Cat",
            "https://bit.ly/abc": "https://bit.ly/abc",
            "http://192.168.1.5:8080/a.mp4": "http://192.168.1.5:8080/a.mp4",
            "hello world": "hello world",
        }
        for src, want in cases.items():
            self.assertEqual(n(src, check_dns=False), want, src)


if __name__ == "__main__":
    unittest.main()
