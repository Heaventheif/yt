"""نقاط النهاية (Routes) فقط. المنطق موزع على الوحدات:
config · errors · net · formats · extractor · info_cache · streaming · serving · security · keepalive
"""
import hashlib
import json
import math
import re
import threading
import time
from functools import wraps
from urllib.parse import quote, urlsplit

import yt_dlp
from flask import Flask, Response, jsonify, redirect, request, send_from_directory

import keepalive
import observability
from config import (CORS_ORIGINS, DL_RATE_LIMIT, INFO_MAX_AGE, MAX_FID_LEN, MAX_URL_LEN, PLAYLIST_MAX_LIMIT,
                    TELEMETRY_ENABLED, THUMB_MAX_BYTES, THUMB_RATE_LIMIT, WARMUP, WEB_PUBLIC)
from cookies_util import COOKIE_STATS
from extractor import search_media, search_soundcloud, warmup
from formats import detail_options, get_fmt, info_payload, pick_fid
from info_cache import _cache as INFO_CACHE, get_info, get_playlist, remember_original
from pages import DOCS_HTML, ENCODE_HTML
from responses import err, jerr
from security import auth_ok, rate_ok
from config import API_RATE_LIMIT
from serving import serve
from streaming import STATS
from url_safety import is_public_url
from net import sess
from url_utils import normalize_url, unwrap_url

observability.init()
import os as _os

STATIC_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # الملفات غير مُبصَمة: ETag + إعادة تحقق بدل max-age
STARTED = time.time()

PUBLIC_PATHS = ("/", "/health", "/docs", "/encode", "/sw.js", "/manifest.webmanifest", "/share")
FID_PATTERN = re.compile(r"^[\w.\-+]{1,%d}$" % MAX_FID_LEN)
LIST_ID = re.compile(r"^[\w-]{10,64}$")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif")
_HTTP_URL = re.compile(r"^https?://")


# ------------------------- أدوات الطلب -------------------------
def valid_url():
    """الرابط من ?url= بعد فك التحويلات وتطبيعه، أو None إن لم يكن رابط http(s) سليما"""
    raw = request.args.get("url", "").strip()
    if len(raw) > MAX_URL_LEN or any(ord(c) < 32 for c in raw):
        return None
    raw = unwrap_url(raw)
    try:
        if _HTTP_URL.match(raw) and urlsplit(raw).username is not None:   # user:pass@host: نرفضه قبل أن يُنزع بالتطبيع
            return None
    except ValueError:
        return None
    url = normalize_url(raw)
    if url != raw and _HTTP_URL.match(raw):
        remember_original(url, raw)
    if not _HTTP_URL.match(url) or len(url) > MAX_URL_LEN:
        return None
    return url


def with_url(missing_msg="url مطلوب"):
    """يمرر الرابط الصالح للدالة، ويحوّل أي استثناء إلى رد JSON"""
    def decorator(fn):
        @wraps(fn)
        def wrapper():
            url = valid_url()
            if not url:
                return jerr(missing_msg, 400)
            if not is_public_url(url):
                return jerr("الرابط غير مسموح", 400)
            try:
                return fn(url)
            except Exception as e:
                return err(e)
        return wrapper
    return decorator


def _pick(url, allow_merge=True):
    """(info, fid) حسب type و q في الطلب"""
    info = get_info(url)
    return info, pick_fid(info, request.args.get("type", "video"), request.args.get("q"), allow_merge)


# ------------------------- الحماية -------------------------
@app.before_request
def guard():
    if request.method == "OPTIONS":  # طلب CORS التمهيدي لا يحمل المفتاح
        return Response(status=204)
    p = request.path
    if p in PUBLIC_PATHS or p.startswith("/static/"):
        return None
    if p.startswith("/web/"):
        if not WEB_PUBLIC:
            return jerr("الواجهة العامة معطلة", 404)
        busy = jerr("طلبات كثيرة، انتظر دقيقة ثم حاول مجددا", 429, 60)
        if p == "/web/dl":
            # أجزاء Range اللاحقة (حفظ دون اتصال) لا تُحسب؛ نحسب بداية كل تنزيل فقط
            rng = request.headers.get("Range", "")
            if (not rng or rng.startswith("bytes=0-")) and not rate_ok(DL_RATE_LIMIT, "dl"):
                return busy
        elif p == "/web/thumb":
            if not rate_ok(THUMB_RATE_LIMIT, "thumb"):
                return busy
        elif p == "/web/telemetry":
            if not rate_ok(60, "tele"):
                return Response(status=204)
        elif (p in ("/web/info", "/web/playlist", "/web/search")) and not rate_ok():
            return busy
        return None
    if not auth_ok():
        return jerr("unauthorized", 401)
    # API المفتاح لا ينبغي أن يتجاوز طبقة الحماية؛ نستخدم حداً منفصلاً عن الواجهة العامة.
    if p in ("/info", "/link", "/stream") and not rate_ok(API_RATE_LIMIT, "api"):
        return jerr("طلبات كثيرة، انتظر دقيقة ثم حاول مجددا", 429, 60)


