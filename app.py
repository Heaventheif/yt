import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request
from requests.adapters import HTTPAdapter
from requests.utils import quote

from cookies_util import COOKIE_STATS, COOKIES_PATH
from pages import DOCS_HTML, ENCODE_HTML, WEB_HTML
from url_utils import normalize_url

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "")
PROXY = os.getenv("PROXY", "")
WEB_PUBLIC = os.getenv("WEB_PUBLIC", "1") == "1"
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
MAX_DOWNLOADS = int(os.getenv("MAX_DOWNLOADS", "6"))
MAX_EXTRACT = int(os.getenv("MAX_CONCURRENT", "2"))
CACHE_TTL = int(os.getenv("CACHE_TTL_SEC", "1200"))
CACHE_MAX = int(os.getenv("CACHE_MAX", "80"))
CHUNK = int(float(os.getenv("CHUNK_MB", "8")) * 1048576)


def _clients(v):
    return [c.strip() for c in v.split(",") if c.strip()]


YT_CLIENTS = _clients(os.getenv("YT_CLIENTS", ""))
YT_FALLBACKS = [_clients(x) for x in os.getenv("YT_FALLBACK_CLIENTS", "android_vr;tv;mweb").split(";") if x.strip()]

SLOTS = threading.Semaphore(MAX_EXTRACT)      # استخراج المعلومات (ثقيل)
DL_SLOTS = threading.Semaphore(MAX_DOWNLOADS)  # تنزيلات متزامنة (خفيفة)
HITS = {}
POOL = ThreadPoolExecutor(max_workers=12)      # فحص متوازٍ + جلب الجزء التالي مسبقا
ORIG = {}                                      # الرابط المطبَّع => الأصلي (احتياط)
GOOD_CLIENT = {"cl": None}                     # آخر عميل يوتيوب نجح (نبدأ به مباشرة)

# جلسة HTTP مشتركة بإعادة استخدام الاتصالات
sess = requests.Session()
sess.trust_env = False
_ad = HTTPAdapter(pool_connections=20, pool_maxsize=64, max_retries=0)
sess.mount("https://", _ad)
sess.mount("http://", _ad)
if PROXY:
    sess.proxies = {"http": PROXY, "https": PROXY}

# ---- Keep-alive: يزور السيرفر نفسه كل 14 دقيقة لمنع النوم ----
KEEP_ALIVE_MIN = int(os.getenv("KEEP_ALIVE_MINUTES", "14"))
SELF_URL = os.getenv("SELF_URL") or os.getenv("RENDER_EXTERNAL_URL", "")


def keep_alive():
    while True:
        time.sleep(KEEP_ALIVE_MIN * 60)
        try:
            requests.get(SELF_URL.rstrip("/") + "/health", timeout=20)
        except Exception:
            pass


if SELF_URL and KEEP_ALIVE_MIN > 0:
    threading.Thread(target=keep_alive, daemon=True).start()


def warmup():
    """يحمّل مستخرجات yt-dlp وكاش مشغّل الجافاسكربت مرة واحدة عند الإقلاع"""
    try:
        with yt_dlp.YoutubeDL(ytdl_opts()) as ydl:
            ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
    except Exception:
        pass


class Busy(Exception):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


# ------------------------- أدوات عامة -------------------------
def auth_ok():
    if not API_KEY:
        return True
    return (request.headers.get("X-API-Key") or request.args.get("key")) == API_KEY


def jerr(msg, code=502):
    return jsonify(ok=False, error=msg), code


def err(e):
    if isinstance(e, Busy):
        return jerr(str(e), 429)
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip()
    return jerr(msg[:400] or "خطأ غير معروف", 502)


def valid_url():
    raw = request.args.get("url", "").strip()
    url = normalize_url(raw)
    if url != raw and re.match(r"^https?://", raw):
        if len(ORIG) > 500:
            ORIG.clear()
        ORIG[url] = raw
    return url if re.match(r"^https?://", url) else None


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() or request.remote_addr or "?"


def rate_ok():
    now = time.time()
    ip = client_ip()
    if len(HITS) > 5000:
        HITS.clear()
    hits = [t for t in HITS.get(ip, []) if now - t < 60]
    if len(hits) >= RATE_LIMIT:
        HITS[ip] = hits
        return False
    hits.append(now)
    HITS[ip] = hits
    return True


