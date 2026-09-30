"""تمرير الملف من المصدر إلى العميل على أجزاء (Range) مع جلب الجزء التالي مسبقا.
لا يعتمد على Flask."""
import re
import threading
import time
from collections import namedtuple

from config import CHUNK, MAX_DOWNLOADS, MAX_STREAM_FAILS, PER_IP_STREAMS, READ_SIZE, UPSTREAM_RETRIES, UPSTREAM_TIMEOUT
from errors import UpstreamError
from net import POOL, sess
from url_safety import is_public_url

DL_SLOTS = threading.Semaphore(MAX_DOWNLOADS)   # تنزيلات متزامنة (خفيفة)
Upstream = namedtuple("Upstream", "resp total last ranged")


STATS = {"bytes": 0, "active": 0}   # للمراقبة في /health (تقريبي، يُصفَّر عند إعادة التشغيل)
_ip_active = {}
_ip_lock = threading.Lock()


def _ip_dec(ip):
    if ip:
        with _ip_lock:
            n = _ip_active.get(ip, 0) - 1
            if n > 0:
                _ip_active[ip] = n
            else:
                _ip_active.pop(ip, None)


class Slot:
    """خانة تنزيل تُحرَّر مرة واحدة فقط مهما تكرر استدعاء release"""

    def __init__(self, ip=None):
        self._lock = threading.Lock()
        self._done = False
        self._ip = ip
        STATS["active"] += 1

    def release(self):
        with self._lock:
            if not self._done:
                self._done = True
                STATS["active"] -= 1
                DL_SLOTS.release()
                _ip_dec(self._ip)


def acquire_slot(ip=None):
    """يرجع Slot أو None إن كانت الخانات مشغولة (أو تجاوز ip حده المتزامن)"""
    if ip and PER_IP_STREAMS > 0:
        with _ip_lock:
            if _ip_active.get(ip, 0) >= PER_IP_STREAMS:
                return None
            _ip_active[ip] = _ip_active.get(ip, 0) + 1
    else:
        ip = None
    if not DL_SLOTS.acquire(blocking=False):
        _ip_dec(ip)
        return None
    return Slot(ip)


def _get_range(fmt, start, end):
    headers = dict(fmt.get("http_headers") or {})
    headers["Range"] = f"bytes={start}-{end}"
    return sess.get(fmt["url"], headers=headers, stream=True, timeout=UPSTREAM_TIMEOUT)


def fetch_range(fmt, start, last):
    """الجزء التالي عند الاستئناف: يرجع الاستجابة أو None عند الفشل"""
    try:
        r = _get_range(fmt, start, min(last, start + CHUNK - 1))
    except Exception:
        return None
    if r.status_code == 206 or (r.status_code == 200 and start == 0):
        return r
    r.close()
    return None


def open_upstream(fmt, cstart=0, cend=None):
    """يفتح أول جزء ويرجع Upstream(resp, total, last, ranged) أو يرمي UpstreamError"""
    end = cstart + CHUNK - 1
    if cend is not None:
        end = min(end, cend)
    if not is_public_url(fmt.get("url", "")):
        raise RuntimeError("مصدر الملف غير مسموح")
    for attempt in range(UPSTREAM_RETRIES + 1):   # تأخير تصاعدي: 0.5s ثم 1s
        last_try = attempt == UPSTREAM_RETRIES
        try:
            r = _get_range(fmt, cstart, end)
        except Exception as e:
            if last_try:
                raise RuntimeError("تعذر الاتصال بمصدر الملف: " + type(e).__name__)
            time.sleep(0.5 * 2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and not last_try:
            r.close()
            time.sleep(0.5 * 2 ** attempt)
            continue
        break
    if r.status_code == 206:
        m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("Content-Range", ""))
        total = int(m.group(3)) if m and m.group(3).isdigit() else None
        ranged = True
    elif r.status_code == 200 and cstart == 0:
        cl = r.headers.get("Content-Length", "")
        total = int(cl) if cl.isdigit() else None
        ranged = False
    else:
        r.close()
        raise UpstreamError(r.status_code)
    last = (total - 1) if total else (1 << 62)
    if cend is not None:
        last = min(last, cend)
    return Upstream(r, total, last, ranged)


def _discard(fut):
    """يغلق اتصالا فُتح مسبقا ولم نعد بحاجته"""
    def _close(f):
        try:
            resp = f.result()
            if resp is not None:
                resp.close()
        except Exception:
            pass
    fut.add_done_callback(_close)


def _next_response(prefetched, fmt, pos, seg_end, last):
    """يختار استجابة الجزء التالي: المجلوبة مسبقا إن كانت تبدأ من pos، وإلا طلب جديد"""
    r = None
    if prefetched is not None:
        res = prefetched.result()
        if pos == seg_end + 1:
            r = res
        elif res is not None:
            res.close()
    return r if r is not None else fetch_range(fmt, pos, last)


def stream_gen(fmt, r, pos, last, ranged, slot):
    """يمرر الملف على أجزاء ويفتح اتصال الجزء التالي عند منتصف الجزء الحالي
    فلا يحدث توقف بين الأجزاء. مع إعادة محاولة عند الانقطاع."""
    fails = 0
    prefetched = None
    try:
        while True:
            seg_end = min(last, pos + CHUNK - 1)
            half = pos + (seg_end - pos) // 2
            got = 0
            try:
                for piece in r.iter_content(READ_SIZE):
                    if piece:
                        got += len(piece)
                        STATS["bytes"] += len(piece)
                        pos += len(piece)
                        yield piece
                        if ranged and prefetched is None and pos >= half and seg_end < last:
                            prefetched = POOL.submit(fetch_range, fmt, seg_end + 1, last)
            except Exception:
                fails += 1
            finally:
                r.close()
            if not ranged or pos > last:
                return
            if got == 0:
                fails += 1
            if fails > MAX_STREAM_FAILS:
                return
            fut, prefetched = prefetched, None
            r = _next_response(fut, fmt, pos, seg_end, last)
            if r is None:
                return
    finally:
        if prefetched is not None:
            _discard(prefetched)
        try:
            r.close()
        except Exception:
            pass
        slot.release()  # تحرير فوري عند الانتهاء أو انقطاع العميل
