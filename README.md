# ytdlp-render

API صغير لـ yt-dlp يعمل على Render (الخطة المجانية).

## النشر
1. ارفع هذا المجلد إلى مستودع GitHub.
2. في Render: New → Blueprint → اختر المستودع (يقرأ render.yaml تلقائيا).
3. بعد النشر انسخ قيمة `API_KEY` من Environment.
4. (مهم ليوتيوب) أضف `COOKIES_B64`:
   - صدّر كوكيز يوتيوب بصيغة Netscape (إضافة "Get cookies.txt LOCALLY") من حساب ثانوي، في نافذة خاصة.
   - حوّلها: `base64 -w0 cookies.txt` (على ويندوز: `certutil -encode` أو أي أداة base64).
5. الـ keep-alive مدمج: التطبيق يزور رابطه العام (`RENDER_EXTERNAL_URL` يوفره Render تلقائيا) كل 14 دقيقة لمنع النوم. يمكنك إضافة UptimeRobot كنسخة احتياطية.

## الاستخدام
> 📘 **توثيق API كامل مع أمثلة JavaScript: [API.md](API.md)** (عميل جاهز في `examples/client.js`).

- `/` واجهة عامة بدون مفتاح: الصق الرابط، اختر الفيديو/الصوت والجودة ثم نزّل (محمية بحد طلبات لكل IP).
- `/encode` أداة تشفير الكوكيز إلى base64 داخل المتصفح (بدون إرسال شيء لأي سيرفر).
- `/docs` صفحة اختبار وتوثيق الـ API (تحتاج المفتاح).

جميع الطلبات تحتاج الهيدر `X-API-Key` (أو `?key=`).

- `GET /health`
- `GET /info?url=...`
- `GET /link?url=...&type=video|audio&q=720`
- `GET /stream?url=...&type=video|audio&q=720`  ← يحمّل الملف عبر السيرفر

مثال Node.js (لبوتك):
```js
const res = await fetch(`${BASE}/stream?url=${encodeURIComponent(url)}&type=video&q=480`,
  { headers: { "X-API-Key": KEY } });
const buf = Buffer.from(await res.arrayBuffer());
```

## متغيرات البيئة
| المتغير | الوصف |
|---|---|
| API_KEY | مفتاح الحماية |
| COOKIES_B64 | كوكيز base64 (اختياري لكن يفيد يوتيوب) |
| ENABLE_POT | 1 لتشغيل سيرفر PO Token |
| AUTO_UPDATE | 1 لتحديث yt-dlp عند كل تشغيل |
| YT_CLIENTS | مثال: `tv,mweb` (اتركه فارغا للافتراضي) |
| MAX_CONCURRENT | عدد الطلبات المتزامنة (افتراضي 2) |
| KEEP_ALIVE_MINUTES | فترة الـ ping الذاتي (افتراضي 14، و0 للتعطيل) |
| SELF_URL | اختياري: رابط الخدمة إن لم يتوفر RENDER_EXTERNAL_URL |
| WEB_PUBLIC | 1 لتفعيل الواجهة العامة بدون مفتاح (0 للتعطيل) |
| RATE_LIMIT_PER_MIN | حد طلبات الواجهة العامة لكل IP (افتراضي 10) |
| MAX_DOWNLOADS | تنزيلات متزامنة (افتراضي 3) |
| CORS_ORIGIN | لاستدعاء الخدمة من متصفح موقع آخر، مثل `https://mysite.com` (معطّل افتراضيا) |
| PROXY | اختياري |

## الأداء والتنزيل
- التنزيل يتم على أجزاء (Range) مثل yt-dlp، مع إعادة محاولة عند الانقطاع ودعم استئناف التنزيل.
- نتائج التحليل تُحفظ 20 دقيقة (CACHE_TTL_SEC) فلا يُعاد الاستخراج عند التنزيل.
- ليوتيوب: يفحص التطبيق أن الروابط مقبولة، وإن رُفضت يجرب عملاء بديلين (YT_FALLBACK_CLIENTS).
- الحدود: MAX_CONCURRENT (استخراج، افتراضي 2)، MAX_DOWNLOADS (تنزيلات متزامنة، افتراضي 6)، RATE_LIMIT_PER_MIN (افتراضي 30).
- لتحديث yt-dlp: أعد النشر من Render (Manual Deploy → Clear build cache & deploy).

