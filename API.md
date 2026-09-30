# توثيق API — الاستخدام من JavaScript

- [نظرة سريعة](#نظرة-سريعة)
- [المصادقة](#المصادقة)
- [نقاط النهاية](#نقاط-النهاية)
- [العميل الجاهز (Node.js)](#العميل-الجاهز-nodejs)
- [وصفات جاهزة](#وصفات-جاهزة)
- [الاستخدام من المتصفح](#الاستخدام-من-المتصفح)
- [الأخطاء](#الأخطاء)
- [الأداء والحدود](#الأداء-والحدود)
- [أنواع البيانات (TypeScript)](#أنواع-البيانات-typescript)
- [استكشاف الأخطاء](#استكشاف-الأخطاء)

---

## نظرة سريعة

```js
const BASE = "https://your-app.onrender.com";   // رابط خدمتك على Render
const KEY  = process.env.YTDLP_KEY;             // قيمة API_KEY

// 1) معلومات الفيديو والجودات المتاحة
const r = await fetch(`${BASE}/info?url=${encodeURIComponent(url)}`, {
  headers: { "X-API-Key": KEY },
});
const info = await r.json();
if (!info.ok) throw new Error(info.error);
console.log(info.title, info.video.map(v => v.label));

// 2) تنزيل الملف عبر السيرفر
const res = await fetch(`${BASE}/stream?url=${encodeURIComponent(url)}&type=video&q=480`, {
  headers: { "X-API-Key": KEY },
});
if (!res.ok) throw new Error((await res.json()).error);
const buf = Buffer.from(await res.arrayBuffer());
```

> **لا حاجة لتنظيف الرابط.** السيرفر يحوّل الروابط تلقائيا (`m.site.com`، `youtu.be`، `shorts`، باراميترات التتبع…) إلى الصيغة القياسية، فيمكنك تمرير الرابط كما نسخه المستخدم.

---

## المصادقة

كل النقاط تحتاج المفتاح **عدا** `/health` و`/ping` و`/stats` و`/repo` والصفحات (`/`، `/docs`، `/encode`) ومسارات `/web/*`.

| الطريقة | مثال |
|---|---|
| هيدر (الأفضل) | `headers: { "X-API-Key": KEY }` |
| باراميتر | `?key=KEY` (يظهر في السجلات والروابط، استخدمه للاختبار فقط) |

المفتاح الخاطئ أو المفقود → `401 {"ok":false,"error":"unauthorized"}`.

> ⚠️ **لا تضع `API_KEY` في كود يعمل داخل المتصفح.** أي شخص يستطيع رؤيته. من المتصفح استخدم [مسارات `/web/*`](#الاستخدام-من-المتصفح) أو مرّر الطلبات عبر سيرفرك.

---

## نقاط النهاية

| المسار | المفتاح | الوظيفة |
|---|---|---|
| `GET /health` | لا | فحص الخدمة + إصدار yt-dlp |
| `GET /ping` | لا | زمن استجابة التطبيق بالمللي ثانية |
| `GET /stats` | لا | الطلبات والأخطاء ومتوسط/P95 الاستجابة |
| `GET /repo` | لا | الفرع وcommit ورابط المستودع |
| `GET /info?url=` | نعم | العنوان والجودات المتاحة |
| `GET /link?url=&type=&q=` | نعم | رابط مباشر من المصدر |
| `GET /stream?url=&type=&q=` | نعم | تنزيل الملف عبر السيرفر (يدعم Range) |
| `GET /web/info?url=` | لا* | مثل `/info` للواجهة العامة |
| `GET /web/dl?url=&fid=[&check=1]` | لا* | تنزيل صيغة محددة، أو فحصها فقط |
| `GET /cookies` | نعم | حالة الكوكيز المحمّلة |

\* محدودة بعدد الطلبات لكل IP، وتُعطَّل بـ `WEB_PUBLIC=0`.

### `GET /health`

```json
{ "ok": true, "yt_dlp": "2026.09.15" }
```

### `GET /info?url=URL`

```json
{
  "ok": true,
  "title": "عنوان الفيديو",
  "uploader": "القناة",
  "duration": 213,
  "thumbnail": "https://…/thumb.jpg",
  "video": [
    { "fid": "22", "label": "720p • MP4 • فيديو + صوت", "size": 25431022, "height": 720, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "has_audio": true, "has_video": true },
    { "fid": "137", "label": "1080p • MP4 • فيديو فقط", "size": null, "height": 1080, "ext": "mp4", "vcodec": "avc1", "acodec": "", "has_audio": false, "has_video": true }
  ],
  "audio": [
    { "fid": "140", "label": "M4A • 129kbps", "size": 3401002, "height": 0, "ext": "m4a", "abr": 129, "vcodec": "", "acodec": "mp4a", "has_audio": true, "has_video": false }
  ]
}
```

- `video` مرتبة من الأعلى جودة وتضم **كل الصيغ المباشرة**، بما فيها صيغ الفيديو المنفصلة عن الصوت. `audio` تضم كل صيغ الصوت المباشرة مرتبة حسب bitrate.
- `size` بالبايت وقد تكون `null` إذا لم يُعلنها المصدر.
- `fid` معرّف الصيغة، ويُستخدم مع `/web/dl`.
- النتيجة تُحفظ 20 دقيقة، فالطلب المتكرر لنفس الرابط فوري.

### `GET /link?url=URL&type=video|audio&q=720`

```json
{ "ok": true, "title": "…", "ext": "mp4", "url": "https://rr1---sn-….googlevideo.com/videoplayback?…" }
```

> ⚠️ الرابط موقّع لعنوان IP **السيرفر**. في يوتيوب غالبا يرفضه المصدر (403) إذا فتحته من جهاز آخر. لتنزيل موثوق استخدم `/stream`. في مواقع كثيرة أخرى يعمل الرابط المباشر من أي مكان.

### `GET /stream?url=URL&type=video|audio&q=720`

| الباراميتر | القيمة | ملاحظة |
|---|---|---|
| `url` | رابط الفيديو | مطلوب |
| `type` | `video` (افتراضي) أو `audio` | |
| `q` | ارتفاع الفيديو، مثل `480` | يختار أعلى جودة **لا تتجاوزه** (افتراضي 720). يُتجاهل مع `audio` (يختار أعلى bitrate) |

**هيدرات الرد**

| الهيدر | المعنى |
|---|---|
| `Content-Disposition` | اسم الملف (`filename*=UTF-8''…` يدعم العربية) |
| `Content-Length` | الحجم إن كان معروفا |
| `Accept-Ranges: bytes` | يدعم الاستئناف إن كان المصدر يدعمه |
| `Content-Range` | مع الرد `206` عند إرسال `Range` |

**الاستئناف:** أرسل `Range: bytes=START-` فيرد `206` ويكمل من البايت المطلوب.

### `GET /web/info?url=URL` و `GET /web/dl?url=URL&fid=FID`

- `/web/info` يرد بنفس شكل `/info` (ويرجع `404` إن لم توجد صيغ قابلة للتنزيل المباشر).
- `/web/dl?url=…&fid=…` يبدأ التنزيل.
- `/web/dl?url=…&fid=…&check=1` يتحقق دون تنزيل: `{ "ok": true, "size": 25431022 }`. مفيد لعرض الخطأ **قبل** بدء تنزيل المتصفح.
- `fid` يقبل الحروف والأرقام و`. - _ +` فقط.

---

## العميل الجاهز (Node.js)

الملفان `examples/client.js` و`examples/example.js`. يحتاج Node 18+ ولا مكتبات خارجية.

```js
const { YtdlpClient, YtdlpApiError } = require("./examples/client");

const api = new YtdlpClient(process.env.YTDLP_URL, process.env.YTDLP_KEY, {
  retries: 2,        // إعادة المحاولة عند 429/502/503 أو فشل الشبكة (2s ثم 4s)
  timeoutMs: 90_000, // مهلة وصول الرد (استخراج يوتيوب قد يأخذ وقتا)
});

const info = await api.info(url);                          // معلومات
const link = await api.link(url, { type: "video", q: 480 }); // رابط مباشر
const buf  = await api.buffer(url, { type: "audio" });     // Buffer (ملفات صغيرة)

// حفظ على القرص بدون تحميل الملف كله في الذاكرة + تقدّم
const { path, bytes } = await api.download(url, {
  type: "video", q: 480, dir: "./downloads",
  onProgress: (got, total) => console.log(got, "/", total ?? "؟"),
});
```

| الدالة | تُرجع |
|---|---|
| `health()` | `{ ok, yt_dlp }` |
| `info(url)` | كائن `/info` |
| `link(url, { type, q })` | `{ ok, title, ext, url }` |
| `stream(url, { type, q, range, signal })` | `Response` (الجسم Stream) |
| `buffer(url, opts)` | `Buffer` |
| `download(url, { type, q, dir, filename, onProgress, signal })` | `{ path, bytes }` |

**التعامل مع الأخطاء**

```js
try {
  await api.download(url, { q: 480 });
} catch (e) {
  if (e instanceof YtdlpApiError) {
    // e.status: 400 رابط غير صالح | 401 مفتاح خاطئ | 404 لا صيغة | 429 مشغول | 502 فشل المصدر | 0 لا اتصال/مهلة
    console.error(e.status, e.message); // e.message عربي جاهز للعرض
  } else throw e;
}
```

- أخطاء `400/401/404/409/416` لا تُعاد تلقائيا (إعادتها لا تفيد).
- `download` يحذف الملف الناقص إذا انقطع التنزيل.

---

## وصفات جاهزة

### إلغاء التنزيل وحدّ الوقت

```js
const ctl = new AbortController();
setTimeout(() => ctl.abort(), 5 * 60_000);          // ألغِ بعد 5 دقائق
await api.download(url, { signal: ctl.signal });
```

### استئناف تنزيل منقطع

```js
const fs = require("fs");
const { Readable } = require("stream");
const { pipeline } = require("stream/promises");

const file = "./downloads/video.mp4";
const have = fs.existsSync(file) ? fs.statSync(file).size : 0;

const res = await api.stream(url, { q: 480, range: `bytes=${have}-` });
if (res.status === 200 && have > 0) fs.rmSync(file); // المصدر لا يدعم Range: ابدأ من الصفر
await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(file, { flags: res.status === 206 ? "a" : "w" }));
```

### عدة روابط (بحد تزامن)

الخادم يسمح بعدد محدود من الاستخراجات (`MAX_CONCURRENT`، افتراضي 2) والتنزيلات (`MAX_DOWNLOADS`، افتراضي 6). لا ترسل مئات الطلبات دفعة واحدة:

```js
async function mapLimit(items, limit, fn) {
  const out = [], running = new Set();
  for (const item of items) {
    const p = fn(item).finally(() => running.delete(p));
    running.add(p); out.push(p);
    if (running.size >= limit) await Promise.race(running);
  }
  return Promise.allSettled(out);
}

const results = await mapLimit(urls, 2, (u) => api.download(u, { q: 360, dir: "./downloads" }));
results.forEach((r, i) => console.log(urls[i], r.status, r.reason?.message ?? r.value.path));
```

### تمرير التنزيل للمتصفح دون كشف المفتاح (Express)

```js
const express = require("express");
const { Readable } = require("stream");
const { YtdlpClient, YtdlpApiError } = require("./examples/client");

const api = new YtdlpClient(process.env.YTDLP_URL, process.env.YTDLP_KEY);
const app = express();

app.get("/download", async (req, res) => {
  try {
    const up = await api.stream(String(req.query.url), { type: req.query.type, q: req.query.q });
    for (const h of ["content-type", "content-disposition", "content-length"]) {
      if (up.headers.get(h)) res.setHeader(h, up.headers.get(h));
    }
    res.on("close", () => up.body.cancel().catch(() => {})); // المتصفح أغلق الاتصال
    Readable.fromWeb(up.body).pipe(res);
  } catch (e) {
    res.status(e instanceof YtdlpApiError && e.status || 502).json({ ok: false, error: e.message });
  }
});
app.listen(3000);
```

### بوت (تنزيل ثم رفع)

```js
const { path } = await api.download(url, { type: "video", q: 480, dir: "/tmp" });
await bot.sendVideo(chatId, fs.createReadStream(path)); // مثال: أي مكتبة بوت
fs.rmSync(path);                                        // نظّف الملف بعد الرفع
```

> استخدم `download` بدل `buffer` في البوتات: `buffer` يحمّل الملف كله في الذاكرة.

---

## الاستخدام من المتصفح

لا تستخدم المفتاح في المتصفح. استخدم مسارات `/web/*` (بلا مفتاح، ومحدودة بعدد الطلبات لكل IP).

**1) إن كان موقعك على نطاق آخر** فعّل CORS في متغيرات البيئة على Render:

```
CORS_ORIGIN=https://mysite.com
```

(أو `*` للتجربة). معطّل افتراضيا. لا يلزم إذا كانت صفحتك تُخدم من نفس السيرفر.

**2) الجلب والتنزيل:**

```js
const B = "https://your-app.onrender.com";

async function jget(path) {
  const r = await fetch(B + path);
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

async function download(url, height = 480) {
  const info = await jget("/web/info?url=" + encodeURIComponent(url));
  const pick = info.video.find(v => v.height <= height) || info.video.at(-1) || info.audio[0];
  const q = new URLSearchParams({ url, fid: pick.fid });

  await jget(`/web/dl?${q}&check=1`);        // يكشف الخطأ قبل بدء التنزيل
  location.href = `${B}/web/dl?${q}`;        // يبدأ التنزيل بمعالج المتصفح (لا يحتاج CORS ولا يستهلك الذاكرة)
}
```

**3) شريط تقدّم داخل الصفحة** (يحتاج CORS ويحمّل الملف في الذاكرة، فاستخدمه للملفات الصغيرة):

```js
const res = await fetch(`${B}/web/dl?${q}`);
const total = Number(res.headers.get("content-length")) || 0;
const reader = res.body.getReader();
const parts = []; let got = 0;
for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  parts.push(value); got += value.length;
  progress.value = total ? got / total : 0;
}
const a = Object.assign(document.createElement("a"), {
  href: URL.createObjectURL(new Blob(parts)), download: "video.mp4",
});
a.click();
```

---

## الأخطاء

كل الأخطاء بهذا الشكل مع كود HTTP مناسب:

```json
{ "ok": false, "error": "رسالة عربية" }
```

| الكود | المعنى | ماذا تفعل |
|---|---|---|
| 400 | رابط غير صالح أو باراميتر ناقص | صحّح الطلب |
| 401 | مفتاح خاطئ/مفقود | راجع `X-API-Key` |
| 404 | لا توجد صيغة مناسبة / الصيغة غير موجودة / الواجهة العامة معطلة | جرّب `q` آخر أو `type` آخر |
| 409 | تغيّرت الصيغ أثناء الطلب | أعد `/info` ثم جرّب |
| 416 | نطاق `Range` غير صالح | صحّح البايتات |
| 429 | مشغول (استخراجات أو تنزيلات كثيرة)، أو تجاوزت حد الطلبات | انتظر ثم أعد (العميل الجاهز يعيد تلقائيا) |
| 502 | فشل الاستخراج أو رفض المصدر (مثل حجب يوتيوب لـ IP السيرفر) | حدّث الكوكيز أو أعد لاحقا |

---

## الأداء والحدود

- **أول طلب بعد نوم الخدمة** (الخطة المجانية) قد يستغرق نصف دقيقة أو أكثر. لذلك مهلة العميل الافتراضية 90 ثانية. الـ keep-alive المدمج يقلل النوم.
- **أول استخراج ليوتيوب** أبطأ من غيره (حل تحديات المشغّل وPO Token). الطلب الثاني لنفس الرابط فوري من الكاش (20 دقيقة).
- الرابط الفاشل يُتذكّر 20 ثانية فلا يُعاد الاستخراج فورا.
- **حد الطلبات** لمسارات `/web/info` و`/web/dl?check=1`: `RATE_LIMIT_PER_MIN` لكل IP (افتراضي 30). مسارات المفتاح غير محدودة بـ IP لكنها تخضع لحدود التزامن.
- **المهلة** تُحسب لوصول الرد فقط. قراءة الجسم (التنزيل نفسه) بلا مهلة، فلا ينقطع تنزيل كبير.
- **الذاكرة** (512MB في الخطة المجانية): لا تستخدم `buffer()` للملفات الكبيرة، واستخدم `download()`.

---

## أنواع البيانات (TypeScript)

```ts
interface FormatOption {
  fid: string;            // معرّف الصيغة
  label: string;          // "720p • MP4" أو "M4A • 129kbps"
  size: number | null;    // بايت
  height: number;         // 0 للصوت
}

interface InfoResponse {
  ok: true;
  title: string | null;
  uploader: string | null;
  duration: number | null; // ثوان
  thumbnail: string | null;
  video: FormatOption[];   // كل الصيغ المباشرة من الأعلى جودة
  audio: FormatOption[];   // كل الصيغ المباشرة من الأعلى bitrate
  format_count: number;
  extractor?: string;
}

interface LinkResponse { ok: true; title: string | null; ext: string; url: string }
interface CheckResponse { ok: true; size: number | null }
interface ErrorResponse { ok: false; error: string }
```

---

## استكشاف الأخطاء

| العَرَض | السبب المحتمل |
|---|---|
| `401 unauthorized` | المفتاح خاطئ، أو أرسلته في هيدر باسم آخر |
| `Failed to fetch` / CORS في المتصفح | لم تفعّل `CORS_ORIGIN`، أو تستخدم مسارا بمفتاح من نطاق آخر |
| `429` متكرر | حد الطلبات لكل IP، أو خانات الاستخراج/التنزيل ممتلئة |
| `502` "رفض يوتيوب روابط التنزيل" | IP السيرفر محجوب: حدّث الكوكيز، وراجع سجلات `[timing]` |
| `/link` يعطي رابطا يرد 403 عندك | الرابط مرتبط بـ IP السيرفر، استخدم `/stream` |
| التنزيل يبدأ بلا حجم | المصدر لم يُعلن `Content-Length`؛ سلوك طبيعي، وشريط التقدم يعمل بلا نسبة |
| `TypeError: fetch is not a function` | Node أقدم من 18 |
