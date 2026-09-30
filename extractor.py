"""الاستخراج عبر yt-dlp مع طابور محدود يمنع إغراق الخادم."""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import yt_dlp

from config import (EXTRACT_QUEUE_MULTIPLIER, EXTRACT_WAIT_SEC, MAX_EXTRACT, PROBE_ENABLED, PROBE_TIMEOUT, PROXY,
                    WARMUP_URL, YT_CLIENTS, YT_FALLBACKS)
from cookies_util import COOKIES_PATH
from config import DISABLE_GENERIC
from errors import Busy
from formats import collect_options, get_fmt
from net import POOL, sess


# لا ننشئ yt-dlp بلا حدود عند الضغط. عدد مهام الاستخراج الفعلية يبقى محدوداً.
_EXTRACT_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, MAX_EXTRACT), thread_name_prefix="extract")
_EXTRACT_QUEUE = threading.BoundedSemaphore(max(1, MAX_EXTRACT) * (1 + EXTRACT_QUEUE_MULTIPLIER))
OK_CODES = (200, 206)
KEEP_FIELDS = ("format_id", "url", "ext", "protocol", "vcodec", "acodec", "height", "tbr", "abr",
               "filesize", "filesize_approx", "http_headers")

_last_good_client = None
_last_good_at = 0.0
_CLIENT_TTL = 900


def log(*args):
    print("[timing]", *args, flush=True)


def _slim_format(f):
    return {k: f.get(k) for k in KEEP_FIELDS}


def slim(d):
    """يحتفظ بالحقول اللازمة فقط لتوفير الذاكرة."""
    if d.get("_type") == "playlist" and d.get("entries"):
        d = next((e for e in d["entries"] if e), d)
    fmts = [_slim_format(f) for f in (d.get("formats") or []) if f.get("url")]
    if not fmts and d.get("url"):
        fmts = [_slim_format({**d, "format_id": "0", "ext": d.get("ext") or "mp4",
                              "protocol": d.get("protocol") or "https"})]
    return {"title": d.get("title"), "uploader": d.get("uploader") or d.get("channel"),
            "duration": d.get("duration"), "thumbnail": d.get("thumbnail"),
            "extractor": str(d.get("extractor_key") or ""), "formats": fmts}


def ytdl_opts(clients=None):
    yt_args = {"skip": ["hls", "dash", "translated_subs"]}
    player_clients = YT_CLIENTS if clients is None else clients
    if player_clients:
        yt_args["player_client"] = player_clients
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
            "socket_timeout": 20, "retries": 2, "js_runtimes": {"node": {}},
            "ignore_no_formats_error": True, "check_formats": False, "extractor_retries": 1,
            "extractor_args": {"youtube": yt_args}}
    if DISABLE_GENERIC:
        opts["allowed_extractors"] = ["default", "-generic"]
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    if PROXY:
        opts["proxy"] = PROXY
    return opts


class _Collect:
    """يلتقط تحذيرات/أخطاء yt-dlp (كانت مكتومة بـ no_warnings) لتظهر في السجل عند غياب الصيغ."""

    def __init__(self):
        self.msgs = []

    def debug(self, m):
        pass

    info = debug

    def warning(self, m):
        if len(self.msgs) < 30:
            self.msgs.append(str(m)[:220])

    error = warning


def _run_extract(url, clients=None):
    try:
        col = _Collect()
        opts = ytdl_opts(clients)
        opts["logger"] = col
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = slim(ydl.extract_info(url, download=False))
        if not info["formats"] and col.msgs:
            log("yt-dlp returned NO formats; messages:", " | ".join(col.msgs[-6:]))
        return info
    finally:
        _EXTRACT_QUEUE.release()


