"""ردود JSON موحدة للأخطاء."""
from flask import jsonify

from errors import Busy, clean_message


def jerr(msg, code=502):
    return jsonify(ok=False, error=msg), code


def err(e):
    if isinstance(e, Busy):
        return jerr(str(e), 429)
    return jerr(clean_message(e) or "خطأ غير معروف", 502)
