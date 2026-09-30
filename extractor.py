"""الاستخراج عبر yt-dlp: الخيارات، الفحص، واختيار عميل يوتيوب المناسب."""
import os
import re
import threading
import time

import yt_dlp

from config import (EXTRACT_WAIT_SEC, MAX_EXTRACT, PROBE_TIMEOUT, PROXY, WARMUP_URL,
                    YT_CLIENTS, YT_FALLBACKS)
from cookies_util import COOKIES_PATH
from errors import Busy
from formats import collect_options, get_fmt
from net import POOL, sess


EXTRACT_SLOTS = threading.Semaphore(MAX_EXTRACT)   # الاستخراج ثقيل فنحدّد تزامنه
OK_CODES = (200, 206)
KEEP_FIELDS = ("format_id", "url", "ext", "protocol", "vcodec", "acodec", "height", "tbr", "abr",
               "filesize", "filesize_approx", "http_headers")

_last_good_client = None   # آخر عميل يوتيوب نجح: نبدأ به مباشرة في الطلب التالي


def log(*args):
    print("[timing]", *args, flush=True)


# ------------------------- تقليص النتيجة -------------------------
def _slim_format(f):
    return {k: f.get(k) for k in KEEP_FIELDS}


def slim(d):
    """يحتفظ بالحقول اللازمة فقط لتوفير الذاكرة"""
    if d.get("_type") == "playlist" and d.get("entries"):
        d = next((e for e in d["entries"] if e), d)
    fmts = [_slim_format(f) for f in (d.get("formats") or []) if f.get("url")]
    if not fmts and d.get("url"):  # رابط مباشر بلا قائمة صيغ
        fmts = [_slim_format({**d, "format_id": "0", "ext": d.get("ext") or "mp4",
                              "protocol": d.get("protocol") or "https"})]
    return {"title": d.get("title"), "uploader": d.get("uploader") or d.get("channel"),
            "duration": d.get("duration"), "thumbnail": d.get("thumbnail"),
            "extractor": str(d.get("extractor_key") or ""), "formats": fmts}


# ------------------------- yt-dlp -------------------------
def ytdl_opts(clients=None):
    yt_args = {"skip": ["hls", "dash", "translated_subs"]}  # أقل طلبات = استخراج أسرع
    player_clients = YT_CLIENTS if clients is None else clients
    if player_clients:
        yt_args["player_client"] = player_clients
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
            "socket_timeout": 20, "retries": 2, "js_runtimes": {"node": {}},
            "ignore_no_formats_error": True, "check_formats": False, "extractor_retries": 1,
            "extractor_args": {"youtube": yt_args}}
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    if PROXY:
        opts["proxy"] = PROXY
    return opts


def extract_raw(url, clients=None):
    if not EXTRACT_SLOTS.acquire(timeout=EXTRACT_WAIT_SEC):
        raise Busy("الخادم مشغول بطلبات أخرى، حاول بعد قليل")
    try:
        with yt_dlp.YoutubeDL(ytdl_opts(clients)) as ydl:
            return slim(ydl.extract_info(url, download=False))
    finally:
        EXTRACT_SLOTS.release()


def warmup():
    """يحمّل مستخرجات yt-dlp وكاش مشغّل الجافاسكربت مرة واحدة عند الإقلاع"""
    try:
        with yt_dlp.YoutubeDL(ytdl_opts()) as ydl:
            ydl.extract_info(WARMUP_URL, download=False)
    except Exception:
        pass


# ------------------------- فحص الروابط -------------------------
def _probe_one(f):
    headers = dict(f.get("http_headers") or {})
    headers["Range"] = "bytes=0-1"
    try:
        r = sess.get(f["url"], headers=headers, stream=True, timeout=PROBE_TIMEOUT)
        code = r.status_code
        r.close()
    except Exception:
        code = 0
    return code


def probe(info):
    """فحص سريع (بالتوازي): هل يقبل المصدر طلب Range من هذا السيرفر؟ يرجع كود HTTP أو None"""
    video, audio = collect_options(info)
    candidates = [f for f in (get_fmt(info, o["fid"]) for o in (video[:1] + audio[:1])) if f]
    if not candidates:
        return None
    codes = list(POOL.map(_probe_one, candidates))
    bad = next((c for c in codes if c not in OK_CODES), None)
    return 200 if bad is None else bad


# ------------------------- يوتيوب -------------------------
def is_youtube(url):
    m = re.match(r"^https?://([^/:?#]+)", url)
    host = (m.group(1) if m else "").lower()
    return host == "youtu.be" or host.endswith(("youtube.com", "youtube-nocookie.com"))


def _client_order():
    """العميل الذي نجح آخر مرة، ثم الافتراضي (None)، ثم البدائل"""
    order = []
    for cl in [_last_good_client, None] + YT_FALLBACKS:
        if cl not in order:
            order.append(cl)
    return order


def _extract_youtube(url):
    global _last_good_client
    first_err, first_code = None, None
    for cl in _client_order():
        name = ",".join(cl) if cl else "default"
        t0 = time.time()
        try:
            info = extract_raw(url, cl)
        except Busy:
            raise
        except Exception as e:
            log(f"youtube client={name} FAILED after {time.time() - t0:.1f}s: {str(e)[:120]}")
            first_err = first_err or e
            continue
        t1 = time.time()
        code = probe(info)
        log(f"youtube client={name} extract={t1 - t0:.1f}s probe={time.time() - t1:.1f}s "
            f"formats={len(info.get('formats', []))} http={code}")
        if code in OK_CODES:
            _last_good_client = cl
            return info
        if first_code is None:
            first_code = code
    _raise_youtube_failure(first_code, first_err)


def _raise_youtube_failure(code, err):
    if code is None and err:
        raise err
    if code is None:
        raise RuntimeError("لم أجد صيغ قابلة للتنزيل لهذا الرابط")
    raise RuntimeError(f"رفض يوتيوب روابط التنزيل (HTTP {code}). حدّث الكوكيز أو جرّب لاحقا")


def smart_extract(url):
    if is_youtube(url):
        return _extract_youtube(url)
    t = time.time()
    info = extract_raw(url)
    log(f"{info.get('extractor')} extract={time.time() - t:.1f}s")
    return info
