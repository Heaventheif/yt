"""أنواع الأخطاء المشتركة."""
import re

from config import ERROR_MAX_LEN

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Busy(Exception):
    """الخادم مشغول (يُحوَّل إلى HTTP 429)"""


class UpstreamError(RuntimeError):
    """رفض المصدر الطلب بكود HTTP معيّن"""

    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class HttpFailure(Exception):
    """فشل معروف يُعرض للمستخدم برسالة وكود محددين"""

    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.msg = msg
        self.code = code


def clean_message(e):
    """رسالة الخطأ بدون ألوان ANSI ومقصوصة الطول"""
    return _ANSI.sub("", str(e)).strip()[:ERROR_MAX_LEN]
