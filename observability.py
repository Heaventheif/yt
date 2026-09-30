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
