/* ledger.js — سجلّ الكاش: سقف صارم 500MB (عشرية) بإخلاء LRU حتمي.
 * يعمل في الصفحة وفي الـ Service Worker (importScripts). ES2017 بلا سلسلة بناء.
 *
 * الثوابت:
 *   TOTAL 500e6 = SHELL 8e6 (كاش الواجهة الثابت، خارج السجل) + CAP 492e6 (كل ما يديره السجل)
 *   الإخلاء يبدأ عند 90% من CAP وينزل إلى 80%. الحجز يسبق الكتابة، فلا يتجاوز الكتّاب المتزامنون السقف.
 * ترتيب الإخلاء: (pinned, last, created, key). المثبّت (حفظ دون اتصال) لا يُخلى تلقائيا أبدا.
 * قفل Web Locks واحد 'ledger' يسلسل الكتابة بين التبويبات والـ SW.
 */
(function (root) {
  'use strict';
  var TOTAL = 500e6, SHELL = 8e6, CAP = TOTAL - SHELL;
  var HIGH = CAP * 0.9, LOW = CAP * 0.8, MAX_ITEM = CAP * 0.4, OVERHEAD = 1024;
  var DYN = 'dyn-v1', PENDING_TTL = 600e3, DB_NAME = 'ledger';

  function req(r) { return new Promise(function (ok, no) { r.onsuccess = function () { ok(r.result); }; r.onerror = function () { no(r.error); }; }); }
  function txDone(t) { return new Promise(function (ok, no) { t.oncomplete = ok; t.onerror = t.onabort = function () { no(t.error); }; }); }
  function locked(fn) {
    if (root.navigator && root.navigator.locks) return root.navigator.locks.request('ledger', fn);
    return fn();   // متصفحات بلا Web Locks: تسلسل داخل السياق الواحد فقط
  }

  var dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise(function (ok, no) {
      var r = root.indexedDB.open(DB_NAME, 1);
      r.onupgradeneeded = function () {
        var s = r.result.createObjectStore('entries', { keyPath: 'key' });
        s.createIndex('lru', ['pinned', 'last', 'created', 'key']);   // pinned = 0/1 (المنطقي ليس مفتاح IDB صالحا)
        s.createIndex('item', 'item');
        r.result.createObjectStore('meta', { keyPath: 'k' });
      };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { no(r.error); };
    });
    return dbp;
  }

  async function getTotal(d) {
    var row = await req(d.transaction('meta').objectStore('meta').get('total'));
    return row ? row.v : 0;
  }

  async function platformCap() {
    // سقف المنصة: لا نعتمد أكثر من 80% من الحصة المتاحة للأصل (Safari/TV أصغر بكثير)
    try {
      if (root.navigator && root.navigator.storage && root.navigator.storage.estimate) {
        var e = await root.navigator.storage.estimate();
        if (e && e.quota) return Math.min(CAP, Math.floor(0.8 * e.quota));
      }
    } catch (x) { /* تجاهل */ }
    return CAP;
  }

  async function evict(d, tot, mustFree) {
    var rows = await req(d.transaction('entries').objectStore('entries').index('lru').getAll());
    var victims = [], freed = 0, now = Date.now();
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (freed >= mustFree || r.pinned) break;                         // المثبّتة تأتي أخيرا: لا إخلاء لها
      if (r.state === 'pending' && now - r.created < PENDING_TTL) continue;   // قيد الكتابة
      victims.push(r); freed += r.bytes;
    }
    if (victims.length) {
      var cache = await root.caches.open(DYN);
      await Promise.all(victims.map(function (v) { return cache.delete(v.key); }));
      var t = d.transaction(['entries', 'meta'], 'readwrite');
      victims.forEach(function (v) { t.objectStore('entries').delete(v.key); });
      t.objectStore('meta').put({ k: 'total', v: tot - freed });
      await txDone(t);
    }
    return { total: tot - freed, evicted: victims.length };
  }

  /** يحجز bytes قبل الكتابة؛ يرمي 'too-large' أو 'quota' إن تعذر. */
  function reserve(key, bytes, o) {
    o = o || {};
    return locked(async function () {
      var d = await db(), need = bytes + OVERHEAD, cap = await platformCap();
      if (need > Math.min(MAX_ITEM, cap)) throw new Error('too-large');
      var tot = await getTotal(d), evicted = 0;
      if (tot + need > Math.min(HIGH, cap)) {
        var r = await evict(d, tot, tot + need - Math.min(LOW, cap)); tot = r.total; evicted = r.evicted;
      }
      if (tot + need > cap) throw new Error('quota');                   // لم يبقَ إلا المثبّت/قيد الكتابة
      var t = d.transaction(['entries', 'meta'], 'readwrite'), now = Date.now();
      t.objectStore('entries').put({ key: key, kind: o.kind || 'misc', item: o.item || '', pinned: o.pinned ? 1 : 0,
        bytes: need, state: 'pending', created: now, last: now, exp: o.ttl ? now + o.ttl : 0 });
      t.objectStore('meta').put({ k: 'total', v: tot + need });
      await txDone(t);
      return { evicted: evicted };
    });
  }

  function commit(key, sha256) {
    return locked(async function () {
      var d = await db(), t = d.transaction('entries', 'readwrite'), s = t.objectStore('entries');
      var row = await req(s.get(key));
      if (row) { row.state = 'ready'; if (sha256) row.sha256 = sha256; s.put(row); }
      await txDone(t);
    });
  }

  function release(key) {
    return locked(async function () {
      var d = await db(), row = await req(d.transaction('entries').objectStore('entries').get(key));
      if (!row) return;
      var tot = await getTotal(d);
      await (await root.caches.open(DYN)).delete(key);
      var t = d.transaction(['entries', 'meta'], 'readwrite');
      t.objectStore('entries').delete(key);
      t.objectStore('meta').put({ k: 'total', v: Math.max(0, tot - row.bytes) });
      await txDone(t);
    });
  }

  /** يحذف كل مدخلات عنصر (حفظ دون اتصال) من الكاش والسجل. */
  function removeItem(item) {
    return locked(async function () {
      var d = await db(), rows = await req(d.transaction('entries').objectStore('entries').index('item').getAll(item));
      if (!rows.length) return 0;
      var tot = await getTotal(d), freed = 0, cache = await root.caches.open(DYN);
      await Promise.all(rows.map(function (r) { freed += r.bytes; return cache.delete(r.key); }));
      var t = d.transaction(['entries', 'meta'], 'readwrite');
      rows.forEach(function (r) { t.objectStore('entries').delete(r.key); });
      t.objectStore('meta').put({ k: 'total', v: Math.max(0, tot - freed) });
      await txDone(t);
      return rows.length;
    });
  }

  function touch(key) {
    return locked(async function () {
      var d = await db(), t = d.transaction('entries', 'readwrite'), s = t.objectStore('entries');
      var row = await req(s.get(key)); if (row) { row.last = Date.now(); s.put(row); }
      await txDone(t);
    });
  }

  /** كتابة مُدارة لاستجابة صغيرة (معلومات/صور مصغرة): حجز ثم تخزين ثم تثبيت. */
  async function putManaged(key, response, o) {
    var buf = await response.clone().arrayBuffer();
    try { await reserve(key, buf.byteLength, o); } catch (e) { return false; }   // لا مكان: نتخطى الكاش بصمت
    try {
      await (await root.caches.open(DYN)).put(key, response);
      await commit(key);
      return true;
    } catch (e) { await release(key); return false; }
  }

  /** مصالحة بعد انهيار/إغلاق مفاجئ: يتيم الكاش، يتيم السجل، الحجوزات العالقة، ثم إعادة حساب المجموع. */
  function reconcile() {
    return locked(async function () {
      var d = await db(), cache = await root.caches.open(DYN), now = Date.now();
      var rows = await req(d.transaction('entries').objectStore('entries').getAll());
      var keys = (await cache.keys()).map(function (r) { return new URL(r.url).pathname + new URL(r.url).search; });
      var have = {}; keys.forEach(function (k) { have[k] = 1; });
      var known = {}, drop = [], sum = 0;
      rows.forEach(function (r) {
        var stale = r.state === 'pending' && now - r.created > PENDING_TTL;
        var expired = r.exp && r.exp < now && !r.pinned;
        if (stale || expired || (r.state === 'ready' && !have[r.key])) drop.push(r); else { known[r.key] = 1; sum += r.bytes; }
      });
      var orphans = keys.filter(function (k) { return !known[k]; });
      await Promise.all(drop.map(function (r) { return cache.delete(r.key); }).concat(orphans.map(function (k) { return cache.delete(k); })));
      var t = d.transaction(['entries', 'meta'], 'readwrite');
      drop.forEach(function (r) { t.objectStore('entries').delete(r.key); });
      t.objectStore('meta').put({ k: 'total', v: sum });
      await txDone(t);
      return { total: sum, dropped: drop.length, orphans: orphans.length };
    });
  }

  async function usage() {
    var d = await db(), rows = await req(d.transaction('entries').objectStore('entries').getAll());
    var items = {};
    rows.forEach(function (r) { if (r.item) { var i = items[r.item] || (items[r.item] = { id: r.item, bytes: 0, parts: 0 }); i.bytes += r.bytes; i.parts++; } });
    return { total: await getTotal(d), cap: CAP, shell: SHELL, items: Object.keys(items).map(function (k) { return items[k]; }) };
  }

  root.Ledger = { TOTAL: TOTAL, SHELL: SHELL, CAP: CAP, DYN: DYN, OVERHEAD: OVERHEAD, reserve: reserve, commit: commit,
    release: release, removeItem: removeItem, touch: touch, putManaged: putManaged, reconcile: reconcile, usage: usage };
})(typeof self !== 'undefined' ? self : globalThis);
