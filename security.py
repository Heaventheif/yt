"""التحقق من المفتاح وتحديد معدل الطلبات لكل IP."""
import threading
import time
from flask import request
import hmac

from config import ALLOW_KEY_QUERY, API_KEY, MAX_TRACKED_IPS, RATE_LIMIT, RATE_WINDOW_SEC, TRUSTED_PROXY_HOPS


def auth_ok():
    if not API_KEY:
        return True
    supplied = request.headers.get("X-API-Key") or (request.args.get("key") if ALLOW_KEY_QUERY else "") or ""
    return hmac.compare_digest(supplied.encode(), API_KEY.encode())


def client_ip():
    parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    if parts:
        hops = TRUSTED_PROXY_HOPS   # 0 = السلوك القديم (أول عنوان). N>0 = من اليمين، أصعب على التزوير
        return parts[-hops] if 0 < hops <= len(parts) else parts[0]
    return request.remote_addr or "?"


_hits = {}
_hits_lock = threading.Lock()


def rate_ok(limit=None, bucket="web"):
    """يحد الطلبات لكل IP داخل سلّة مستقلة (web/api/dl/thumb/tele) كي لا يستهلك نوعٌ حصةَ نوع آخر."""
    limit = RATE_LIMIT if limit is None else limit
    now = time.time()
    ip = f"{bucket}|{client_ip()}"
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