## الصيغ والجودات
- `/info` و`/web/info` يعرضان **كل الصيغ المباشرة** المتاحة، وليس صيغة واحدة لكل ارتفاع.
- كل خيار يتضمن `fid` و`ext` و`vcodec` و`acodec` و`size` و`height`/`abr`.
- صيغ الفيديو المنفصلة عن الصوت تُعرض كما هي ويمكن تنزيلها منفردة؛ الدمج يحتاج ffmpeg في العميل.

## تسريع الجلب (fetch)
- `url_utils.py`: يحوّل أي رابط (m.site.com، youtu.be، shorts، music...) إلى الصيغة القياسية ويحذف باراميترات التتبع، فيصبح لنفس الفيديو مفتاح كاش واحد. يعمل أيضا كسكريبت: `python url_utils.py "رابط"`.
- استخراج يوتيوب يبدأ بآخر عميل نجح (GOOD_CLIENT) بدل تجربة الافتراضي الفاشل أولا.
- فحص الروابط (probe) يتم بالتوازي، وتخطي HLS/DASH أثناء الاستخراج.
- التنزيل يفتح اتصال الجزء التالي مسبقا (بدون توقف بين الأجزاء).
- `WARMUP=1` (افتراضي): تسخين yt-dlp عند الإقلاع.

## هيكل الكود
| الملف | المسؤولية |
|---|---|
| `app.py` | المسارات (Routes) فقط، ونقطة الدخول `app:app` |
| `config.py` | متغيرات البيئة والثوابت المسماة |
| `errors.py` | `Busy` و`UpstreamError` و`HttpFailure` وتنظيف الرسائل |
| `net.py` | جلسة HTTP مشتركة ومجمّع الخيوط |
| `formats.py` | دوال نقية لاختيار الصيغ (بدون شبكة ولا Flask) |
| `extractor.py` | yt-dlp: الخيارات، الفحص المتوازي، اختيار عميل يوتيوب |
| `info_cache.py` | كاش TTL، منع الاستخراج المكرر، تذكّر الأخطاء |
| `streaming.py` | تمرير الملف على أجزاء مع الجلب المسبق (بدون Flask) |
| `serving.py` | استجابة التنزيل: Range، الهيدرات، إعادة الاستخراج عند انتهاء الرابط |
| `security.py` | المفتاح وحد الطلبات لكل IP |
| `url_utils.py` | تطبيع الروابط |
| `keepalive.py` | منع نوم الخدمة |
| `examples/` | عميل JavaScript جاهز ومثال (انظر API.md) |

## الاختبارات
```
python -m unittest discover -s tests -v
```
تعمل بدون إنترنت: سيرفر ملفات محلي يحاكي المصدر (Range، وانتهاء الرابط 403).

### تحسينات التحمل والأداء

الإصدار الحالي يستخدم طابورًا محدودًا لاستخراج `yt-dlp`، وsingle-flight بحيث الطلبات المتزامنة لنفس الرابط تشترك في عملية استخراج واحدة، وحدًا مستقلاً لطلبات `/info` و`/link` و`/stream`. كما أن فحص `probe` معطّل افتراضيًا لتقليل طلبات الشبكة، ويمكن تفعيله عبر `PROBE_ON_EXTRACT=1` عند الحاجة.

إعدادات إضافية: `API_RATE_LIMIT_PER_MIN`، `EXTRACT_QUEUE_MULTIPLIER`، `EXTRACT_WAIT_SEC`، `PROBE_ON_EXTRACT`، `WORKERS`، و`THREADS`.
