"""قياسات خفيفة داخل الذاكرة لعرض الصحة والأداء دون قاعدة بيانات."""
import threading
import time
from collections import deque

_started = time.time()
_lock = threading.Lock()
_total = 0
_errors = 0
_durations = deque(maxlen=500)
_routes = {}

def record(path, status, elapsed):
    global _total, _errors
    with _lock:
        _total += 1
        _errors += int(status >= 400)
        _durations.append(elapsed * 1000)
        item = _routes.setdefault(path, {"requests": 0, "errors": 0, "last_ms": 0.0})
        item["requests"] += 1
        item["errors"] += int(status >= 400)
        item["last_ms"] = round(elapsed * 1000, 2)

def snapshot():
    with _lock:
        values = sorted(_durations)
        avg = sum(values) / len(values) if values else 0
        p95 = values[min(len(values) - 1, int(len(values) * .95))] if values else 0
        return {"ok": True, "uptime_sec": round(time.time() - _started, 1),
                "requests": _total, "errors": _errors, "avg_ms": round(avg, 2),
                "p95_ms": round(p95, 2), "routes": dict(_routes)}
