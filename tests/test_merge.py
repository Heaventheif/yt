"""اختبارات دمج ffmpeg: وسائط حقيقية صغيرة تُقدَّم من مصدر محلي يدعم Range."""
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("API_KEY", "k")
for k, v in dict(ALLOW_PRIVATE_URLS="1", WARMUP="0", WEB_PUBLIC="1", CHUNK_MB="0.25", KEEP_ALIVE_MINUTES="0",
                 COOKIES_B64="", RATE_LIMIT_PER_MIN="1000").items():
    os.environ.setdefault(k, v)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import info_cache  # noqa: E402
import security  # noqa: E402
import merge  # noqa: E402
import streaming  # noqa: E402
from app import app  # noqa: E402
from formats import collect_options, pick_fid  # noqa: E402

FF = merge.ffmpeg_path()
FILES = {}


def _ff(*args):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _build_media(d):
    v = lambda *a: ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8", *a]
    s = lambda *a: ["-f", "lavfi", "-i", "sine=frequency=440:duration=8", *a]
    _ff(*v("-c:v", "libx264", "-b:v", "1500k", "-pix_fmt", "yuv420p", "-movflags", "+faststart", f"{d}/v.mp4"))
    _ff(*s("-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", f"{d}/a.m4a"))
    _ff(*v("-c:v", "libvpx-vp9", "-b:v", "800k", "-deadline", "realtime", "-cpu-used", "8", f"{d}/v.webm"))
    _ff(*s("-c:a", "libopus", "-b:a", "96k", f"{d}/a.webm"))
    for n in ("v.mp4", "a.m4a", "v.webm", "a.webm"):
        FILES[n] = open(f"{d}/{n}", "rb").read()


