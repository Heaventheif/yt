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
| PROXY | اختياري |
