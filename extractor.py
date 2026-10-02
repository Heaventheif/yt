"""الاستخراج عبر yt-dlp مع طابور محدود يمنع إغراق الخادم."""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from urllib.parse import urljoin, urlsplit

import yt_dlp

from config import (EXTRACT_QUEUE_MULTIPLIER, EXTRACT_WAIT_SEC, MAX_EXTRACT, PROBE_ENABLED, PROBE_TIMEOUT, PROXY,
                    WARMUP_URL, YT_CLIENTS, YT_FALLBACKS, YT_NOAUTH_CLIENTS, YT_TRY_NO_COOKIES)
from cookies_util import COOKIES_PATH
from config import DISABLE_GENERIC
from errors import Busy
from formats import collect_options, get_fmt
from net import POOL, sess
from url_safety import is_public_url


# لا ننشئ yt-dlp بلا حدود عند الضغط. عدد مهام الاستخراج الفعلية يبقى محدوداً.
_EXTRACT_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, MAX_EXTRACT), thread_name_prefix="extract")
_EXTRACT_QUEUE = threading.BoundedSemaphore(max(1, MAX_EXTRACT) * (1 + EXTRACT_QUEUE_MULTIPLIER))
OK_CODES = (200, 206)
KEEP_FIELDS = ("format_id", "url", "ext", "protocol", "vcodec", "acodec", "height", "tbr", "abr",
               "filesize", "filesize_approx", "http_headers", "fps")

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
    return {"title": d.get("title"), "webpage_url": d.get("webpage_url") or d.get("original_url"),
            "uploader": d.get("uploader") or d.get("channel"),
            "duration": d.get("duration"), "thumbnail": d.get("thumbnail"),
            "extractor": str(d.get("extractor_key") or ""), "formats": fmts}


def search_soundcloud(query):
    """يحوّل عنوان أغنية إلى رابط SoundCloud عام بلا حاجة إلى Client ID."""
    query = re.sub(r"\s+", " ", (query or "").strip())
    if len(query) < 2 or len(query) > 200:
        raise ValueError("اكتب عنوان أغنية أطول قليلا")
    info = extract_raw("scsearch1:" + query, cookies=False)
    url = info.get("webpage_url")
    host = (urlsplit(url).hostname or "").lower().rstrip(".") if url else ""
    if not url or not (host == "soundcloud.com" or host.endswith(".soundcloud.com")):
        raise RuntimeError("لم أجد أغنية مطابقة على SoundCloud")
    return {"url": url, "title": info.get("title"), "uploader": info.get("uploader"),
            "thumbnail": info.get("thumbnail"), "duration": info.get("duration")}


def search_media(query, source="soundcloud", limit=10):
    """يبحث عن عدة نتائج قابلة للاختيار في SoundCloud أو YouTube."""
    query = re.sub(r"\s+", " ", (query or "").strip())
    if len(query) < 2 or len(query) > 200:
        raise ValueError("اكتب عنوانا أطول قليلا")
    if source not in ("soundcloud", "youtube"):
        raise ValueError("مصدر البحث غير صالح")
    prefix = "scsearch" if source == "soundcloud" else "ytsearch"
    limit = max(1, min(10, int(limit)))
    if not _EXTRACT_QUEUE.acquire(timeout=EXTRACT_WAIT_SEC):
        raise Busy("الخادم مشغول بطلبات بحث أخرى، حاول بعد قليل")
    future = None
    try:
        future = _EXTRACT_EXECUTOR.submit(_run_search, prefix + str(limit) + ":" + query)
        return future.result(timeout=max(30, EXTRACT_WAIT_SEC + 30))
    except FutureTimeout:
        if future and future.cancel():
            _EXTRACT_QUEUE.release()
        raise Busy("استغرق البحث وقتا أطول من المسموح، حاول مجددا")
    except Exception:
        if future is None:
            _EXTRACT_QUEUE.release()
        raise


