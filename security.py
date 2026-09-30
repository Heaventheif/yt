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


def rate_ok(limit=None):
    """يحد الطلبات لكل IP، ويمكن تمرير حد مختلف حسب نوع المسار."""
    limit = RATE_LIMIT if limit is None else limit
    now = time.time()
    ip = client_ip()
    with _hits_lock:
        if len(_hits) >= MAX_TRACKED_IPS:
            stale = [k for k, ts in _hits.items() if not ts or now - ts[-1] >= RATE_WINDOW_SEC]
            for k in stale[: max(1, len(stale) - MAX_TRACKED_IPS // 2)]:
                _hits.pop(k, None)
            if len(_hits) >= MAX_TRACKED_IPS:
                return False
        recent = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW_SEC]
        allowed = len(recent) < limit
        if allowed:
            recent.append(now)
        _hits[ip] = recent
        return allowed