# ------------------------- استخراج + كاش -------------------------
KEEP_FMT = ("format_id", "url", "ext", "protocol", "vcodec", "acodec", "height", "tbr", "abr",
            "filesize", "filesize_approx", "http_headers")


def slim(d):
    """يحتفظ بالحقول اللازمة فقط لتوفير الذاكرة"""
    if d.get("_type") == "playlist" and d.get("entries"):
        d = next((e for e in d["entries"] if e), d)
    fmts = [{k: f.get(k) for k in KEEP_FMT} for f in (d.get("formats") or []) if f.get("url")]
    if not fmts and d.get("url"):
        fmts = [{"format_id": "0", "url": d["url"], "ext": d.get("ext") or "mp4",
                 "protocol": d.get("protocol") or "https", "vcodec": d.get("vcodec"), "acodec": d.get("acodec"),
                 "height": d.get("height"), "tbr": d.get("tbr"), "abr": d.get("abr"),
                 "filesize": d.get("filesize"), "filesize_approx": d.get("filesize_approx"),
                 "http_headers": d.get("http_headers")}]
    return {"title": d.get("title"), "uploader": d.get("uploader") or d.get("channel"),
            "duration": d.get("duration"), "thumbnail": d.get("thumbnail"),
            "extractor": str(d.get("extractor_key") or ""), "formats": fmts}


def ytdl_opts(clients=None):
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
         "socket_timeout": 20, "retries": 2, "js_runtimes": {"node": {}},
         "ignore_no_formats_error": True}
    cl = YT_CLIENTS if clients is None else clients
    yt = {"skip": ["hls", "dash", "translated_subs"]}  # أقل طلبات = استخراج أسرع
    if cl:
        yt["player_client"] = cl
    o["extractor_args"] = {"youtube": yt}
    o["check_formats"] = False
    o["extractor_retries"] = 1
    if os.path.exists(COOKIES_PATH):
        o["cookiefile"] = COOKIES_PATH
    if PROXY:
        o["proxy"] = PROXY
    return o


def extract_raw(url, clients=None):
    if not SLOTS.acquire(timeout=45):
        raise Busy("الخادم مشغول بطلبات أخرى، حاول بعد قليل")
    try:
        with yt_dlp.YoutubeDL(ytdl_opts(clients)) as ydl:
            return slim(ydl.extract_info(url, download=False))
    finally:
        SLOTS.release()


def collect_options(info):
    vids, auds = {}, {}
    for f in info.get("formats", []):
        if f.get("protocol") not in ("http", "https") or not f.get("url") or f.get("ext") == "mhtml":
            continue
        has_v = f.get("vcodec") != "none"
        has_a = f.get("acodec") != "none"
        size = f.get("filesize") or f.get("filesize_approx")
        ext = (f.get("ext") or "").upper()
        if has_v and has_a:
            h = f.get("height") or 0
            score = (f.get("ext") == "mp4", f.get("tbr") or 0)
            if h not in vids or score > vids[h][0]:
                label = (f"{h}p" if h else "جودة قياسية") + f" • {ext}"
                vids[h] = (score, {"fid": f["format_id"], "label": label, "size": size, "height": h})
        elif has_a and not has_v:
            abr = int(f.get("abr") or 0)
            key = (ext, abr)
            if key not in auds:
                label = ext + (f" • {abr}kbps" if abr else "")
                auds[key] = (abr, {"fid": f["format_id"], "label": label, "size": size, "height": 0})
    video = [v[1] for _, v in sorted(vids.items(), key=lambda x: -x[0])]
    audio = [v[1] for v in sorted(auds.values(), key=lambda x: -x[0])]
    return video, audio


def get_fmt(info, fid):
    for f in info.get("formats", []):
        if f.get("format_id") == fid and f.get("url"):
            return f
    return None


def match_fmt(info, old):
    """بعد إعادة الاستخراج قد تتغير المعرفات، نبحث عن أقرب صيغة"""
    f = get_fmt(info, old.get("format_id"))
    if f:
        return f
    aud = old.get("vcodec") == "none"
    for f in info.get("formats", []):
        if (f.get("ext") == old.get("ext") and f.get("height") == old.get("height")
                and (f.get("vcodec") == "none") == aud and f.get("url")
                and f.get("protocol") in ("http", "https")):
            return f
    return None


def _probe_one(f):
    h = dict(f.get("http_headers") or {})
    h["Range"] = "bytes=0-1"
    try:
        r = sess.get(f["url"], headers=h, stream=True, timeout=(5, 8))
        code = r.status_code
        r.close()
    except Exception:
        code = 0
    return code


