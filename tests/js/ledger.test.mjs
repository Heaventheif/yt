// تشغيل:  cd tests/js && npm i fake-indexeddb && node ledger.test.mjs
// يتحقق من ثوابت سقف 500MB: المجموع ≤ CAP دائما، المجموع == مجموع المدخلات، المثبّت لا يُخلى، لا تجاوز مع الكتّاب المتزامنين.
import 'fake-indexeddb/auto';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// ---- بيئة وهمية: Cache API + Web Locks + storage.estimate ----
const stores = new Map();
globalThis.caches = {
  async open(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    const m = stores.get(name);
    return {
      async put(k, v) { m.set(typeof k === 'string' ? k : new URL(k.url).pathname, v); },
      async match(k) { return m.get(typeof k === 'string' ? k : new URL(k.url).pathname); },
      async delete(k) { return m.delete(k); },
      async keys() { return [...m.keys()].map(k => new Request('http://localhost' + k)); },
    };
  },
};
let chain = Promise.resolve();
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
  locks: { request: (_n, fn) => { const run = chain.then(fn); chain = run.catch(() => {}); return run; } },
  storage: { estimate: async () => ({ quota: 10e9, usage: 0 }) },
} });
const require = createRequire(import.meta.url);
require('../../static/ledger.js');
const L = globalThis.Ledger;

const rows = () => new Promise((ok, no) => {
  const r = indexedDB.open('ledger', 1);
  r.onsuccess = () => { const q = r.result.transaction('entries').objectStore('entries').getAll(); q.onsuccess = () => ok(q.result); q.onerror = no; };
});
const metaTotal = () => new Promise((ok) => {
  const r = indexedDB.open('ledger', 1);
  r.onsuccess = () => { const q = r.result.transaction('meta').objectStore('meta').get('total'); q.onsuccess = () => ok(q.result ? q.result.v : 0); };
});
async function invariants(label, pinned) {
  const all = await rows(), sum = all.reduce((a, r) => a + r.bytes, 0), tot = await metaTotal();
  assert.ok(tot <= L.CAP, `${label}: total ${tot} > CAP`);
  assert.equal(tot, sum, `${label}: meta total ${tot} != sum ${sum}`);
  const have = new Set(all.map(r => r.key));
  for (const k of pinned) assert.ok(have.has(k), `${label}: pinned ${k} was evicted`);
}
const put = async (key, bytes, o) => { await L.reserve(key, bytes, o); await (await caches.open(L.DYN)).put(key, new Response('x')); await L.commit(key); };

// mulberry32 حتمي
let seed = 42; const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };

// 1) تسلسل عشوائي: 1500 عملية
{
  const pinned = new Set(), live = [];
  for (let i = 0; i < 1500; i++) {
    const op = rnd();
    if (op < 0.7) {
      const key = `/k/${i}`, bytes = Math.floor(rnd() * 120e6) + 1, pin = rnd() < 0.08;
      try { await put(key, bytes, { kind: 'media', item: pin ? `item${i % 5}` : '', pinned: pin }); live.push(key); if (pin) pinned.add(key); }
      catch (e) { assert.ok(['quota', 'too-large'].includes(e.message), e.message); }
    } else if (op < 0.85 && live.length) {
      const k = live.splice(Math.floor(rnd() * live.length), 1)[0]; await L.release(k); pinned.delete(k);
    } else if (op < 0.9) {
      const id = `item${Math.floor(rnd() * 5)}`; await L.removeItem(id);
      for (const k of [...pinned]) if ([...(await rows())].every(r => r.key !== k)) pinned.delete(k);
    }
    if (i % 25 === 0) await invariants(`fuzz#${i}`, pinned);
  }
  await invariants('fuzz-end', pinned);
  console.log('ok  fuzz 1500 ops; total', (await metaTotal() / 1e6).toFixed(1), 'MB ≤', L.CAP / 1e6, 'MB');
}

// 2) كتّاب متزامنون: 60 حجزا × 90MB دفعة واحدة لا يتجاوزون السقف
{
  const res = await Promise.allSettled(Array.from({ length: 60 }, (_, i) => put(`/c/${i}`, 90e6, { kind: 'media', pinned: false })));
  assert.ok(res.some(r => r.status === 'fulfilled'));
  await invariants('concurrent', new Set());
  console.log('ok  60 concurrent reservations stayed ≤ CAP');
}

// 3) عنصر أكبر من 40% مرفوض، والمثبّت يملأ الحصة فيُرفض الجديد بـ quota
{
  await assert.rejects(L.reserve('/big', L.CAP * 0.41, {}), /too-large/);
  const pins = [];
  for (let i = 0; i < 6; i++) { try { await put(`/p/${i}`, 190e6, { pinned: true, item: 'fill' }); pins.push(`/p/${i}`); } catch (e) { assert.equal(e.message, 'quota'); } }
  await assert.rejects(L.reserve('/new', 100e6, {}), /quota/);
  await invariants('pinned-full', new Set(pins));
  console.log('ok  too-large and quota refusals; pinned items never evicted');
  await L.removeItem('fill');
}

// 4) مصالحة: يتيم الكاش + حجز عالق قديم + مدخل بلا كاش
{
  const c = await caches.open(L.DYN);
  await c.put('/orphan', new Response('x'));
  await L.reserve('/stale', 1000, {});                                  // pending ثم نجعله قديما
  await new Promise((ok) => { const r = indexedDB.open('ledger', 1); r.onsuccess = () => { const t = r.result.transaction('entries', 'readwrite'), s = t.objectStore('entries'); const g = s.get('/stale'); g.onsuccess = () => { g.result.created = Date.now() - 3600e3; s.put(g.result); }; t.oncomplete = ok; }; });
  await put('/ghost', 5000, {}); await c.delete('/ghost');              // مدخل جاهز بلا ملف
  const r = await L.reconcile();
  assert.ok(r.orphans >= 1 && r.dropped >= 2, JSON.stringify(r));
  await invariants('reconcile', new Set());
  assert.equal(await c.match('/orphan'), undefined);
  console.log('ok  reconcile:', JSON.stringify(r));
}
console.log('ALL LEDGER TESTS PASSED');
