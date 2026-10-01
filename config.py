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
EXTRACT_QUEUE_MULTIPLIER = max(1, int(os.getenv("EXTRACT_QUEUE_MULTIPLIER", "2")))
PROBE_ENABLED = os.getenv("PROBE_ON_EXTRACT", "0") == "1"
MAX_DOWNLOADS = int(os.getenv("MAX_DOWNLOADS", "6"))      # تنزيلات متزامنة
MAX_EXTRACT = int(os.getenv("MAX_CONCURRENT", "1"))       # استخراجات متزامنة (ثقيلة)
CACHE_TTL = int(os.getenv("CACHE_TTL_SEC", "1200"))
CACHE_MAX = int(os.getenv("CACHE_MAX", "80"))
CHUNK = int(float(os.getenv("CHUNK_MB", "8")) * 1048576)  # حجم الجزء (Range)

YT_CLIENTS = _clients(os.getenv("YT_CLIENTS", ""))   # عملاء المحاولة المسجَّلة بالكوكيز (فارغ = الافتراضي لـ yt-dlp)
# محاولة بلا كوكيز: yt-dlp يحذف عملاء visionos/android_vr (أصحاب الصيغ المنفصلة بروابط مباشرة) فور وجود كوكيز،
# فتبقى 360p فقط. لذلك نجرب أولا بدون كوكيز كما يفعل yt.sh، ثم بالكوكيز كاحتياط.
YT_NOAUTH_CLIENTS = _clients(os.getenv("YT_NOAUTH_CLIENTS", "default,android_vr"))
YT_TRY_NO_COOKIES = os.getenv("YT_TRY_NO_COOKIES", "1") == "1"
YT_FALLBACKS = [_clients(x) for x in os.getenv("YT_FALLBACK_CLIENTS", "tv;mweb").split(";") if x.strip()]

KEEP_ALIVE_MIN = int(os.getenv("KEEP_ALIVE_MINUTES", "10"))
SELF_URL = os.getenv("SELF_URL") or os.getenv("RENDER_EXTERNAL_URL", "")

# ---- ثوابت (كانت أرقاما مبعثرة في الكود) ----
EXTRACT_WAIT_SEC = int(os.getenv("EXTRACT_WAIT_SEC", "45"))          # أقصى انتظار لفتح خانة استخراج
ERROR_CACHE_SEC = 20           # مدة تذكّر فشل رابط قبل إعادة المحاولة
MAX_CACHED_ERRORS = 200
MAX_TRACKED_IPS = 5000
MAX_REMEMBERED_ORIGINALS = 500
RATE_WINDOW_SEC = 60
ERROR_MAX_LEN = 400
READ_SIZE = 262144             # حجم القراءة من المصدر (256KB)
UPSTREAM_TIMEOUT = (10, 30)    # (اتصال، قراءة) بالثواني
PROBE_TIMEOUT = (5, 8)
POOL_WORKERS = 12
REFRESH_CODES = (401, 403, 404, 410)   # أكواد تعني أن رابط المصدر انتهى فنعيد الاستخراج
MAX_STREAM_FAILS = 3
WARMUP_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

# ---- حدود الموارد والأمان (جديد) ----
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "0"))            # 0 = بلا حد؛ أكبر حجم ملف مسموح بتمريره
PER_IP_STREAMS = int(os.getenv("PER_IP_STREAMS", "2"))      # تنزيلات متزامنة لكل IP في الواجهة العامة (0 = بلا حد)
ALLOWED_HOSTS = [h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]  # فارغ = كل المواقع
ALLOW_PRIVATE_URLS = os.getenv("ALLOW_PRIVATE_URLS", "0") == "1"   # للاختبارات المحلية فقط
DISABLE_GENERIC = os.getenv("DISABLE_GENERIC", "0") == "1"  # تعطيل مستخرج generic (يمنع استخدام الخدمة كـ proxy لأي رابط)
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))     # 0 = أول عنوان في X-Forwarded-For، N = العنوان رقم N من اليمين
UPSTREAM_RETRIES = int(os.getenv("UPSTREAM_RETRIES", "2"))  # إعادة محاولة فتح المصدر مع تأخير تصاعدي
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# ---- دمج ffmpeg (فيديو منفصل + صوت منفصل) ----
MUX_ENABLED = os.getenv("MUX_ENABLED", "1") == "1"     # 0 = عرض الصيغ المباشرة فقط
MAX_MERGES = max(1, int(os.getenv("MAX_MERGES", "1")))  # عمليات ffmpeg متزامنة (ذاكرة 512MB)

# ---- تحويل MP3 (ffmpeg libmp3lame) ----
MP3_ENABLED = os.getenv("MP3_ENABLED", "1") == "1"
MP3_BITRATES = sorted({int(x) for x in os.getenv("MP3_BITRATES", "128,192").split(",") if x.strip().isdigit()}, reverse=True)
