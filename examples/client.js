// عميل JavaScript لـ ytdlp-render — يعمل على Node 18+ (fetch مدمج) ومعظمه يعمل في المتصفح.
//
//   const { YtdlpClient } = require("./client");
//   const api = new YtdlpClient("https://your-app.onrender.com", process.env.YTDLP_KEY);
//   const info = await api.info("https://youtu.be/VIDEO_ID");
//   await api.download("https://youtu.be/VIDEO_ID", { type: "video", q: 480, dir: "./downloads" });

const fs = require("fs");
const path = require("path");
const { Readable } = require("stream");
const { pipeline } = require("stream/promises");

class YtdlpApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "YtdlpApiError";
    this.status = status; // كود HTTP (0 = فشل اتصال/مهلة)
  }
}

const RETRY_STATUS = new Set([429, 502, 503, 504]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class YtdlpClient {
  /**
   * @param {string} baseUrl  مثل https://your-app.onrender.com
   * @param {string} apiKey   قيمة API_KEY
   * @param {{retries?: number, timeoutMs?: number}} [opts]
   *   retries: عدد إعادة المحاولة عند 429/502/503 أو فشل الشبكة (افتراضي 2)
   *   timeoutMs: مهلة وصول الردّ (الهيدرات) — استخراج يوتيوب قد يأخذ وقتا (افتراضي 90 ثانية)
   */
  constructor(baseUrl, apiKey, { retries = 2, timeoutMs = 90_000 } = {}) {
    this.base = baseUrl.replace(/\/+$/, "");
    this.key = apiKey;
    this.retries = retries;
    this.timeoutMs = timeoutMs;
  }

  // ---- طلب عام مع مهلة وإعادة محاولة. يرجع Response سليم (2xx) أو يرمي YtdlpApiError ----
  async _request(pathname, params = {}, { headers = {}, signal } = {}) {
    const url = `${this.base}${pathname}?${new URLSearchParams(params)}`;
    let lastErr;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      if (attempt > 0) await sleep(2000 * attempt); // 2s ثم 4s ...
      if (signal?.aborted) throw signal.reason ?? new DOMException("Aborted", "AbortError");
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), this.timeoutMs);
      signal?.addEventListener("abort", () => ctl.abort(), { once: true });
      try {
        const res = await fetch(url, {
          headers: { "X-API-Key": this.key, ...headers },
          signal: ctl.signal,
        });
        clearTimeout(timer); // المهلة لوصول الهيدرات فقط؛ قراءة الجسم (التنزيل) بلا مهلة
        if (res.ok) return res;
        let msg = `HTTP ${res.status}`;
        try { msg = (await res.json()).error || msg; } catch {}
        lastErr = new YtdlpApiError(msg, res.status);
        if (!RETRY_STATUS.has(res.status)) throw lastErr; // 400/401/404/409/416: لا فائدة من الإعادة
      } catch (e) {
        clearTimeout(timer);
        if (e instanceof YtdlpApiError) {
          if (!RETRY_STATUS.has(e.status)) throw e;
          lastErr = e;
        } else if (signal?.aborted) {
          throw e; // أوقفه المستخدم
        } else {
          lastErr = new YtdlpApiError(e.name === "AbortError" ? "انتهت مهلة الطلب" : `تعذر الاتصال: ${e.message}`, 0);
        }
      }
    }
    throw lastErr;
  }

  async _json(pathname, params) {
    return (await this._request(pathname, params)).json();
  }

  /** فحص الخدمة (لا يحتاج مفتاحا). */
  health() {
    return this._json("/health", {});
  }

  /** معلومات الفيديو والصيغ: { ok, title, uploader, duration, thumbnail, video:[{fid,label,size,height}], audio:[...] } */
  info(url) {
    return this._json("/info", { url });
  }

  /** رابط مباشر من المصدر: { ok, title, ext, url }. تنبيه: الرابط مرتبط بـ IP السيرفر (انظر API.md). */
  link(url, { type = "video", q } = {}) {
    return this._json("/link", { url, type, ...(q ? { q } : {}) });
  }

  /** يرجع Response للتنزيل عبر السيرفر (جسمه Stream). range مثل "bytes=1000-" للاستئناف. */
  stream(url, { type = "video", q, range, signal } = {}) {
    return this._request("/stream", { url, type, ...(q ? { q } : {}) }, {
      headers: range ? { Range: range } : {},
      signal,
    });
  }

  /** يحمّل الملف كاملا في الذاكرة → Buffer (للملفات الصغيرة فقط). */
  async buffer(url, opts) {
    return Buffer.from(await (await this.stream(url, opts)).arrayBuffer());
  }

  /**
   * يحفظ الملف على القرص بدون تحميله كله في الذاكرة.
   * @returns {Promise<{path: string, bytes: number}>}
   * @param {{type?: "video"|"audio", q?: number, dir?: string, filename?: string,
   *          onProgress?: (received:number, total:number|null)=>void, signal?: AbortSignal}} [opts]
   */
  async download(url, { type = "video", q, dir = ".", filename, onProgress, signal } = {}) {
    const res = await this.stream(url, { type, q, signal });
    const total = Number(res.headers.get("content-length")) || null;
    const name = safeName(filename || filenameFrom(res.headers.get("content-disposition")) || "download.bin");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, name);
    let received = 0;
    async function* counted() {
      for await (const chunk of res.body) {
        received += chunk.length;
        onProgress?.(received, total);
        yield chunk;
      }
    }
    try {
      await pipeline(counted(), fs.createWriteStream(file));
    } catch (e) {
      fs.rmSync(file, { force: true }); // لا نترك ملفا ناقصا
      throw e;
    }
    return { path: file, bytes: received };
  }
}

/** اسم الملف من Content-Disposition (يدعم filename*=UTF-8''...). */
function filenameFrom(cd) {
  if (!cd) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) { try { return decodeURIComponent(star[1]); } catch {} }
  const plain = /filename="([^"]+)"/i.exec(cd);
  return plain ? plain[1] : null;
}

function safeName(n) {
  return n.replace(/[\\/:*?"<>|\r\n]+/g, "_").slice(0, 150);
}

module.exports = { YtdlpClient, YtdlpApiError, filenameFrom };