def extract_raw(url, clients=None):
    """يضع مهمة yt-dlp في طابور محدود وينتظر النتيجة بمهلة واضحة.

    إذا انتهت مهلة انتظار النتيجة، نحاول إلغاء المهمة إن لم تكن قد بدأت بعد.
    أما مهمة yt-dlp التي بدأت فعلا فلا يمكن قتلها بأمان من داخل ThreadPoolExecutor؛
    تبقى محكومة بمهلات yt-dlp، مع بقاء عددها الأقصى محدودا بـ MAX_EXTRACT.
    """
    if not _EXTRACT_QUEUE.acquire(timeout=EXTRACT_WAIT_SEC):
        raise Busy("الخادم مشغول بطلبات استخراج أخرى، حاول بعد قليل")
    future = None
    try:
        future = _EXTRACT_EXECUTOR.submit(_run_extract, url, clients)
        try:
            return future.result(timeout=max(30, EXTRACT_WAIT_SEC + 30))
        except FutureTimeout:
            # إن لم تبدأ المهمة بعد، نلغيها ونعيد خانة الطابور يدويا لأن
            # _run_extract لن يدخل finally في هذه الحالة. أما إن كانت بدأت،
            # فـ _run_extract سيحرر الخانة بنفسه عند انتهائها.
            if future.cancel():
                _EXTRACT_QUEUE.release()
            raise Busy("استغرق استخراج الرابط وقتا أطول من المسموح، حاول مجددا")
    except Busy:
        raise
    except Exception:
        if future is None:
            _EXTRACT_QUEUE.release()
        raise


def warmup():
    """تسخين عبر نفس الطابور المحدود، حتى لا يزاحم طلبات المستخدمين على 0.1 CPU."""
    try:
        extract_raw(WARMUP_URL)
    except Exception:
        pass


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
    video, audio = collect_options(info)
    candidates = [f for f in (get_fmt(info, o["fid"]) for o in (video[:1] + audio[:1])) if f]
    if not candidates:
        return None
    codes = list(POOL.map(_probe_one, candidates))
    bad = next((c for c in codes if c not in OK_CODES), None)
    return 200 if bad is None else bad


def is_youtube(url):
    m = re.match(r"^https?://([^/:?#]+)", url)
    host = (m.group(1) if m else "").lower()
    return host == "youtu.be" or host.endswith(("youtube.com", "youtube-nocookie.com"))


def _client_order():
    now = time.time()
    recent = _last_good_client if _last_good_client is not None and now - _last_good_at < _CLIENT_TTL else None
    order = []
    for cl in [recent, None] + YT_FALLBACKS:
        if cl not in order:
            order.append(cl)
    return order


def _extract_youtube(url):
    global _last_good_client, _last_good_at
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
        video, audio = collect_options(info)
        if not (video or audio):   # نتيجة بلا صيغ مباشرة ليست نجاحاً: جرّب العميل التالي
            log(f"youtube client={name} returned no direct formats (total={len(info.get('formats', []))})")
            continue
        code = probe(info) if PROBE_ENABLED else 200
        log(f"youtube client={name} extract={t1 - t0:.1f}s probe={time.time() - t1:.1f}s "
            f"formats={len(info.get('formats', []))} http={code}")
        if code in OK_CODES:
            _last_good_client = cl
            _last_good_at = time.time()
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


_TRANSIENT = ("timed out", "timeout", "connection reset", "connection aborted", "remote end closed",
              "temporary failure", "http error 5", "http error 429", "too many requests")


def _transient(e):
    m = str(e).lower()
    return any(k in m for k in _TRANSIENT)


def _with_backoff(fn, tries=3, base=1.0):
    """إعادة محاولة بتأخير تصاعدي (1s, 2s) للأخطاء العابرة فقط."""
    for i in range(tries):
        try:
            return fn()
        except Busy:
            raise
        except Exception as e:
            if i == tries - 1 or not _transient(e):
                raise
            log(f"transient error, retry {i + 1} in {base * 2 ** i:.0f}s: {str(e)[:100]}")
            time.sleep(base * 2 ** i)


def smart_extract(url):
    if is_youtube(url):
        return _extract_youtube(url)
    t = time.time()
    info = _with_backoff(lambda: extract_raw(url))
    log(f"{info.get('extractor')} extract={time.time() - t:.1f}s")
    return info