def probe(info):
    """فحص سريع (بالتوازي): هل يقبل المصدر طلب Range من هذا السيرفر؟ يرجع كود HTTP أو None"""
    v, a = collect_options(info)
    cands = [f for f in (get_fmt(info, o["fid"]) for o in (v[:1] + a[:1])) if f]
    if not cands:
        return None
    codes = list(POOL.map(_probe_one, cands))
    bad = next((c for c in codes if c not in (200, 206)), None)
    return 200 if bad is None else bad


def is_youtube(url):
    m = re.match(r"^https?://([^/:?#]+)", url)
    h = (m.group(1) if m else "").lower()
    return h == "youtu.be" or h.endswith("youtube.com") or h.endswith("youtube-nocookie.com")


def smart_extract(url):
    if not is_youtube(url):
        return extract_raw(url)
    # الترتيب: العميل الذي نجح آخر مرة، ثم الافتراضي (None)، ثم البدائل
    order = []
    for cl in [GOOD_CLIENT["cl"], None] + YT_FALLBACKS:
        if cl not in order:
            order.append(cl)
    first_err, first_code = None, None
    for cl in order:
        try:
            info = extract_raw(url, cl)
        except Busy:
            raise
        except Exception as e:
            first_err = first_err or e
            continue
        code = probe(info)
        if code in (200, 206):
            GOOD_CLIENT["cl"] = cl
            return info
        if first_code is None:
            first_code = code
    if first_code is None and first_err:
        raise first_err
    if first_code is None:
        raise RuntimeError("لم أجد صيغ قابلة للتنزيل لهذا الرابط")
    raise RuntimeError(f"رفض يوتيوب روابط التنزيل (HTTP {first_code}). حدّث الكوكيز أو جرّب لاحقا")


_cache = OrderedDict()
_errs = {}
_inflight = {}
_cache_lock = threading.Lock()


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if item and time.time() - item[0] < CACHE_TTL:
            _cache.move_to_end(key)
            return item[1]
        _cache.pop(key, None)
    return None


def cache_put(key, val):
    with _cache_lock:
        _cache[key] = (time.time(), val)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


def get_info(url, fresh=False):
    if not fresh:
        c = cache_get(url)
        if c:
            return c
        e = _errs.get(url)
        if e and time.time() - e[0] < 20:
            raise RuntimeError(e[1])
    with _cache_lock:
        lk = _inflight.setdefault(url, threading.Lock())
    with lk:  # طلبات نفس الرابط تنتظر نتيجة واحدة بدل استخراج مكرر
        if not fresh:
            c = cache_get(url)
            if c:
                return c
        try:
            try:
                info = smart_extract(url)
            except Busy:
                raise
            except Exception:
                orig = ORIG.get(url)  # إن فشل الرابط المطبَّع جرّب الأصلي مرة واحدة
                if not orig:
                    raise
                info = smart_extract(orig)
        except Busy:
            raise
        except Exception as e:
            if len(_errs) > 200:
                _errs.clear()
            _errs[url] = (time.time(), re.sub(r"\x1b\[[0-9;]*m", "", str(e))[:400])
            raise
        finally:
            with _cache_lock:
                _inflight.pop(url, None)
        _errs.pop(url, None)
        cache_put(url, info)
        return info


def info_payload(info):
    video, audio = collect_options(info)
    return {"ok": True, "title": info["title"], "uploader": info["uploader"],
            "duration": info["duration"], "thumbnail": info["thumbnail"],
            "video": video, "audio": audio}


# ------------------------- تمرير الملف -------------------------
def fetch_range(fmt, start, last):
    h = dict(fmt.get("http_headers") or {})
    h["Range"] = f"bytes={start}-{min(last, start + CHUNK - 1)}"
    try:
        r = sess.get(fmt["url"], headers=h, stream=True, timeout=(10, 30))
    except Exception:
        return None
    if r.status_code == 206 or (r.status_code == 200 and start == 0):
        return r
    r.close()
    return None


