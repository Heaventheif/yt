"""نقاط النهاية (Routes) فقط. المنطق موزع على الوحدات:
config · errors · net · formats · extractor · info_cache · streaming · serving · security · keepalive
"""
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from functools import wraps

import yt_dlp
from flask import Flask, Response, g, jsonify, request

import keepalive
from config import CORS_ORIGIN, LINK_CACHE_MAX, LINK_CACHE_SEC, WARMUP, WEB_PUBLIC
from cookies_util import COOKIE_STATS
from extractor import warmup
from formats import get_fmt, info_payload, pick_fid
from info_cache import get_info, remember_original
from pages import DOCS_HTML, ENCODE_HTML, WEB_HTML
from responses import err, jerr
from security import auth_ok, rate_ok
from config import API_RATE_LIMIT
from metrics import record, snapshot
from serving import serve
from url_utils import normalize_url

app = Flask(__name__)

# روابط yt-dlp المباشرة موقعة وقصيرة العمر؛ الاحتفاظ بها لفترة قصيرة يمنع
# إعادة بناء نفس استجابة /link عندما يطلبها البوت أكثر من مرة خلال ثوانٍ.
_link_cache = OrderedDict()
_link_cache_lock = threading.Lock()


def _cached_link(key):
    now = time.time()
    with _link_cache_lock:
        item = _link_cache.get(key)
        if not item:
            return None
        if item[0] <= now:
            _link_cache.pop(key, None)
            return None
        _link_cache.move_to_end(key)
        return item[1]


def _store_link(key, value):
    with _link_cache_lock:
        _link_cache[key] = (time.time() + LINK_CACHE_SEC, value)
        _link_cache.move_to_end(key)
        while len(_link_cache) > LINK_CACHE_MAX:
            _link_cache.popitem(last=False)

PUBLIC_PATHS = ("/", "/health", "/ping", "/stats", "/repo", "/docs", "/encode")
FID_PATTERN = re.compile(r"^[\w.\-+]+$")
_HTTP_URL = re.compile(r"^https?://")


# ------------------------- أدوات الطلب -------------------------
def valid_url():
    """الرابط من ?url= بعد تطبيعه، أو None إن لم يكن رابط http(s)"""
    raw = request.args.get("url", "").strip()
    url = normalize_url(raw)
    if url != raw and _HTTP_URL.match(raw):
        remember_original(url, raw)
    return url if _HTTP_URL.match(url) else None


def with_url(missing_msg="url مطلوب"):
    """يمرر الرابط الصالح للدالة، ويحوّل أي استثناء إلى رد JSON"""
    def decorator(fn):
        @wraps(fn)
        def wrapper():
            url = valid_url()
            if not url:
                return jerr(missing_msg, 400)
            try:
                return fn(url)
            except Exception as e:
                return err(e)
        return wrapper
    return decorator


def _pick(url):
    """(info, fid) حسب type و q في الطلب"""
    info = get_info(url)
    return info, pick_fid(info, request.args.get("type", "video"), request.args.get("q"))


# ------------------------- الحماية -------------------------
@app.before_request
def timing_start():
    g.started_at = time.perf_counter()

@app.before_request
def guard():
    if request.method == "OPTIONS":  # طلب CORS التمهيدي لا يحمل المفتاح
        return Response(status=204)
    p = request.path
    if p in PUBLIC_PATHS:
        return None
    if p.startswith("/web/"):
        if not WEB_PUBLIC:
            return jerr("الواجهة العامة معطلة", 404)
        if (p == "/web/info" or request.args.get("check")) and not rate_ok():
            return jerr("طلبات كثيرة، انتظر دقيقة ثم حاول مجددا", 429)
        return None
    if not auth_ok():
        return jerr("unauthorized", 401)
    # API المفتاح لا ينبغي أن يتجاوز طبقة الحماية؛ نستخدم حداً منفصلاً عن الواجهة العامة.
    if p in ("/info", "/link", "/stream") and not rate_ok(API_RATE_LIMIT):
        return jerr("طلبات كثيرة، انتظر دقيقة ثم حاول مجددا", 429)