class Origin(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = FILES[self.path.lstrip("/")]
        m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        a, b = (int(m[1]), min(int(m[2]) if m[2] else len(data) - 1, len(data) - 1)) if m else (0, len(data) - 1)
        self.send_response(206 if m else 200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if m:
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
        self.end_headers()
        self.wfile.write(data[a:b + 1])


def _fmt(fid, name, ext, vcodec, acodec, height=None, tbr=0, abr=None, base=""):
    return {"format_id": fid, "url": f"{base}/{name}", "ext": ext, "protocol": "https", "vcodec": vcodec,
            "acodec": acodec, "height": height, "tbr": tbr, "abr": abr, "filesize": len(FILES[name]),
            "filesize_approx": None, "http_headers": {}, "fps": 25}


@unittest.skipUnless(FF, "ffmpeg غير متوفر")
class MergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _build_media(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.info = {"title": "فيديو/اختبار", "uploader": None, "duration": 8, "thumbnail": None, "extractor": "Youtube",
                    "formats": [
                        _fmt("18", "v.mp4", "mp4", "avc1.42001E", "mp4a.40.2", 360, 500, base=base),   # muxed (وهمي)
                        _fmt("136", "v.mp4", "mp4", "avc1.4d401f", "none", 720, 1500, base=base),
                        _fmt("247", "v.webm", "webm", "vp09.00.40.08", "none", 720, 800, base=base),
                        _fmt("140", "a.m4a", "m4a", "none", "mp4a.40.2", None, 128, 128, base=base),
                        _fmt("251", "a.webm", "webm", "none", "opus", None, 96, 96, base=base),
                    ]}
        cls._orig = info_cache.smart_extract
        info_cache.smart_extract = lambda url: cls.info
        cls.c = app.test_client()
        cls.q = "url=https://www.youtube.com/watch?v=abcdefghijk"

    @classmethod
    def tearDownClass(cls):
        info_cache.smart_extract = cls._orig
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        security._hits.clear()   # test_api يضبط حد معدل صغيرا؛ نصفّره لتبقى الاختبارات مستقلة

    def _probe(self, data, suffix):
        p = os.path.join(self.tmp.name, "out" + suffix)
        with open(p, "wb") as fh:
            fh.write(data)
        r = subprocess.run([FF, "-hide_banner", "-v", "error", "-i", p, "-f", "null", "-"], capture_output=True, text=True)
        meta = subprocess.run([FF, "-hide_banner", "-i", p], capture_output=True, text=True).stderr
        self.assertEqual(r.stderr.strip(), "", r.stderr)   # فك الترميز كاملا بلا أخطاء
        self.assertIn("Video:", meta)
        self.assertIn("Audio:", meta)

    def test_options_list(self):
        video, audio = collect_options(self.info)
        labels = [o["label"] for o in video]
        self.assertEqual([o["fid"] for o in video if o["height"] == 720], ["136+140", "247+251", "136", "247"][:2] + ["136", "247"])
        self.assertTrue(any("دمج" in l for l in labels))
        self.assertTrue(any("بدون صوت" in l for l in labels))
        self.assertEqual(video[-1]["fid"], "18")   # 360p الجاهزة تبقى مباشرة بلا دمج
        self.assertEqual({o["label"] for o in audio if not o.get("convert")}, {"M4A • 128kbps", "WEBM • 96kbps"})
        self.assertEqual([o["fid"] for o in audio if o.get("convert")], ["140+mp3_192", "140+mp3_128"])
        self.assertTrue(audio[0].get("convert"))   # MP3 أولا في تبويب الصوت
        self.assertEqual(pick_fid(self.info, "audio", None), "140")   # type=audio يبقى الصوت الأصلي بلا تحويل
        self.assertEqual(pick_fid(self.info, "mp3", "192"), "140+mp3_192")
        self.assertEqual(pick_fid(self.info, "mp3", None), "140+mp3_128")
        self.assertEqual(pick_fid(self.info, "video", "720"), "136+140")
        self.assertEqual(pick_fid(self.info, "video", "480"), "18")
        self.assertEqual(pick_fid(self.info, "video", "720", allow_merge=False), "18")

    def test_merge_mp4(self):
        r = self.c.get(f"/web/dl?{self.q}&fid=136%2B140")
        self.assertEqual(r.status_code, 200, r.data[:200])
        self.assertEqual(r.headers["Content-Type"], "video/mp4")
        self.assertIn(".mp4", r.headers["Content-Disposition"])
        self.assertNotIn("Content-Length", r.headers)
        self._probe(r.data, ".mp4")
        self.assertGreater(len(r.data), len(FILES["v.mp4"]))

    def test_merge_webm(self):
        r = self.c.get(f"/web/dl?{self.q}&fid=247%2B251")
        self.assertEqual(r.status_code, 200, r.data[:200])
        self.assertEqual(r.headers["Content-Type"], "video/webm")
        self._probe(r.data, ".webm")

    def test_check_reports_total_size(self):
        r = self.c.get(f"/web/dl?{self.q}&fid=136%2B140&check=1").get_json()
        self.assertTrue(r["ok"] and r["merged"])
        self.assertEqual(r["size"], len(FILES["v.mp4"]) + len(FILES["a.m4a"]))

    def test_api_stream_picks_merged_and_link_does_not(self):
        r = self.c.get(f"/stream?{self.q}&q=720", headers={"X-API-Key": "k"})
        self.assertEqual(r.status_code, 200)
        self._probe(r.data, ".mp4")
        j = self.c.get(f"/link?{self.q}&q=720", headers={"X-API-Key": "k"}).get_json()
        self.assertTrue(j["url"].endswith("/v.mp4") and "136" not in j["url"])

    def test_mp3_conversion(self):
        r = self.c.get(f"/web/dl?{self.q}&fid=140%2Bmp3_128")
        self.assertEqual(r.status_code, 200, r.data[:200])
        self.assertEqual(r.headers["Content-Type"], "audio/mpeg")
        self.assertIn(".mp3", r.headers["Content-Disposition"])
        p = os.path.join(self.tmp.name, "out.mp3")
        with open(p, "wb") as fh:
            fh.write(r.data)
        meta = subprocess.run([FF, "-hide_banner", "-i", p], capture_output=True, text=True).stderr
        self.assertIn("Audio: mp3", meta)
        self.assertNotIn("Video:", meta)
        self.assertRegex(meta, r"Duration: 00:00:0[78]")             # مدة الأصل ~8 ثوان
        self.assertIn("title", meta)                                  # ID3 title
        self.assertRegex(meta, r"128 kb/s")

    def test_mp3_from_webm_opus_and_api_type_mp3(self):
        r = self.c.get(f"/stream?{self.q}&type=mp3&q=192", headers={"X-API-Key": "k"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "audio/mpeg")
        self.assertGreater(len(r.data), 100_000)   # 8s × 192kbps ≈ 190KB
        self.assertEqual(self.c.get(f"/link?{self.q}&type=mp3", headers={"X-API-Key": "k"}).status_code, 404)

    def test_mp3_rejects_unlisted_bitrate(self):
        self.assertEqual(self.c.get(f"/web/dl?{self.q}&fid=140%2Bmp3_320").status_code, 404)
        j = self.c.get(f"/web/dl?{self.q}&fid=140%2Bmp3_128&check=1").get_json()
        self.assertTrue(j["ok"], j)

    def test_bad_pair_and_cleanup_on_disconnect(self):
        self.assertEqual(self.c.get(f"/web/dl?{self.q}&fid=136%2B999").status_code, 404)
        before_mux, before_dl = merge.MUX_SLOTS._value, streaming.DL_SLOTS._value
        procs, orig = [], merge.start_job

        def spy(*a):
            res = orig(*a)
            procs.append(res[0])
            return res
        merge.start_job = spy
        try:
            r = self.c.get(f"/web/dl?{self.q}&fid=136%2B140", buffered=False)
            next(iter(r.response))   # بدأ التدفق
            r.close()                # العميل انقطع قبل الانتهاء
        finally:
            merge.start_job = orig
        for _ in range(50):
            if merge.MUX_SLOTS._value == before_mux and streaming.DL_SLOTS._value == before_dl:
                break
            threading.Event().wait(0.1)
        self.assertEqual(merge.MUX_SLOTS._value, before_mux)
        self.assertEqual(streaming.DL_SLOTS._value, before_dl)
        self.assertEqual(len(procs), 1)
        self.assertIsNotNone(procs[0].poll(), "ffmpeg لم يُنهَ بعد انقطاع العميل")

if __name__ == "__main__":
    unittest.main()
