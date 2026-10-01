"""سجل أخطاء JSON خفيف + Sentry اختياري (لا يُحمَّل إلا إذا حُدد SENTRY_DSN وثُبّتت الحزمة)."""
import json
import time

from config import SENTRY_DSN

_sentry = None


def init():
    global _sentry
    if not SENTRY_DSN:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0, send_default_pii=False)
        _sentry = sentry_sdk
    except ImportError:
        print("[sentry] SENTRY_DSN محدد لكن sentry-sdk غير مثبّت", flush=True)


def log_error(e, **ctx):
    print(json.dumps({"t": int(time.time()), "level": "error", "type": type(e).__name__,
                      "msg": str(e)[:300], **ctx}, ensure_ascii=False), flush=True)


def capture(e):
    if _sentry:
        _sentry.capture_exception(e)


# ---- عدّادات خفيفة في الذاكرة (لا PII) تُعرض في /metrics ----
import threading as _t

EVENTS = {"info_hit", "info_miss", "dl_start", "dl_ok", "dl_fail", "sw_hit", "sw_miss", "cache_evict",
          "offline_ok", "offline_fail", "integrity_fail", "quota_denied", "lcp_ms", "inp_ms"}
_lock = _t.Lock()
_counters = {}


def count(name, value=1):
    if name not in EVENTS:
        return False
    with _lock:
        c = _counters.setdefault(name, {"n": 0, "sum": 0.0, "max": 0.0})
        c["n"] += 1
        c["sum"] += value
        c["max"] = max(c["max"], value)
    return True


def snapshot():
    with _lock:
        return {k: dict(v) for k, v in _counters.items()}