def open_upstream(fmt, cstart=0, cend=None):
    end = cstart + CHUNK - 1
    if cend is not None:
        end = min(end, cend)
    h = dict(fmt.get("http_headers") or {})
    h["Range"] = f"bytes={cstart}-{end}"
    try:
        r = sess.get(fmt["url"], headers=h, stream=True, timeout=(10, 30))
    except Exception as e:
        raise RuntimeError("تعذر الاتصال بمصدر الملف: " + type(e).__name__)
    code = r.status_code
    if code == 206:
        m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("Content-Range", ""))
        total = int(m.group(3)) if m and m.group(3).isdigit() else None
        ranged = True
    elif code == 200 and cstart == 0:
        cl = r.headers.get("Content-Length", "")
        total = int(cl) if cl.isdigit() else None
        ranged = False
    else:
        r.close()
        raise UpstreamError(code)
    last = (total - 1) if total else (1 << 62)
    if cend is not None:
        last = min(last, cend)
    return r, total, last, ranged


def _discard(fut):
    def _c(f):
        try:
            x = f.result()
            if x is not None:
                x.close()
        except Exception:
            pass
    fut.add_done_callback(_c)


def stream_gen(fmt, r, pos, last, ranged, slot):
    """يمرر الملف على أجزاء (Range) ويفتح اتصال الجزء التالي مسبقا عند منتصف الجزء الحالي
    فلا يحدث توقف بين الأجزاء. مع إعادة محاولة عند الانقطاع."""
    fails = 0
    nxt = None
    try:
        while True:
            seg_end = min(last, pos + CHUNK - 1)
            half = pos + (seg_end - pos) // 2
            got = 0
            try:
                for piece in r.iter_content(262144):
                    if piece:
                        got += len(piece)
                        pos += len(piece)
                        yield piece
                        if ranged and nxt is None and pos >= half and seg_end < last:
                            nxt = POOL.submit(fetch_range, fmt, seg_end + 1, last)
            except Exception:
                fails += 1
            finally:
                r.close()
            if not ranged or pos > last:
                return
            if got == 0:
                fails += 1
            if fails > 3:
                return
            r = None
            if nxt is not None:
                fut, nxt = nxt, None
                res = fut.result()
                if pos == seg_end + 1:
                    r = res
                elif res is not None:
                    res.close()
            if r is None:
                r = fetch_range(fmt, pos, last)
            if r is None:
                return
    finally:
        if nxt is not None:
            _discard(nxt)
        try:
            r.close()
        except Exception:
            pass
        slot.release()  # تحرير فوري عند الانتهاء أو انقطاع العميل


class Slot:
    def __init__(self):
        self.lock = threading.Lock()
        self.done = False

    def release(self):
        with self.lock:
            if not self.done:
                self.done = True
                DL_SLOTS.release()


CTYPES = {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg",
          "opus": "audio/ogg", "ogg": "audio/ogg", "flv": "video/x-flv", "3gp": "video/3gpp"}


def disposition(name, ext):
    fn = f"{name}.{ext}"
    ascii_fn = re.sub(r"[^A-Za-z0-9._ \-\[\]()]+", "_", fn) or f"file.{ext}"
    return 'attachment; filename="' + ascii_fn + '"; filename*=UTF-8' + "''" + quote(fn)


def serve(url, fid, check=False):
    info = get_info(url)
    fmt = get_fmt(info, fid)
    if not fmt:
        return jerr("الصيغة غير موجودة، أعد البحث عن الرابط", 404)

    cstart, cend = 0, None
    m = re.match(r"bytes=(\d+)-(\d*)$", (request.headers.get("Range") or "").strip())
    if m and not check:
        cstart = int(m.group(1))
        cend = int(m.group(2)) if m.group(2) else None

    if not DL_SLOTS.acquire(blocking=False):
        return jerr("الخادم مشغول بتنزيلات أخرى، حاول بعد قليل", 429)
    slot, handed = Slot(), False
    try:
        up = None
        for attempt in (0, 1):
            try:
                up = open_upstream(fmt, cstart, cend)
                break
            except UpstreamError as e:
                if attempt == 1 or e.code not in (401, 403, 404, 410):
                    return jerr(f"رفض المصدر الطلب (HTTP {e.code})", 502)
                try:  # الرابط انتهى أو رُفض: استخراج جديد ثم محاولة أخيرة
                    info = get_info(url, fresh=True)
                except Exception as ex:
                    return err(ex)
                fmt = match_fmt(info, fmt)
                if not fmt:
                    return jerr("تغيرت الصيغ المتاحة، أعد البحث عن الرابط", 409)
        r, total, last, ranged = up
        if last < cstart:
            r.close()
            return jerr("نطاق غير صالح", 416)
        if check:
            r.close()
            return jsonify(ok=True, size=total)

        ext = fmt.get("ext") or "bin"
        audio_only = fmt.get("vcodec") == "none"
        ctype = CTYPES.get(ext, "application/octet-stream")
        if audio_only and ext == "webm":
            ctype = "audio/webm"
        title = re.sub(r'[\\/:*?"<>|\r\n]+', "_", info.get("title") or "file")[:80]
        if fmt.get("height") and not audio_only:
            title += f" [{fmt['height']}p]"
        out = {"Content-Type": ctype, "Content-Disposition": disposition(title, ext),
               "Cache-Control": "no-store"}
        status = 200
        if ranged and total:
            out["Accept-Ranges"] = "bytes"
        if total:
            out["Content-Length"] = str(last - cstart + 1)
            if cstart > 0 or (cend is not None and cend < total - 1):
                status = 206
                out["Content-Range"] = f"bytes {cstart}-{last}/{total}"
        resp = Response(stream_gen(fmt, r, cstart, last, ranged, slot), status=status, headers=out)
        resp.call_on_close(slot.release)
        handed = True
        return resp
    except RuntimeError as e:
        return err(e)
    finally:
        if not handed:
            slot.release()


