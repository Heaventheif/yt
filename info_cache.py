"""كاش نتائج الاستخراج + single-flight حقيقي باستخدام Future."""
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future

from config import (CACHE_MAX, CACHE_TTL, ERROR_CACHE_SEC, INFO_CACHE_MAX_BYTES, MAX_CACHED_ERRORS,
                    MAX_REMEMBERED_ORIGINALS)
from errors import Busy, clean_message
from extractor import extract_playlist, smart_extract


class TTLCache:
    def __init__(self, ttl, max_items):
        self._ttl, self._max = ttl, max_items
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item and time.time() - item[0] < self._ttl:
                self._items.move_to_end(key)
                return item[1]
            self._items.pop(key, None)
        return None

    def put(self, key, value):
        with self._lock:
            self._items[key] = (time.time(), value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)


class ByteTTLCache(TTLCache):
    """TTL + LRU بسقف بالبايت (الذاكرة 512MB، لا نعتمد على عدد العناصر فقط)."""

    def __init__(self, ttl, max_items, max_bytes):
        super().__init__(ttl, max_items)
        self._max_bytes = max_bytes
        self._bytes = 0

    @property
    def bytes(self):
        return self._bytes

    def _drop(self, key):
        item = self._items.pop(key, None)
        if item:
            self._bytes -= item[2]
        return item

    def get(self, key):
        with self._lock:
            item = self._items.get(key)
            if item and time.time() - item[0] < self._ttl:
                self._items.move_to_end(key)
                return item[1]
            self._drop(key)
        return None

    def put(self, key, value):
        size = len(json.dumps(value, separators=(",", ":"), default=str))
        with self._lock:
            self._drop(key)
            self._items[key] = (time.time(), value, size)
            self._bytes += size
            while self._items and (len(self._items) > self._max or self._bytes > self._max_bytes):
                oldest = next(iter(self._items))
                if oldest == key and len(self._items) == 1:
                    break
                self._drop(oldest)


_cache = ByteTTLCache(CACHE_TTL, CACHE_MAX, INFO_CACHE_MAX_BYTES)
_errors = {}
_inflight = {}  # url -> Future: كل الطلبات لنفس الرابط تشترك في استخراج واحد
_originals = {}
_lock = threading.Lock()


def remember_original(normalized, original):
    with _lock:
        if len(_originals) >= MAX_REMEMBERED_ORIGINALS:
            _originals.clear()
        _originals[normalized] = original


def _extract(url):
    try:
        return smart_extract(url)
    except Busy:
        raise
    except Exception:
        with _lock:
            original = _originals.get(url)
        if not original:
            raise
        return smart_extract(original)


def _raise_recent_error(url):
    with _lock:
        e = _errors.get(url)
    if e and time.time() - e[0] < ERROR_CACHE_SEC:
        raise RuntimeError(e[1])


def _record_error(url, e):
    with _lock:
        if len(_errors) >= MAX_CACHED_ERRORS:
            _errors.clear()
        _errors[url] = (time.time(), clean_message(e))


def _run_and_cache(url):
    try:
        info = _extract(url)
        _cache.put(url, info)
        with _lock:
            _errors.pop(url, None)
        return info
    except Busy:
        raise
    except Exception as e:
        _record_error(url, e)
        raise


def get_info(url, fresh=False):
    # fast path: الطلب العادي يستفيد من الكاش قبل إنشاء Future.
    if not fresh:
        cached = _cache.get(url)
        if cached:
            return cached
        _raise_recent_error(url)

    # ننشئ/نلتقط Future واحدة لكل URL. هذا يمنع تشغيل yt-dlp عدة مرات
    # لنفس الرابط عند وصول طلبات متزامنة.
    with _lock:
        future = _inflight.get(url)
        if future is None:
            future = Future()
            _inflight[url] = future
            owner = True
        else:
            owner = False

    if owner:
        try:
            # double-check مهم: قد يكون طلب آخر أنهى الاستخراج وملأ الكاش
            # قبل أن يصل هذا المالك إلى هنا. عندها لا نعيد الاستخراج بلا داع.
            # الطلب العادي فقط يعيد استخدام نتيجة ظهرت بعد الـ fast path.
            # fresh يتجاهل الكاش القديم عمداً.
            cached = _cache.get(url) if not fresh else None
            if cached:
                future.set_result(cached)
            else:
                future.set_result(_run_and_cache(url))
        except BaseException as e:
            future.set_exception(e)
        finally:
            with _lock:
                if _inflight.get(url) is future:
                    _inflight.pop(url, None)

    # fresh يتجاهل الكاش القديم، لكنه لا يتجاوز extraction جاريا بالفعل.
    return future.result()


_playlists = TTLCache(300, 60)


def get_playlist(list_id, start, limit):
    key = (list_id, start, limit)
    hit = _playlists.get(key)
    if hit:
        return hit
    page = extract_playlist(list_id, start, limit)
    _playlists.put(key, page)
    return page