_CSP_STRICT = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
               "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; "
               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
# صفحتا الإدارة (/docs و/encode) تستخدمان سكربتات مضمّنة قديمة: تبقيان على سياسة أخف
_CSP_ADMIN = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
              "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@app.after_request
def finish(resp):
    path = request.path
    if resp.mimetype == "text/html":
        resp.headers["Content-Security-Policy"] = _CSP_ADMIN if path in ("/docs", "/encode") else _CSP_STRICT
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"   # يخزَّن لكن يُعاد التحقق (ETag => 304)
    origin = request.headers.get("Origin", "").rstrip("/")
    if CORS_ORIGINS and (origin in CORS_ORIGINS or "*" in CORS_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin if "*" not in CORS_ORIGINS else "*"
        if "*" not in CORS_ORIGINS:
            resp.headers.add("Vary", "Origin")
        resp.headers["Access-Control-Allow-Headers"] = "X-API-Key, Range, If-None-Match, If-Range"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "600"
        resp.headers["Access-Control-Expose-Headers"] = ("Content-Disposition, Content-Length, Content-Range, "
                                                          "Accept-Ranges, ETag, Retry-After")
    return resp


# ------------------------- صفحات -------------------------
def _static(name, **kw):
    return send_from_directory(STATIC_DIR, name, **kw)


@app.get("/")
def index():
    if WEB_PUBLIC:
        return _static("index.html", mimetype="text/html")
    return Response(DOCS_HTML, mimetype="text/html")


@app.get("/sw.js")
def service_worker():
    resp = _static("sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.get("/manifest.webmanifest")
def manifest():
    return _static("manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/share")
def share_target():
    """هدف المشاركة في PWA: يستقبل url/text ويحوّل إلى الصفحة الرئيسية بـ ?u="""
    shared = request.args.get("u") or request.args.get("t") or ""
    return redirect("/?u=" + quote(shared[:MAX_URL_LEN], safe=""), 303)


@app.get("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html")


@app.get("/encode")
def encode_page():
    return Response(ENCODE_HTML, mimetype="text/html")


def _pot_up():
    import os
    import socket
    if os.getenv("ENABLE_POT", "1") != "1":
        return None
    try:
        socket.create_connection(("127.0.0.1", 4416), timeout=0.3).close()
        return True
    except OSError:
        return False


@app.get("/health")
def health():
    return jsonify(ok=True, pot_server=_pot_up(), yt_dlp=yt_dlp.version.__version__, uptime_s=int(time.time() - STARTED),
                   active_downloads=STATS["active"], served_mb=STATS["bytes"] >> 20)


@app.get("/cookies")
def cookies_status():
    yt = any(d.endswith(("youtube.com", "google.com")) for d in COOKIE_STATS["domains"])
    return jsonify(ok=True, has_youtube=yt, **COOKIE_STATS)


# ------------------------- واجهة عامة -------------------------
def etag_json(payload, max_age=INFO_MAX_AGE):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    tag = 'W/"' + hashlib.blake2s(body.encode(), digest_size=12).hexdigest() + '"'
    if request.headers.get("If-None-Match") == tag:
        resp = Response(status=304)
    else:
        resp = Response(body, mimetype="application/json")
    resp.headers["ETag"] = tag
    resp.headers["Cache-Control"] = f"public, max-age={max_age}, stale-while-revalidate=600"
    return resp


def _thumb_proxy(src):
    return "/web/thumb?u=" + quote(src, safe="") if src and _HTTP_URL.match(src) else None


@app.get("/web/info")
@with_url("الرابط غير صحيح")
def web_info(url):
    info = get_info(url)
    payload = info_payload(info)
    if not payload["video"] and not payload["audio"]:
        return jerr("لا توجد صيغ قابلة للتنزيل المباشر لهذا الرابط", 404)
    payload["thumbnail"] = _thumb_proxy(payload.get("thumbnail"))
    payload["detail"] = detail_options(info) if request.args.get("detail") == "all" else None
    return etag_json(payload)


@app.get("/web/search")
def web_search():
    query = re.sub(r"\s+", " ", request.args.get("q", "").strip())
    source = request.args.get("source", "soundcloud").lower()
    if len(query) < 2 or len(query) > 200:
        return jerr("اكتب عنوان أغنية صالحا (من حرفين إلى 200 حرف)", 400)
    if source not in ("soundcloud", "youtube"):
        return jerr("مصدر البحث غير صالح", 400)
    try:
        results = search_media(query, source, 10)
        if not results:
            return jerr("لم أجد نتائج مطابقة", 404)
        return etag_json({"ok": True, "source": source, "results": results, **results[0]}, 120)
    except Exception as e:
        return err(e)


@app.get("/web/thumb")
def web_thumb():
    """وسيط للصور المصغرة: نفس الأصل (CSP/Service Worker) + سقف حجم + أنواع صور فقط."""
    src = request.args.get("u", "")
    if len(src) > MAX_URL_LEN or not _HTTP_URL.match(src) or not is_public_url(src):
        return jerr("رابط الصورة غير مسموح", 400)
    try:
        up = sess.get(src, stream=True, timeout=(5, 8), headers={"Accept": "image/*"})
    except Exception:
        return jerr("تعذر جلب الصورة", 502)
    try:
        ctype = (up.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if up.status_code != 200 or ctype not in IMAGE_TYPES:
            return jerr("ليست صورة صالحة", 502)
        data = b""
        for piece in up.iter_content(32768):
            data += piece
            if len(data) > THUMB_MAX_BYTES:
                return jerr("الصورة كبيرة جدا", 502)
    finally:
        up.close()
    resp = Response(data, mimetype=ctype)
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return resp


@app.get("/web/playlist")
def web_playlist():
    """قائمة تشغيل يوتيوب بصفحات: ?list=ID&cursor=N&limit=25 => {items, next_cursor}"""
    list_id = request.args.get("list", "")
    if not LIST_ID.match(list_id):
        return jerr("معرّف القائمة غير صحيح", 400)
    try:
        start = max(0, int(request.args.get("cursor", "0")))
        limit = min(PLAYLIST_MAX_LIMIT, max(1, int(request.args.get("limit", "25"))))
    except ValueError:
        return jerr("معاملات الصفحات غير صحيحة", 400)
    try:
        page = get_playlist(list_id, start, limit)
    except Exception as e:
        return err(e)
    items = page["items"]
    total = page.get("count")
    more = len(items) == limit and (total is None or start + limit < total)
    return etag_json({"ok": True, "title": page.get("title"), "count": total, "items": items,
                      "next_cursor": str(start + limit) if more else None}, 300)


_TELE_FIELDS = {"e", "v"}


@app.post("/web/telemetry")
def web_telemetry():
    """قياسات مجهولة من المتصفح (sendBeacon): اسم حدث من قائمة بيضاء + رقم. لا تخزين لأي معرّف."""
    if not TELEMETRY_ENABLED:
        return Response(status=204)
    raw = request.get_data(cache=False)[:2048]
    try:
        items = json.loads(raw)
    except ValueError:
        return Response(status=204)
    for ev in (items if isinstance(items, list) else [items])[:20]:
        if isinstance(ev, dict) and set(ev) <= _TELE_FIELDS and isinstance(ev.get("e"), str):
            v = ev.get("v", 1)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                v = float(v)
                v = min(1000.0, max(-1000.0, v)) if math.isfinite(v) else 1.0
            else:
                v = 1.0
            observability.count(ev["e"], v)
    return Response(status=204)


@app.get("/metrics")
def metrics():
    return jsonify(ok=True, events=observability.snapshot(), info_cache_bytes=INFO_CACHE.bytes,
                   active_downloads=STATS["active"], served_mb=STATS["bytes"] >> 20)


@app.get("/web/dl")
@with_url("طلب غير صحيح")
def web_dl(url):
    fid = request.args.get("fid", "")
    if not FID_PATTERN.match(fid):
        return jerr("طلب غير صحيح", 400)
    return serve(url, fid, check=bool(request.args.get("check")), per_ip=True)


# ------------------------- API بمفتاح (للبوت) -------------------------
@app.get("/info")
@with_url()
def api_info(url):
    return jsonify(info_payload(get_info(url)))


@app.get("/link")
@with_url()
def api_link(url):
    info, fid = _pick(url, allow_merge=False)   # رابط واحد مباشر: بلا دمج
    fmt = get_fmt(info, fid) if fid else None
    if not fmt:
        return jerr("لا توجد صيغة مناسبة", 404)
    return jsonify(ok=True, title=info["title"], ext=fmt.get("ext"), url=fmt["url"])


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