def pick_fid(info, kind, q):
    v, a = collect_options(info)
    if kind == "audio":
        return a[0]["fid"] if a else None
    if not v:
        return None
    q = int(q) if str(q).isdigit() else 720
    for o in v:
        if (o["height"] or 0) <= q:
            return o["fid"]
    return v[-1]["fid"]


# ------------------------- المسارات -------------------------
@app.before_request
def guard():
    p = request.path
    if p in ("/", "/health", "/docs", "/encode"):
        return None
    if p.startswith("/web/"):
        if not WEB_PUBLIC:
            return jerr("الواجهة العامة معطلة", 404)
        if (p == "/web/info" or request.args.get("check")) and not rate_ok():
            return jerr("طلبات كثيرة، انتظر دقيقة ثم حاول مجددا", 429)
        return None
    if not auth_ok():
        return jerr("unauthorized", 401)


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
    return jsonify(ok=True, yt_dlp=yt_dlp.version.__version__)


@app.get("/cookies")
def cookies_status():
    yt = any(d.endswith(("youtube.com", "google.com")) for d in COOKIE_STATS["domains"])
    return jsonify(ok=True, has_youtube=yt, **COOKIE_STATS)


# --- واجهة عامة ---
@app.get("/web/info")
def web_info():
    url = valid_url()
    if not url:
        return jerr("الرابط غير صحيح", 400)
    try:
        info = get_info(url)
    except Exception as e:
        return err(e)
    p = info_payload(info)
    if not p["video"] and not p["audio"]:
        return jerr("لا توجد صيغ قابلة للتنزيل المباشر لهذا الرابط", 404)
    return jsonify(p)


@app.get("/web/dl")
def web_dl():
    url = valid_url()
    fid = request.args.get("fid", "")
    if not url or not re.match(r"^[\w.\-+]+$", fid):
        return jerr("طلب غير صحيح", 400)
    try:
        return serve(url, fid, check=bool(request.args.get("check")))
    except Exception as e:
        return err(e)


# --- API بمفتاح (للبوت) ---
@app.get("/info")
def api_info():
    url = valid_url()
    if not url:
        return jerr("url مطلوب", 400)
    try:
        return jsonify(info_payload(get_info(url)))
    except Exception as e:
        return err(e)


@app.get("/link")
def api_link():
    url = valid_url()
    if not url:
        return jerr("url مطلوب", 400)
    try:
        info = get_info(url)
        fid = pick_fid(info, request.args.get("type", "video"), request.args.get("q"))
        fmt = get_fmt(info, fid) if fid else None
        if not fmt:
            return jerr("لا توجد صيغة مناسبة", 404)
        return jsonify(ok=True, title=info["title"], ext=fmt.get("ext"), url=fmt["url"])
    except Exception as e:
        return err(e)


@app.get("/stream")
def api_stream():
    url = valid_url()
    if not url:
        return jerr("url مطلوب", 400)
    try:
        info = get_info(url)
        fid = pick_fid(info, request.args.get("type", "video"), request.args.get("q"))
        if not fid:
            return jerr("لا توجد صيغة مناسبة", 404)
        return serve(url, fid)
    except Exception as e:
        return err(e)


if os.getenv("WARMUP", "1") == "1":
    threading.Thread(target=warmup, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