def _run_search(search_url):
    try:
        opts = ytdl_opts(cookies=False)
        opts.update({"noplaylist": False, "extract_flat": "in_playlist", "playlistend": 10,
                     "ignoreerrors": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(search_url, download=False)
        results = []
        for entry in (data.get("entries") or []):
            if not entry:
                continue
            url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
            if not url or not url.startswith("https://"):
                continue
            results.append({"url": url, "title": entry.get("title") or url,
                            "uploader": entry.get("uploader") or entry.get("channel"),
                            "thumbnail": entry.get("thumbnail"), "duration": entry.get("duration")})
        return results
    finally:
        _EXTRACT_QUEUE.release()


def ytdl_opts(clients=None, cookies=True):
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
    if cookies and os.path.exists(COOKIES_PATH):
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


def _run_extract(url, clients=None, cookies=True):
    try:
        col = _Collect()
        opts = ytdl_opts(clients, cookies)
        opts["logger"] = col
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = slim(ydl.extract_info(url, download=False))
        if not info["formats"] and col.msgs:
            log("yt-dlp returned NO formats; messages:", " | ".join(col.msgs[-6:]))
        return info
    finally:
        _EXTRACT_QUEUE.release()


def extract_raw(url, clients=None, cookies=True):
    """يضع مهمة yt-dlp في طابور محدود وينتظر النتيجة بمهلة واضحة.

    إذا انتهت مهلة انتظار النتيجة، نحاول إلغاء المهمة إن لم تكن قد بدأت بعد.
    أما مهمة yt-dlp التي بدأت فعلا فلا يمكن قتلها بأمان من داخل ThreadPoolExecutor؛
    تبقى محكومة بمهلات yt-dlp، مع بقاء عددها الأقصى محدودا بـ MAX_EXTRACT.
    """
    if not _EXTRACT_QUEUE.acquire(timeout=EXTRACT_WAIT_SEC):
        raise Busy("الخادم مشغول بطلبات استخراج أخرى، حاول بعد قليل")
    future = None
    try:
        future = _EXTRACT_EXECUTOR.submit(_run_extract, url, clients, cookies)
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


def is_soundcloud(url):
    m = re.match(r"^https?://([^/:?#]+)", url)
    host = (m.group(1) if m else "").lower().rstrip(".")
    return host == "soundcloud.com" or host.endswith(".soundcloud.com")


def _has_adaptive(info):
    """هل فيها مسار فيديو أو صوت منفصل بروابط مباشرة (أساس الجودات العالية والصوت)؟"""
    for f in info.get("formats", []):
        if f.get("protocol") in ("http", "https") and f.get("url") and f.get("ext") != "mhtml":
            if f.get("vcodec") == "none" or f.get("acodec") == "none":
                return True
    return False


def _client_order():
    """قائمة محاولات (عملاء، هل نستخدم الكوكيز). الأولى بلا كوكيز لأنها وحدها تُبقي عملاء الصيغ المنفصلة."""
    now = time.time()
    recent = _last_good_client if _last_good_client is not None and now - _last_good_at < _CLIENT_TTL else None
    base = ([(YT_NOAUTH_CLIENTS or None, False)] if YT_TRY_NO_COOKIES else []) + [(None, True)] + \
           [(cl, True) for cl in YT_FALLBACKS]
    order = []
    for a in [recent] + base:
        if a is not None and a not in order:
            order.append(a)
    return order


def _extract_youtube(url):
    global _last_good_client, _last_good_at
    first_err, first_code, weak = None, None, None
    for attempt in _client_order():
        cl, use_cookies = attempt
        name = (",".join(cl) if cl else "default") + ("" if use_cookies else "+nocookies")
        t0 = time.time()
        try:
            info = extract_raw(url, cl, use_cookies)
        except Busy:
            raise
        except Exception as e:
            log(f"youtube client={name} FAILED after {time.time() - t0:.1f}s: {str(e)[:220]}")
            first_err = first_err or e
            continue
        t1 = time.time()
        video, audio = collect_options(info)
        if not (video or audio):   # نتيجة بلا صيغ مباشرة ليست نجاحاً: جرّب العميل التالي
            log(f"youtube client={name} returned no direct formats (total={len(info.get('formats', []))})")
            continue
        if not _has_adaptive(info):   # 360p الجاهزة فقط: جرّب عملاء أخرى بحثا عن الصيغ المنفصلة، واحتفظ بهذه كاحتياط
            log(f"youtube client={name} gave only muxed formats (total={len(info.get('formats', []))}); trying next")
            weak = weak or info
            continue
        code = probe(info) if PROBE_ENABLED else 200
        log(f"youtube client={name} extract={t1 - t0:.1f}s probe={time.time() - t1:.1f}s "
            f"formats={len(info.get('formats', []))} http={code}")
        if code in OK_CODES:
            _last_good_client = attempt
            _last_good_at = time.time()
            return info
        if first_code is None:
            first_code = code
    if weak:
        return weak
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


_REDIRECT_HOSTS = {"bit.ly", "buff.ly", "fb.me", "fb.watch", "goo.gl", "is.gd", "ow.ly", "pin.it",
                   "t.co", "tinyurl.com", "vm.tiktok.com"}


def _needs_redirect_resolution(url):
    """روابط المشاركة/الاختصار غالبا لا يطابقها yt-dlp قبل فك 301/302."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        path = parts.path.rstrip("/")
    except ValueError:
        return False
    return host in _REDIRECT_HOSTS or (host.endswith("facebook.com") and path.startswith("/share"))


def _resolve_redirects(url, max_hops=5):
    """يفك التحويلات HTTP مع منع التحويل إلى مضيف داخلي أو بروتوكول غير HTTP."""
    if not _needs_redirect_resolution(url):
        return url
    current = url
    headers = {"User-Agent": "Mozilla/5.0 (compatible; yt-dlp service)"}
    for _ in range(max_hops):
        try:
            with sess.get(current, allow_redirects=False, stream=True, timeout=(5, 10), headers=headers) as response:
                if response.status_code not in (301, 302, 303, 307, 308):
                    return current
                location = response.headers.get("Location")
        except Exception as exc:
            log(f"redirect resolution skipped: {str(exc)[:160]}")
            return url
        if not location:
            return current
        target = urljoin(current, location)
        if not is_public_url(target):
            log("redirect resolution blocked a non-public target")
            return url
        current = target
    return current


def smart_extract(url):
    resolved = _resolve_redirects(url)
    if resolved != url:
        log(f"resolved redirect: {url} -> {resolved}")
        url = resolved
    if is_youtube(url):
        return _extract_youtube(url)
    t = time.time()
    # كوكيز يوتيوب قد تكون غير صالحة أو تغيّر استجابة SoundCloud؛ لا نرسلها
    # إلى خدمة أخرى لا تحتاجها أصلًا.
    info = _with_backoff(lambda: extract_raw(url, cookies=not is_soundcloud(url)))
    log(f"{info.get('extractor')} extract={time.time() - t:.1f}s")
    return info


def _run_playlist(list_id, start, limit):
    try:
        opts = ytdl_opts(cookies=False)
        opts.update({"noplaylist": False, "extract_flat": "in_playlist", "playlist_items": f"{start + 1}-{start + limit}",
                     "ignore_no_formats_error": True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            d = ydl.extract_info(f"https://www.youtube.com/playlist?list={list_id}", download=False)
        entries = [e for e in (d.get("entries") or []) if e and e.get("id")]
        return {"title": d.get("title"), "count": d.get("playlist_count"),
                "items": [{"id": e["id"], "title": e.get("title"), "duration": e.get("duration"),
                           "uploader": e.get("uploader") or e.get("channel")} for e in entries]}
    finally:
        _EXTRACT_QUEUE.release()


def extract_playlist(list_id, start, limit):
    """صفحة من قائمة تشغيل عبر نفس الطابور المحدود (استخراج مسطّح بلا صيغ)."""
    if not _EXTRACT_QUEUE.acquire(timeout=EXTRACT_WAIT_SEC):
        raise Busy("الخادم مشغول بطلبات استخراج أخرى، حاول بعد قليل")
    try:
        future = _EXTRACT_EXECUTOR.submit(_run_playlist, list_id, start, limit)
    except Exception:
        _EXTRACT_QUEUE.release()
        raise
    try:
        return future.result(timeout=max(30, EXTRACT_WAIT_SEC + 30))
    except FutureTimeout:
        if future.cancel():
            _EXTRACT_QUEUE.release()
        raise Busy("استغرق جلب القائمة وقتا أطول من المسموح، حاول مجددا")