@app.after_request
def collect_metrics(resp):
    record(request.path, resp.status_code, time.perf_counter() - getattr(g, "started_at", time.perf_counter()))
    return resp

@app.after_request
def cors(resp):
    if CORS_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "X-API-Key, Range"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length, Content-Range, Accept-Ranges"
    return resp


# ------------------------- صفحات -------------------------
@app.get("/")
def index():
    return Response(WEB_HTML if WEB_PUBLIC else DOCS_HTML, mimetype="text/html")


@app.get("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html")


@app.get("/encode")
def encode_page():
    return Response(ENCODE_HTML, mimetype="text/html")


@app.get("/health")
def health():
    return jsonify(ok=True, yt_dlp=yt_dlp.version.__version__, service="ytdlp-api")

@app.get("/ping")
def ping():
    started = time.perf_counter()
    # لا نلمس المصدر الخارجي؛ هذا يقيس زمن استجابة التطبيق نفسه.
    return jsonify(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 2),
                   server_time=int(time.time()))

@app.get("/stats")
def stats():
    return jsonify(snapshot())

@app.get("/repo")
def repo():
    def run(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=os.path.dirname(__file__),
                                           text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""
    return jsonify(ok=True, name="Heaventheif/yt", branch=run("branch", "--show-current"),
                   commit=run("rev-parse", "--short", "HEAD"),
                   updated=run("log", "-1", "--format=%cI"),
                   url="https://github.com/Heaventheif/yt")


@app.get("/cookies")
def cookies_status():
    yt = any(d.endswith(("youtube.com", "google.com")) for d in COOKIE_STATS["domains"])
    return jsonify(ok=True, has_youtube=yt, **COOKIE_STATS)


# ------------------------- واجهة عامة -------------------------
@app.get("/web/info")
@with_url("الرابط غير صحيح")
def web_info(url):
    payload = info_payload(get_info(url))
    if not payload["video"] and not payload["audio"]:
        return jerr("لا توجد صيغ قابلة للتنزيل المباشر لهذا الرابط", 404)
    return jsonify(payload)


@app.get("/web/dl")
@with_url("طلب غير صحيح")
def web_dl(url):
    fid = request.args.get("fid", "")
    if not FID_PATTERN.match(fid):
        return jerr("طلب غير صحيح", 400)
    return serve(url, fid, check=bool(request.args.get("check")))


# ------------------------- API بمفتاح (للبوت) -------------------------
@app.get("/info")
@with_url()
def api_info(url):
    return jsonify(info_payload(get_info(url)))


@app.get("/link")
@with_url()
def api_link(url):
    kind = request.args.get("type", "video").lower()
    quality = request.args.get("q", "")
    cache_key = (url, kind, quality)
    cached = _cached_link(cache_key)
    if cached:
        response = jsonify(cached)
        response.headers["X-Link-Cache"] = "HIT"
        response.headers["Cache-Control"] = f"private, max-age={min(LINK_CACHE_SEC, 30)}"
        return response
    info, fid = _pick(url)
    fmt = get_fmt(info, fid) if fid else None
    if not fmt:
        return jerr("لا توجد صيغة مناسبة", 404)
    payload = {"ok": True, "title": info["title"], "ext": fmt.get("ext"), "url": fmt["url"]}
    _store_link(cache_key, payload)
    response = jsonify(payload)
    response.headers["X-Link-Cache"] = "MISS"
    response.headers["Cache-Control"] = f"private, max-age={min(LINK_CACHE_SEC, 30)}"
    return response


@app.get("/stream")
@with_url()
def api_stream(url):
    info, fid = _pick(url)
    if not fid:
        return jerr("لا توجد صيغة مناسبة", 404)
    return serve(url, fid)


# ------------------------- مهام الخلفية -------------------------
keepalive.start()
if WARMUP:
    threading.Thread(target=warmup, daemon=True).start()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
