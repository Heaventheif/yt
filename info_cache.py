"""كاش نتائج الاستخراج + منع الاستخراج المكرر لنفس الرابط + تذكّر الأخطاء القصيرة."""
import threading
import time
from collections import OrderedDict

from config import (CACHE_MAX, CACHE_TTL, ERROR_CACHE_SEC, MAX_CACHED_ERRORS,
                    MAX_REMEMBERED_ORIGINALS)
from errors import Busy, clean_message
from extractor import smart_extract


class TTLCache:
    """LRU بسيط بمدة صلاحية، آمن للخيوط"""

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


_cache = TTLCache(CACHE_TTL, CACHE_MAX)
_errors = {}      # url -> (وقت، رسالة)
_inflight = {}    # url -> قفل: الطلبات المتزامنة لنفس الرابط تنتظر استخراجا واحدا
_originals = {}   # الرابط المطبَّع -> الرابط الأصلي (احتياط إن فشل المطبَّع)
_lock = threading.Lock()


def remember_original(normalized, original):
    if len(_originals) > MAX_REMEMBERED_ORIGINALS:
        _originals.clear()
    _originals[normalized] = original


def _extract(url):
    try:
        return smart_extract(url)
    except Busy:
        raise
    except Exception:
        original = _originals.get(url)  # إن فشل الرابط المطبَّع جرّب الأصلي مرة واحدة
        if not original:
            raise
        return smart_extract(original)


def _raise_recent_error(url):
    e = _errors.get(url)
    if e and time.time() - e[0] < ERROR_CACHE_SEC:
        raise RuntimeError(e[1])


def _record_error(url, e):
    if len(_errors) > MAX_CACHED_ERRORS:
        _errors.clear()
    _errors[url] = (time.time(), clean_message(e))


def get_info(url, fresh=False):
    if not fresh:
        cached = _cache.get(url)
        if cached:
            return cached
        _raise_recent_error(url)
    with _lock:
        url_lock = _inflight.setdefault(url, threading.Lock())
    with url_lock:
        if not fresh:
            cached = _cache.get(url)
            if cached:
                return cached
        try:
            info = _extract(url)
        except Busy:
            raise
        except Exception as e:
            _record_error(url, e)
            raise
        finally:
            with _lock:
                _inflight.pop(url, None)
        _errors.pop(url, None)
        _cache.put(url, info)
        return info
