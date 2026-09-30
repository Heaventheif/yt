"""ردود JSON موحدة للأخطاء."""
from flask import jsonify

from errors import Busy, HttpFailure, clean_message
from observability import capture, log_error


def jerr(msg, code=502):
    return jsonify(ok=False, error=msg), code


def err(e):
    if isinstance(e, Busy):
        return jerr(str(e), 429)
    log_error(e)
    if not isinstance(e, HttpFailure) and type(e).__name__ != "DownloadError":
        capture(e)   # أخطاء المستخدم الشائعة (فيديو خاص/محذوف) لا تُرسل لـ Sentry
    return jerr(clean_message(e) or "خطأ غير معروف", 502)
