/* app.js — الواجهة. ES2017 (بلا ?. أو ?? أو نشر الكائنات) لتعمل على متصفحات التلفاز القديمة. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var CHUNK = 4 * 1048576, PARALLEL = 2;           // PER_IP_STREAMS = 2 في الخادم
  var TYPES = { mp4: 'video/mp4', webm: 'video/webm', m4a: 'audio/mp4', mp3: 'audio/mpeg', opus: 'audio/ogg', ogg: 'audio/ogg' };
  var IS_TV = /Tizen|Web0S|WebOS|SMART-TV|SmartTV|HbbTV|Android TV|AFTM|BRAVIA/i.test(navigator.userAgent);
  var CAN_OFFLINE = !IS_TV && 'serviceWorker' in navigator && 'caches' in window && 'indexedDB' in window && window.Ledger;
  var state = { url: '', data: null, tab: 'video', advanced: false, abort: null };

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function sleep(ms, signal) {
    return new Promise(function (ok, no) {
      var t = setTimeout(ok, ms);
      if (signal) signal.addEventListener('abort', function () { clearTimeout(t); no(new DOMException('aborted', 'AbortError')); });
    });
  }
  function mb(n) { return n ? (n / 1048576).toFixed(n > 10485760 ? 0 : 1) + ' MB' : '—'; }
  function dur(s) {
    if (!s) return ''; s = Math.round(s);
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
  }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null'); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } }
  function beacon(e, v) {
    try { navigator.sendBeacon('/web/telemetry', JSON.stringify([{ e: e, v: v == null ? 1 : v }])); } catch (x) { /* اختياري */ }
  }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36); }

  /* ---------- الروابط ---------- */
  // الخادم يفك التحويلات (google/url, redirect, intent, vnd.youtube)؛ هنا نلتقط أول رابط من نص المشاركة فقط
  function extractUrl(text) {
    var m = /(?:https?|intent):\/\/[^\s<>"']+|vnd\.youtube:[^\s<>"']+/i.exec(text || '');
    return m ? m[0].replace(/[.,;)!?]+$/, '') : (text || '').trim();
  }

  /* ---------- الشبكة ---------- */
  async function fetchRetry(url, init, tries) {
    init = init || {}; tries = tries || 4;
    for (var a = 0; ; a++) {
      var wait = Math.random() * Math.min(8000, 500 * Math.pow(2, a));     // تأخير تصاعدي مع jitter كامل
      try {
        var r = await fetch(url, init);
        if (r.ok || (r.status < 500 && r.status !== 429) || a === tries - 1) return r;
        var ra = (+r.headers.get('Retry-After') || 0) * 1000;
        await sleep(Math.max(wait, Math.min(ra, 30000)), init.signal);
      } catch (e) {
        if ((init.signal && init.signal.aborted) || a === tries - 1) throw e;
        await sleep(wait, init.signal);
      }
    }
  }
  async function jget(u, init) {
    var r; try { r = await fetchRetry(u, init, 3); } catch (e) { if (e.name === 'AbortError') throw e; throw new Error('تعذر الاتصال بالخدمة. تحقق من الشبكة وأعد المحاولة.'); }
    var j = null; try { j = await r.json(); } catch (e) { /* لا JSON */ }
    if (!j) throw new Error(r.status >= 500 ? 'الخدمة غير متاحة الآن، انتظر دقيقة ثم أعد المحاولة.' : 'ردّ غير متوقع من الخدمة.');
    return j;
  }
  function status(text, cls) { var b = $('res'); b.textContent = ''; b.appendChild(el('p', 'status ' + (cls || ''), text)); }

  /* ---------- البحث والعرض ---------- */
  async function search(raw) {
    var url = extractUrl(raw);
    if (!/^(https?|intent|vnd\.youtube)/i.test(url)) { status('الصق رابطا صحيحا يبدأ بـ http.', 'err'); return; }
    status('جارٍ تحليل الرابط… قد يستغرق أول طلب نحو دقيقة إن كانت الخدمة نائمة.');
    $('go').disabled = true;
    var t0 = performance.now();
    try {
      var q = '/web/info?url=' + encodeURIComponent(url) + (state.advanced ? '&detail=all' : '');
      var d = await jget(q);
      if (!d.ok) throw new Error(d.error || 'فشل جلب المعلومات');
      state.url = url; state.data = d;
      beacon('info_miss', Math.round(performance.now() - t0));
      pushRecent(url, d.title);
      render();
    } catch (e) { status(e.message, 'err'); }
    $('go').disabled = false;
  }

  function parts(label) { var p = (label || '').split(' • '); return { q: p[0], rest: p.slice(1).join(' • ') }; }

  function render() {
    var d = state.data, box = $('res'); box.textContent = '';
    var media = el('div', 'media');
    if (d.thumbnail) { var im = el('img'); im.src = d.thumbnail; im.alt = ''; im.loading = 'lazy'; im.decoding = 'async'; media.appendChild(im); }
    var meta = el('div');
    meta.appendChild(el('h2', null, d.title || 'بدون عنوان'));
    meta.appendChild(el('p', null, [d.uploader, dur(d.duration)].filter(Boolean).join(' — ')));
    media.appendChild(meta); box.appendChild(media);

    var tools = el('div', 'tools'), tabs = el('div', 'tabs'); tabs.setAttribute('role', 'tablist');
    [['video', 'فيديو (' + d.video.length + ')'], ['audio', 'صوت (' + d.audio.length + ')']].forEach(function (t) {
      var b = el('button', null, t[1]); b.type = 'button'; b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(state.tab === t[0]));
      b.onclick = function () { state.tab = t[0]; render(); };
      tabs.appendChild(b);
    });
    var adv = el('label', 'adv'), cb = el('input'); cb.type = 'checkbox'; cb.checked = state.advanced;
    cb.onchange = function () { state.advanced = cb.checked; search(state.url); };
    adv.appendChild(cb); adv.appendChild(el('span', null, 'كل الصيغ والترميزات'));
    tools.appendChild(tabs); tools.appendChild(adv); box.appendChild(tools);

    var note = el('div', 'note'); note.setAttribute('role', 'status');
    var host = el('div');
    if (state.advanced && d.detail) host.appendChild(detailTable(d.detail, note));
    else if (state.tab === 'video') {
      var v = d.video;
      host.appendChild(section('جاهز بصوت وصورة', v.filter(function (o) { return o.sound && o.fid.indexOf('+') < 0; }), note));
      host.appendChild(section('دمج صوت وصورة (يستغرق أطول، بلا استئناف)', v.filter(function (o) { return o.sound && o.fid.indexOf('+') >= 0; }), note));
      host.appendChild(section('صورة فقط', v.filter(function (o) { return !o.sound; }), note));
    } else host.appendChild(section('صوت', d.audio, note));
    box.appendChild(host); box.appendChild(note);
  }

  function section(title, items, note) {
    var frag = document.createDocumentFragment();
    if (!items.length) return frag;
    var max = Math.max.apply(null, items.map(function (o) { return o.size || 0; }).concat([1]));
    var table = el('table', 'matrix'), cap = el('caption', null, title); table.appendChild(cap);
    var head = el('thead'), hr = el('tr');
    ['الجودة', 'التفاصيل', 'الحجم', ''].forEach(function (h) { var th = el('th', null, h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr); table.appendChild(head);
    var body = el('tbody');
    items.forEach(function (o) {
      var p = parts(o.label), tr = el('tr');
      tr.appendChild(el('td', 'q', p.q));
      tr.appendChild(el('td', 'fmt', p.rest));
      var sz = el('td', 'size'); if (o.size) { var bar = el('i'); bar.style.width = Math.max(6, Math.round(o.size / max * 100)) + '%'; sz.appendChild(bar); }
      sz.appendChild(el('span', null, mb(o.size))); tr.appendChild(sz);
      tr.appendChild(actions(o, note));
      body.appendChild(tr);
    });
    table.appendChild(body); frag.appendChild(table); return frag;
  }

  function detailTable(rows, note) {
    var items = rows.map(function (r) {
      var q = r.kind === 'audio' ? (r.codec || 'صوت') : (r.height ? r.height + 'p' + (r.fps > 30 ? r.fps : '') : '—');
      var rest = [r.container.toUpperCase(), r.kind === 'audio' ? '' : r.codec, r.tbr ? r.tbr + ' kbps' : '', r.kind === 'video' ? 'بلا صوت' : '']
        .filter(Boolean).join(' • ');
      return { fid: r.fid, label: q + ' • ' + rest, size: r.size, sound: r.kind !== 'video' };
    });
    return section('كل الصيغ المباشرة', items, note);
  }

  function actions(o, note) {
    var td = el('td', 'acts-cell'), box = el('div', 'acts');
    var dl = el('button', 'primary', 'تنزيل'); dl.type = 'button'; dl.onclick = function () { download(o, dl, note); };
    box.appendChild(dl);
    var seekable = o.size && o.fid.indexOf('+') < 0 && !o.convert;       // الدمج وMP3 بلا Range فلا يُحفظان أجزاء
    if (CAN_OFFLINE && seekable) {
      var off = el('button', null, 'حفظ دون اتصال'); off.type = 'button'; off.onclick = function () { saveOffline(o, off, note); };
      box.appendChild(off);
    }
    td.appendChild(box); return td;
  }

  /* ---------- التنزيل ---------- */
  async function download(o, btn, note) {
    var old = btn.textContent; btn.disabled = true; btn.textContent = 'جارٍ التحضير…'; note.className = 'note'; note.textContent = '';
    var q = 'url=' + encodeURIComponent(state.url) + '&fid=' + encodeURIComponent(o.fid);
    beacon('dl_start');
    try {
      var j = await jget('/web/dl?' + q + '&check=1');
      if (!j.ok) throw new Error(j.error || 'فشل التحضير');
      var a = document.createElement('a'); a.href = '/web/dl?' + q; document.body.appendChild(a); a.click(); a.remove();
      beacon('dl_ok');
      note.className = 'note ok'; note.textContent = 'بدأ التنزيل. إن لم يبدأ، جرّب صيغة أخرى.';
    } catch (e) {
      beacon('dl_fail');
      note.className = 'note bad'; note.textContent = e.message + (/تغيرت|غير موجودة/.test(e.message) ? ' سنعيد جلب الصيغ.' : '');
      if (/تغيرت|غير موجودة/.test(e.message)) setTimeout(function () { search(state.url); }, 800);
    }
    btn.textContent = old; btn.disabled = false;
  }

  /* ---------- الحفظ دون اتصال (سقف 500MB عبر Ledger) ---------- */
  async function sha256hex(buf) {
    if (IS_TV || !crypto.subtle) return '';
    var h = new Uint8Array(await crypto.subtle.digest('SHA-256', buf)), s = '';
    for (var i = 0; i < h.length; i++) s += h[i].toString(16).padStart(2, '0');
    return s;
  }
  function savedList() { return store('saved') || []; }

  async function saveOffline(o, btn, note) {
    var id = hash(state.url + '|' + o.fid), base = '/web/dl?url=' + encodeURIComponent(state.url) + '&fid=' + encodeURIComponent(o.fid);
    var ctl = new AbortController(); state.abort = ctl;
    var old = btn.textContent, bar = el('div', 'prog'), fill = el('i'); bar.appendChild(fill); note.className = 'note'; note.textContent = 'جارٍ الحفظ…'; note.appendChild(bar);
    btn.textContent = 'إلغاء'; btn.onclick = function () { ctl.abort(); };
    try {
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist();
      var head = await jget(base + '&check=1', { signal: ctl.signal });
      if (!head.ok || !head.size || head.merged) throw new Error('هذه الصيغة لا تدعم الحفظ دون اتصال. اختر صيغة جاهزة.');
      var n = Math.ceil(head.size / CHUNK), cache = await caches.open(Ledger.DYN), next = 0, done = 0;
      var ext = (o.label.match(/\b(MP4|WEBM|M4A|OPUS|OGG)\b/i) || [])[1];
      var man = { size: head.size, chunk: CHUNK, n: n, type: TYPES[(ext || 'mp4').toLowerCase()] || 'application/octet-stream',
        name: (state.data.title || 'file') + '.' + (ext || 'mp4').toLowerCase(), complete: false };
      await Ledger.reserve('/_m/' + id, 2048, { kind: 'manifest', item: id, pinned: true });
      await cache.put('/_m/' + id, new Response(JSON.stringify(man), { headers: { 'Content-Type': 'application/json' } }));
      await Ledger.commit('/_m/' + id);
      var worker = async function () {
        for (var i; (i = next++) < n;) {
          var s = i * CHUNK, e = Math.min(s + CHUNK, head.size) - 1, key = '/_c/' + id + '/' + i;
          await Ledger.reserve(key, e - s + 1, { kind: 'media', item: id, pinned: true });
          try {
            var r = await fetchRetry(base, { headers: { Range: 'bytes=' + s + '-' + e }, signal: ctl.signal });
            if (r.status !== 206) throw new Error('الخادم لم يدعم الاستئناف لهذه الصيغة.');
            var buf = await r.arrayBuffer();
            if (buf.byteLength !== e - s + 1) throw new Error('انقطع الاتصال قبل اكتمال الجزء.');
            await cache.put(key, new Response(buf));
            await Ledger.commit(key, await sha256hex(buf));
            fill.style.width = Math.round(++done / n * 100) + '%';
          } catch (err) { await Ledger.release(key); throw err; }
        }
      };
      var ws = []; for (var k = 0; k < Math.min(PARALLEL, n); k++) ws.push(worker());
      await Promise.all(ws);
      man.complete = true;
      await cache.put('/_m/' + id, new Response(JSON.stringify(man), { headers: { 'Content-Type': 'application/json' } }));
      var list = savedList().filter(function (x) { return x.id !== id; });
      list.unshift({ id: id, title: state.data.title, label: o.label, type: man.type, name: man.name, at: Date.now() });
      store('saved', list);
      beacon('offline_ok'); note.className = 'note ok'; note.textContent = 'تم الحفظ على هذا الجهاز.';
    } catch (e) {
      try { await Ledger.removeItem(id); } catch (x) { /* تنظيف قدر الإمكان */ }
      var msg = e.name === 'AbortError' ? 'أُلغي الحفظ.' : e.message === 'quota' ? 'لا توجد مساحة كافية. احذف عنصرا محفوظا ثم أعد المحاولة.'
        : e.message === 'too-large' ? 'الملف أكبر من الحد المسموح للحفظ دون اتصال (نحو 196 MB). نزّله مباشرة.' : e.message;
      beacon(e.message === 'quota' || e.message === 'too-large' ? 'quota_denied' : 'offline_fail');
      note.className = 'note bad'; note.textContent = msg;
    }
    btn.textContent = old; btn.onclick = function () { saveOffline(o, btn, note); };
    renderSaved();
  }

  async function renderSaved() {
    var list = savedList(), box = $('saved');
    if (!CAN_OFFLINE) { box.hidden = true; return; }
    var u; try { u = await Ledger.usage(); } catch (e) { return; }
    var live = {}; u.items.forEach(function (i) { live[i.id] = 1; });
    var shown = list.filter(function (x) { return live[x.id]; });                // عناصر السجل التي حُذفت (إخلاء/مصالحة) تختفي
    if (shown.length !== list.length) store('saved', shown);
    box.hidden = !shown.length && !u.total;
    var pct = Math.min(100, Math.round(u.total / u.cap * 100));
    $('meter').style.width = pct + '%'; box.querySelector('.meter').setAttribute('aria-valuenow', String(pct));
    $('meter-text').textContent = mb(u.total) + ' من ' + mb(u.cap);
    var ul = $('saved-list'); ul.textContent = '';
    shown.forEach(function (x) {
      var li = el('li', 'item'), t = el('div', 't'); t.appendChild(el('strong', null, x.title || x.name)); t.appendChild(el('div', 'muted', x.label));
      var acts = el('div', 'acts'), play = el('button', null, 'تشغيل'), del = el('button', null, 'حذف'), keep = el('a', 'link', 'حفظ كملف');
      play.type = del.type = 'button'; keep.href = '/offline/' + x.id; keep.setAttribute('download', x.name);
      play.onclick = function () {
        var old = li.querySelector('video,audio'); if (old) { old.remove(); return; }
        var m = el(/^audio/.test(x.type) ? 'audio' : 'video'); m.controls = true; m.preload = 'metadata'; m.src = '/offline/' + x.id; li.appendChild(m); m.play().catch(function () {});
      };
      del.onclick = async function () { await Ledger.removeItem(x.id); store('saved', savedList().filter(function (y) { return y.id !== x.id; })); renderSaved(); };
      acts.appendChild(play); acts.appendChild(keep); acts.appendChild(del); li.appendChild(t); li.appendChild(acts); ul.appendChild(li);
    });
  }

  /* ---------- آخر الروابط ---------- */
  function pushRecent(url, title) {
    var r = (store('recent') || []).filter(function (x) { return x.url !== url; });
    r.unshift({ url: url, title: title || url }); store('recent', r.slice(0, 6)); renderRecent();
  }
  function renderRecent() {
    var r = store('recent') || [], ul = $('recent-list'); $('recents').hidden = !r.length; ul.textContent = '';
    r.forEach(function (x) {
      var li = el('li', 'item'), b = el('button', 'link', x.title); b.type = 'button'; b.dir = 'auto';
      b.onclick = function () { $('url').value = x.url; search(x.url); };
      li.appendChild(b); ul.appendChild(li);
    });
  }

  /* ---------- التنقل بالأسهم على التلفاز ---------- */
  function spatialNav() {
    document.body.classList.add('tv');
    document.addEventListener('keydown', function (e) {
      var dir = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
      if (!dir || /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName) && dir[1] === 0) return;
      var cur = document.activeElement; if (!cur || cur === document.body) { var f = document.querySelector('input,button,a[href]'); if (f) f.focus(); e.preventDefault(); return; }
      var c = cur.getBoundingClientRect(), best = null, bestScore = 1e12;
      Array.prototype.forEach.call(document.querySelectorAll('button:not(:disabled),input,a[href],[tabindex="0"]'), function (n) {
        if (n === cur) return; var r = n.getBoundingClientRect(); if (!r.width) return;
        var dx = (r.left + r.width / 2) - (c.left + c.width / 2), dy = (r.top + r.height / 2) - (c.top + c.height / 2);
        var along = dx * dir[0] + dy * dir[1], across = Math.abs(dx * dir[1]) + Math.abs(dy * dir[0]);
        if (along <= 4) return;
        var score = along + across * 2.5; if (score < bestScore) { bestScore = score; best = n; }
      });
      if (best) { best.focus(); best.scrollIntoView({ block: 'nearest' }); e.preventDefault(); }
    });
  }

  /* ---------- الإقلاع ---------- */
  $('bar').addEventListener('submit', function (e) { e.preventDefault(); search($('url').value); });
  if (IS_TV) spatialNav();
  renderRecent();
  var u = new URLSearchParams(location.search).get('u');
  if (u) { $('url').value = extractUrl(u); search(u); history.replaceState(null, '', '/'); }
  if (CAN_OFFLINE) renderSaved();

  if ('serviceWorker' in navigator && /[?&]nosw=1/.test(location.search)) {     // مفتاح الإيقاف: يلغي SW ويمسح الكاش
    navigator.serviceWorker.getRegistrations().then(function (rs) { rs.forEach(function (r) { r.unregister(); }); });
    if (window.caches) caches.keys().then(function (ks) { ks.forEach(function (k) { caches.delete(k); }); });
  } else if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').then(function (reg) {
      if (reg.periodicSync && navigator.permissions) reg.periodicSync.register('ledger-clean', { minInterval: 24 * 3600e3 }).catch(function () {});
    }).catch(function () { /* الواجهة تعمل بلا SW */ });
  }
  window.addEventListener('pagehide', function () {                             // قياس LCP بسيط، مرة واحدة
    try {
      var e = performance.getEntriesByType('largest-contentful-paint'); if (e.length) beacon('lcp_ms', Math.round(e[e.length - 1].startTime));
    } catch (x) { /* غير مدعوم */ }
  }, { once: true });
})();
