"""تمرير الملف من المصدر إلى العميل على أجزاء (Range) مع جلب الجزء التالي مسبقا.
لا يعتمد على Flask."""
import re
import threading
from collections import namedtuple

from config import CHUNK, MAX_DOWNLOADS, MAX_STREAM_FAILS, READ_SIZE, UPSTREAM_TIMEOUT
from errors import UpstreamError
from net import POOL, sess

DL_SLOTS = threading.Semaphore(MAX_DOWNLOADS)   # تنزيلات متزامنة (خفيفة)
Upstream = namedtuple("Upstream", "resp total last ranged")


class Slot:
    """خانة تنزيل تُحرَّر مرة واحدة فقط مهما تكرر استدعاء release"""

    def __init__(self):
        self._lock = threading.Lock()
        self._done = False

    def release(self):
        with self._lock:
            if not self._done:
                self._done = True
                DL_SLOTS.release()


def acquire_slot():
    """يرجع Slot أو None إن كانت كل الخانات مشغولة"""
    return Slot() if DL_SLOTS.acquire(blocking=False) else None


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
    try:
        r = _get_range(fmt, cstart, end)
    except Exception as e:
        raise RuntimeError("تعذر الاتصال بمصدر الملف: " + type(e).__name__)
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
