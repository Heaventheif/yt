"""كل الإعدادات (متغيرات البيئة) والثوابت في مكان واحد."""
import os


def _clients(value):
    return [c.strip() for c in value.split(",") if c.strip()]


# ---- من متغيرات البيئة ----
API_KEY = os.getenv("API_KEY", "")
PROXY = os.getenv("PROXY", "")
WEB_PUBLIC = os.getenv("WEB_PUBLIC", "1") == "1"
WARMUP = os.getenv("WARMUP", "1") == "1"
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "")   # مثال: https://mysite.com أو * (معطّل افتراضيا)

RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))   # حد طلبات الواجهة العامة لكل IP
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT_PER_MIN", "60"))
EXTRACT_QUEUE_MULTIPLIER = max(1, int(os.getenv("EXTRACT_QUEUE_MULTIPLIER", "4")))
PROBE_ENABLED = os.getenv("PROBE_ON_EXTRACT", "0") == "1"
MAX_DOWNLOADS = int(os.getenv("MAX_DOWNLOADS", "6"))      # تنزيلات متزامنة
MAX_EXTRACT = int(os.getenv("MAX_CONCURRENT", "2"))       # استخراجات متزامنة (ثقيلة)
CACHE_TTL = int(os.getenv("CACHE_TTL_SEC", "1200"))
CACHE_MAX = int(os.getenv("CACHE_MAX", "80"))
LINK_CACHE_SEC = max(1, int(os.getenv("LINK_CACHE_SEC", "90")))
LINK_CACHE_MAX = max(1, int(os.getenv("LINK_CACHE_MAX", "300")))
CHUNK = int(float(os.getenv("CHUNK_MB", "16")) * 1048576)  # حجم الجزء (Range)

YT_CLIENTS = _clients(os.getenv("YT_CLIENTS", ""))
YT_FALLBACKS = [_clients(x) for x in os.getenv("YT_FALLBACK_CLIENTS", "android_vr;tv;mweb").split(";") if x.strip()]

KEEP_ALIVE_MIN = int(os.getenv("KEEP_ALIVE_MINUTES", "14"))
SELF_URL = os.getenv("SELF_URL") or os.getenv("RENDER_EXTERNAL_URL", "")

# ---- ثوابت (كانت أرقاما مبعثرة في الكود) ----
EXTRACT_WAIT_SEC = int(os.getenv("EXTRACT_WAIT_SEC", "45"))          # أقصى انتظار لفتح خانة استخراج
ERROR_CACHE_SEC = 20           # مدة تذكّر فشل رابط قبل إعادة المحاولة
MAX_CACHED_ERRORS = 200
MAX_TRACKED_IPS = 5000
MAX_REMEMBERED_ORIGINALS = 500
RATE_WINDOW_SEC = 60
ERROR_MAX_LEN = 400
READ_SIZE = max(65536, int(os.getenv("READ_SIZE_KB", "512")) * 1024)
UPSTREAM_TIMEOUT = (10, 30)    # (اتصال، قراءة) بالثواني
PROBE_TIMEOUT = (5, 8)
POOL_WORKERS = 12
REFRESH_CODES = (401, 403, 404, 410)   # أكواد تعني أن رابط المصدر انتهى فنعيد الاستخراج
MAX_STREAM_FAILS = 3
WARMUP_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
