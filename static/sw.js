/* sw.js — الواجهة تعمل دون اتصال، والبيانات المُدارة كلها تمر عبر Ledger (سقف 500MB).
 * ES2017. لا يعترض /web/dl أبدا: التنزيل الحي يذهب مباشرة إلى الشبكة. */
importScripts('/static/ledger.js');

var SHELL = 'shell-v1';
var SHELL_FILES = ['/', '/static/app.css', '/static/app.js', '/static/ledger.js', '/static/icon.svg', '/manifest.webmanifest'];
var INFO_TTL = 24 * 3600e3, THUMB_TTL = 7 * 24 * 3600e3, MANIFEST_TTL_TOUCH = 30e3;
var lastTouch = {};

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(SHELL).then(function (c) { return c.addAll(SHELL_FILES); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil((async function () {
    var names = await caches.keys();
    await Promise.all(names.filter(function (n) { return n !== SHELL && n !== Ledger.DYN; }).map(function (n) { return caches.delete(n); }));
    try { await Ledger.reconcile(); } catch (x) { /* لا نمنع التفعيل */ }
    await self.clients.claim();
  })());
});

self.addEventListener('periodicsync', function (e) {
  if (e.tag === 'ledger-clean') e.waitUntil(Ledger.reconcile());
});

self.addEventListener('message', function (e) {
  if (e.data === 'ledger-clean') e.waitUntil(Ledger.reconcile());
});

self.addEventListener('fetch', function (e) {
  var r = e.request;
  if (r.method !== 'GET') return;
  var u = new URL(r.url);
  if (u.origin !== location.origin) return;
  var p = u.pathname;
  if (p.indexOf('/offline/') === 0) return e.respondWith(serveOffline(r));
  if (r.mode === 'navigate' && p === '/') return e.respondWith(networkFirstShell(r));
  if (p.indexOf('/static/') === 0 || p === '/manifest.webmanifest') return e.respondWith(shellSWR(r));
  if (p === '/web/info') return e.respondWith(managedSWR(r, 'info', INFO_TTL));
  if (p === '/web/thumb') return e.respondWith(managedCacheFirst(r, 'thumb', THUMB_TTL));
  /* /web/dl و/web/playlist وغيرها: الشبكة فقط */
});

async function networkFirstShell(r) {
  try {
    var res = await fetch(r);
    if (res.ok && !new URL(r.url).search) (await caches.open(SHELL)).put('/', res.clone());
    return res;
  } catch (x) {
    return (await caches.match('/', { ignoreSearch: true })) || new Response('offline', { status: 503 });
  }
}

async function shellSWR(r) {
  var cache = await caches.open(SHELL), hit = await cache.match(r);
  var net = fetch(r).then(function (res) { if (res.ok) cache.put(r, res.clone()); return res; }).catch(function () { return null; });
  return hit || (await net) || new Response('', { status: 504 });
}

function fresh(res) {
  var d = res && res.headers.get('x-cached-at');
  return d;
}

async function stamp(res) {
  // نخزّن نسخة بوسم زمني كي لا نُقدّم معلومات قديمة جدا بعد الاتصال
  var h = new Headers(res.headers); h.set('x-cached-at', String(Date.now()));
  return new Response(await res.clone().arrayBuffer(), { status: res.status, statusText: res.statusText, headers: h });
}

async function managedSWR(r, kind, ttl) {
  var cache = await caches.open(Ledger.DYN), key = new URL(r.url).pathname + new URL(r.url).search;
  var hit = await cache.match(key);
  var net = fetch(r).then(async function (res) {
    if (res.status === 200) await Ledger.putManaged(key, await stamp(res), { kind: kind, ttl: ttl });
    return res;
  }).catch(function () { return null; });
  if (hit) {
    var at = +fresh(hit) || 0;
    if (Date.now() - at < ttl) { Ledger.touch(key).catch(function () {}); return hit; }
  }
  return (await net) || hit || new Response(JSON.stringify({ ok: false, error: 'لا يوجد اتصال' }), { status: 503, headers: { 'Content-Type': 'application/json' } });
}

async function managedCacheFirst(r, kind, ttl) {
  var cache = await caches.open(Ledger.DYN), key = new URL(r.url).pathname + new URL(r.url).search;
  var hit = await cache.match(key);
  if (hit) { Ledger.touch(key).catch(function () {}); return hit; }
  var res = await fetch(r);
  if (res.status === 200) Ledger.putManaged(key, res.clone(), { kind: kind, ttl: ttl }).catch(function () {});
  return res;
}

/* ---- ملفات «حفظ دون اتصال»: أجزاء 4MiB في Cache API. المتصفح يرسل Range دائما والـ Cache API لا يدعمه. ---- */
function expectedLen(man, i) { return i < man.n - 1 ? man.chunk : man.size - man.chunk * (man.n - 1); }

async function serveOffline(r) {
  var id = new URL(r.url).pathname.split('/')[2];
  var cache = await caches.open(Ledger.DYN);
  var mres = await cache.match('/_m/' + id);
  var man = mres && (await mres.json());
  if (!man || !man.complete) return new Response('', { status: 404 });
  var m = /bytes=(\d+)-(\d*)/.exec(r.headers.get('range') || '');
  if (!m) return streamAll(cache, id, man);                           // بلا Range (رابط حفظ الملف): بث كامل جزءا جزءا
  var start = m ? +m[1] : 0, end = Math.min(m && m[2] ? +m[2] : man.size - 1, man.size - 1);
  end = Math.min(end, start + 8 * man.chunk - 1);                      // سقف الرد: 8 أجزاء
  if (start > end || start >= man.size) {
    return new Response(null, { status: 416, headers: { 'Content-Range': 'bytes */' + man.size } });
  }
  var first = Math.floor(start / man.chunk), last = Math.floor(end / man.chunk), parts = [];
  for (var i = first; i <= last; i++) {
    var cr = await cache.match('/_c/' + id + '/' + i), b = cr && (await cr.blob());
    if (!b || b.size !== expectedLen(man, i)) {                        // علاج ذاتي: عنصر تالف => نحذفه كله
      Ledger.removeItem(id).catch(function () {});
      return new Response('', { status: 404 });
    }
    parts.push(b.slice(i === first ? start - i * man.chunk : 0, i === last ? end - i * man.chunk + 1 : b.size));
  }
  var now = Date.now();
  if (!lastTouch[id] || now - lastTouch[id] > MANIFEST_TTL_TOUCH) { lastTouch[id] = now; Ledger.touch('/_m/' + id).catch(function () {}); }
  return new Response(new Blob(parts), { status: 206, headers: {
    'Content-Type': man.type || 'application/octet-stream', 'Accept-Ranges': 'bytes',
    'Content-Length': String(end - start + 1), 'Content-Range': 'bytes ' + start + '-' + end + '/' + man.size } });
}

function streamAll(cache, id, man) {
  var i = 0;
  var body = new ReadableStream({
    pull: async function (ctrl) {
      if (i >= man.n) return ctrl.close();
      var cr = await cache.match('/_c/' + id + '/' + i), b = cr && (await cr.blob());
      if (!b || b.size !== expectedLen(man, i)) { Ledger.removeItem(id).catch(function () {}); return ctrl.error(new Error('corrupt')); }
      ctrl.enqueue(new Uint8Array(await b.arrayBuffer())); i++;
    }
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': man.type || 'application/octet-stream',
    'Content-Length': String(man.size), 'Accept-Ranges': 'bytes',
    'Content-Disposition': 'attachment; filename*=UTF-8\'\'' + encodeURIComponent(man.name || 'file') } });
}
