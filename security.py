"""التحقق من المفتاح وتحديد معدل الطلبات لكل IP."""
import threading
import time

from flask import request

from config import API_KEY, MAX_TRACKED_IPS, RATE_LIMIT, RATE_WINDOW_SEC


def auth_ok():
    if not API_KEY:
        return True
    return (request.headers.get("X-API-Key") or request.args.get("key")) == API_KEY


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() or request.remote_addr or "?"


_hits = {}
_hits_lock = threading.Lock()


def rate_ok():
    """يسجّل الطلب ويرجع False إن تجاوز الـ IP الحد خلال الدقيقة الأخيرة"""
    now = time.time()
    ip = client_ip()
    with _hits_lock:
        if len(_hits) > MAX_TRACKED_IPS:
            _hits.clear()
        recent = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW_SEC]
        allowed = len(recent) < RATE_LIMIT
        if allowed:
            recent.append(now)
        _hits[ip] = recent
        return allowed
