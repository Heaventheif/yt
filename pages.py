DOCS_HTML = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>توثيق yt-dlp API</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131b2f;--line:#263453;--text:#edf3ff;--muted:#91a0bd;--brand:#6c8cff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#17264a,var(--bg) 48%);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Tahoma,sans-serif;line-height:1.65}.wrap{max-width:1020px;margin:auto;padding:28px 18px}.hero{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:24px}.eyebrow{color:#91aaff;font-weight:700}.hero h1{font-size:clamp(1.7rem,4vw,2.8rem);margin:4px 0}.hero p{color:var(--muted);margin:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card,pre{background:rgba(19,27,47,.86);border:1px solid var(--line);border-radius:16px;padding:16px}.card strong{display:block;font-size:1.25rem}.muted{color:var(--muted);font-size:.9rem}h2{margin:30px 0 10px}.endpoint{margin:10px 0;padding:12px 14px;border-inline-start:3px solid var(--brand);background:#111a2e;border-radius:8px}.method{color:#8fd5ff;font-weight:800;direction:ltr;display:inline-block}code,pre{direction:ltr;text-align:left;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}pre{overflow:auto;white-space:pre-wrap}a{color:#9db2ff}</style></head><body><main class="wrap"><header class="hero"><div><div class="eyebrow">yt-dlp API</div><h1>توثيق سريع وواضح</h1><p>جلب كل الصيغ المباشرة والجودات المتاحة مع قياس الأداء.</p></div><a href="/">العودة للتحميل</a></header><section class="grid" id="overview"><div class="card"><strong id="latency">—</strong><span class="muted">زمن ping المحلي</span></div><div class="card"><strong id="requests">—</strong><span class="muted">إجمالي الطلبات</span></div><div class="card"><strong id="commit">—</strong><span class="muted">آخر commit</span></div></section><h2>النقاط المتاحة</h2><div class="endpoint"><span class="method">GET /health</span> فحص الخدمة وإصدار yt-dlp — عام.</div><div class="endpoint"><span class="method">GET /ping</span> قياس استجابة التطبيق دون الاتصال بمصدر خارجي — عام.</div><div class="endpoint"><span class="method">GET /stats</span> المتوسط وP95 وعدد الأخطاء والمسارات — عام.</div><div class="endpoint"><span class="method">GET /repo</span> فرع المستودع وcommit ورابط GitHub — عام.</div><div class="endpoint"><span class="method">GET /info?url=URL</span> كل صيغ الفيديو والصوت المباشرة، مع <code>fid</code> والامتداد والكودك والحجم — يحتاج <code>X-API-Key</code>.</div><div class="endpoint"><span class="method">GET /link?url=&amp;type=&amp;q=</span> رابط المصدر لصيغة تلقائية — يحتاج المفتاح.</div><div class="endpoint"><span class="method">GET /stream?url=&amp;type=&amp;q=</span> تمرير التنزيل مع Range واستئناف — يحتاج المفتاح.</div><h2>أمثلة</h2><pre>curl -H "X-API-Key: YOUR_KEY" "https://your-host/info?url=https%3A%2F%2Fyoutu.be%2FVIDEO_ID"
curl -H "X-API-Key: YOUR_KEY" -o video.mp4 "https://your-host/stream?url=URL&amp;type=video&amp;q=720"</pre><p class="muted">ملاحظة: صيغ الفيديو المنفصلة عن الصوت تُعرض كما هي. دمجها يحتاج ffmpeg أو عميل تنزيل يدعم الدمج.</p></main><script>Promise.all([fetch('/ping'),fetch('/stats'),fetch('/repo')]).then(async([a,b,c])=>{const[p,s,r]=await Promise.all([a.json(),b.json(),c.json()]);document.querySelector('#latency').textContent=p.latency_ms+' ms';document.querySelector('#requests').textContent=s.requests;document.querySelector('#commit').textContent=r.commit||'—'}).catch(()=>{});</script></body></html>"""

ENCODE_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>تشفير الكوكيز base64</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0f1115;color:#eee;margin:0;padding:20px 14px;line-height:1.7}
.w{max-width:680px;margin:0 auto}
h1{font-size:1.35rem;text-align:center;margin:0 0 4px}
.s{text-align:center;color:#9aa;font-size:.85rem;margin:0 0 14px}
textarea{width:100%;height:150px;background:#1a1d24;color:#eee;border:1px solid #333;border-radius:10px;padding:10px;direction:ltr;font-family:monospace;font-size:.8rem}
button,label.b{display:inline-block;cursor:pointer;border:0;border-radius:10px;background:#2b6cff;color:#fff;padding:11px 16px;font:inherit;margin:6px 4px 6px 0}
button.g,label.g{background:#333}
input[type=file]{display:none}
#info{color:#9aa;font-size:.9rem;margin:6px 0}
.ok{color:#6fdc8c}.bad{color:#ff7b7b}
</style></head><body><div class="w">
<h1>تشفير الكوكيز إلى base64</h1>
<p class="s">التشفير يتم داخل متصفحك فقط، ولا يُرسل شيء لأي سيرفر.</p>
<label class="b">اختر ملف cookies.txt<input type="file" id="f" accept=".txt,.json,text/plain,application/json"></label>
<span style="color:#9aa">أو الصق محتواه:</span>
<textarea id="src" placeholder="# Netscape HTTP Cookie File ..."></textarea>
<label style="display:block;margin:8px 0"><input type="checkbox" id="only" checked> إبقاء كوكيز youtube.com و google.com فقط (موصى به)</label>
<button onclick="run()">تشفير</button>
<div id="info"></div>
<textarea id="out" readonly placeholder="الناتج يظهر هنا — انسخه إلى COOKIES_B64 في Render"></textarea>
<button onclick="cp()">نسخ الناتج</button>
<button class="g" onclick="dec()">فحص: فك الترميز</button>
<pre id="chk" style="direction:ltr;background:#1a1d24;padding:10px;border-radius:10px;white-space:pre-wrap;display:none"></pre>
</div>
<script>
const $=id=>document.getElementById(id);
function b64(str){const b=new TextEncoder().encode(str);let s='';for(let i=0;i<b.length;i+=8192)s+=String.fromCharCode.apply(null,b.subarray(i,i+8192));return btoa(s)}
$('f').onchange=async e=>{const f=e.target.files[0];if(f){$('src').value=await f.text();run()}};
function run(){
  let t=$('src').value.replace(/\r\n?/g,'\n').trim();
  if(!t){$('info').innerHTML='<span class="bad">لا يوجد محتوى</span>';return}
  let out,n=0,yt=false,tabs=true;
  if(t[0]==='['||t[0]==='{'){out=t;n='JSON';yt=/youtube|google/.test(t)}
  else{
    let ls=t.split('\n').filter(l=>l.trim()&&(!l.startsWith('#')||l.startsWith('#HttpOnly_')));
    if($('only').checked)ls=ls.filter(l=>/(youtube|google)\.com/.test(l));
    n=ls.length;yt=ls.some(l=>/youtube\.com/.test(l));tabs=ls.every(l=>l.split('\t').length===7);
    out='# Netscape HTTP Cookie File\n'+ls.join('\n')+'\n';
  }
  if(!n){$('info').innerHTML='<span class="bad">لم أجد كوكيز مطابقة. جرّب إلغاء خيار التصفية.</span>';$('out').value='';return}
  $('out').value=b64(out);
  $('info').innerHTML='عدد الكوكيز: '+n+' — '+(yt?'<span class="ok">يوتيوب موجود</span>':'<span class="bad">لا توجد كوكيز يوتيوب (سجّل الدخول ثم صدّر من صفحة youtube.com)</span>')
    +(tabs?'':' — <span class="bad">التابات مفقودة، لكن السيرفر يصلحها تلقائياً</span>')+' — الحجم: '+$('out').value.length+' حرف';
}
async function cp(){const v=$('out').value;if(!v)return;try{await navigator.clipboard.writeText(v)}catch(e){$('out').select();document.execCommand('copy')}$('info').innerHTML+=' — <span class="ok">تم النسخ</span>'}
function dec(){const v=$('out').value;if(!v)return;const c=$('chk');c.style.display='block';
  try{c.textContent=new TextDecoder().decode(Uint8Array.from(atob(v),x=>x.charCodeAt(0))).split('\n').slice(0,3).map(l=>l.replace(/\t.*\t/,'\t…\t')).join('\n')}catch(e){c.textContent='فشل الفك'}}
</script></body></html>"""


WEB_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="جلب وتنزيل صيغ الفيديو والصوت"><title>yt fetch — تنزيل الفيديو والصوت</title>
<style>
:root{--bg:#07101f;--panel:#101c31;--panel2:#14243d;--line:#294263;--text:#f4f7ff;--muted:#9cafca;--brand:#6d8cff;--good:#79e3a0;--danger:#ff9b9b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#203d70,var(--bg) 48%);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Tahoma,sans-serif;line-height:1.55}.wrap{max-width:1040px;margin:auto;padding:22px 16px 36px}.top{display:flex;justify-content:space-between;align-items:center}.brand{font-weight:900;font-size:1.2rem}.nav a{color:#b7c6ff;text-decoration:none;margin-inline-start:16px;font-size:.9rem}.hero{text-align:center;padding:42px 0 24px}.eyebrow{color:#a9b9ff;font-weight:700}.hero h1{font-size:clamp(2rem,6vw,4rem);line-height:1.05;margin:10px 0}.hero p{color:var(--muted);max-width:640px;margin:0 auto 22px}.search{display:flex;gap:9px;max-width:780px;margin:auto}.search input{flex:1;min-width:0;padding:15px 16px;border-radius:14px;border:1px solid var(--line);background:#0b172a;color:var(--text);font-size:1rem;direction:ltr;outline:none}.search input:focus{border-color:var(--brand);box-shadow:0 0 0 3px #6d8cff25}.btn{border:0;border-radius:11px;background:var(--brand);color:#fff;padding:11px 17px;cursor:pointer;font:inherit;font-weight:800}.btn:disabled{opacity:.55;cursor:wait}.btn.alt{background:#233858}.panel{background:rgba(16,28,49,.94);border:1px solid var(--line);border-radius:20px;padding:18px;margin-top:18px;box-shadow:0 12px 36px #0002}.meta{display:flex;gap:15px;align-items:center}.meta img{width:132px;height:82px;object-fit:cover;border-radius:12px}.meta h2{margin:0;font-size:1.15rem}.muted{color:var(--muted);font-size:.9rem}.stats{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.pill{background:#1a2c49;border:1px solid var(--line);border-radius:999px;padding:3px 9px;color:#cbd8f2;font-size:.78rem}.tabs{display:flex;gap:8px;margin:20px 0 12px;border-bottom:1px solid var(--line);padding-bottom:10px}.tab{background:transparent;color:var(--muted);border:1px solid transparent;border-radius:10px;padding:9px 14px;cursor:pointer;font:inherit}.tab.active{background:#243c65;color:#fff;border-color:#5578bd}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}.toolbar input,.toolbar select{background:#0b172a;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px}.count{margin-inline-start:auto;color:var(--muted);font-size:.85rem}.format{display:flex;justify-content:space-between;align-items:center;gap:14px;border-top:1px solid #243957;padding:13px 3px}.format-main{min-width:0}.format-title{font-weight:750}.format-meta{display:flex;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:.78rem;margin-top:3px}.format-meta span{background:#0c182b;border-radius:6px;padding:2px 6px}.msg{text-align:center;color:var(--muted);padding:22px}.err{color:var(--danger)}.diagnostics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:18px}.metric{padding:12px;background:#0d192d;border:1px solid var(--line);border-radius:12px}.metric strong{display:block}.foot{text-align:center;color:#7183a4;font-size:.82rem;margin-top:26px}@media(max-width:600px){.search{flex-direction:column}.search .btn{width:100%}.meta img{width:92px;height:64px}.format{align-items:flex-start;flex-direction:column}.format .btn{width:100%}.count{width:100%;margin:0}.nav a{margin-inline-start:8px}}
</style></head><body><main class="wrap"><nav class="top"><span class="brand">yt fetch</span><span class="nav"><a href="/docs">التوثيق</a><a href="/repo" target="_blank">المستودع</a></span></nav>
<section class="hero"><div class="eyebrow">فيديو وصوت — كل الصيغ المتاحة</div><h1>نزّل بالطريقة التي تريدها</h1><p>ألصق رابط يوتيوب أو أي مصدر مدعوم. ستظهر صيغ الفيديو والصوت منفصلة مع الجودة والكودك والحجم.</p><div class="search"><input id="url" placeholder="https://www.youtube.com/watch?v=..." autocomplete="off" inputmode="url"><button class="btn" id="go">جلب الصيغ</button></div></section>
<div id="res"></div><section class="diagnostics"><div class="metric"><strong id="ping">—</strong><span class="muted">زمن ping</span></div><div class="metric"><strong id="repo">—</strong><span class="muted">نسخة المستودع</span></div><div class="metric"><strong id="stat">—</strong><span class="muted">زمن الجلب</span></div></section><p class="foot">استخدم المحتوى الذي تملك حق تنزيله فقط. <a href="/encode">أداة كوكيز</a></p></main>
<script>
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),mb=n=>n?(n/1048576).toFixed(n>10485760?0:1)+' MB':'غير معروف';
const msg=(t,c='')=>{$('res').innerHTML='<div class="panel msg '+c+'">'+esc(t)+'</div>'};
async function json(url){const r=await fetch(url,{cache:'no-store'}),j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||'تعذر إكمال الطلب');return j}
function formatMeta(o){return [o.ext&&o.ext.toUpperCase(),o.resolution||(o.height?o.height+'p':null),o.fps?o.fps+' fps':null,o.abr?o.abr+' kbps':null,o.vcodec||o.acodec,o.format_note,o.size?mb(o.size):null].filter(Boolean).map(x=>'<span>'+esc(x)+'</span>').join('')}
function show(d,url){
 const box=document.createElement('section');box.className='panel';
 box.innerHTML='<div class="meta">'+(d.thumbnail?'<img src="'+esc(d.thumbnail)+'" loading="lazy" referrerpolicy="no-referrer">':'')+'<div><h2>'+esc(d.title||'بدون عنوان')+'</h2><div class="muted">'+esc([d.uploader,d.extractor].filter(Boolean).join(' • '))+'</div><div class="stats"><span class="pill">فيديو: '+d.video.length+'</span><span class="pill">صوت: '+d.audio.length+'</span><span class="pill">الإجمالي: '+d.format_count+'</span></div></div></div><div class="tabs"><button class="tab active" data-kind="video">فيديو ('+d.video.length+')</button><button class="tab" data-kind="audio">صوت ('+d.audio.length+')</button></div><div class="toolbar"><input id="filter" placeholder="بحث: mp4، 720p، m4a"><span class="count" id="count"></span></div><div id="list"></div>';
 $('res').replaceChildren(box);const list=box.querySelector('#list'),filter=box.querySelector('#filter'),count=box.querySelector('#count');let kind='video';
 const render=()=>{const source=kind==='audio'?d.audio:d.video,q=filter.value.toLowerCase().trim(),items=source.filter(o=>!q||JSON.stringify(o).toLowerCase().includes(q));count.textContent=items.length+' من '+source.length;list.innerHTML=items.length?'':'<div class="msg">لا توجد صيغ مطابقة</div>';items.forEach(o=>{const row=document.createElement('div');row.className='format';row.innerHTML='<div class="format-main"><div class="format-title">'+esc(o.label)+'</div><div class="format-meta">'+formatMeta(o)+'</div></div>';const b=document.createElement('button');b.className='btn alt';b.textContent='تنزيل';b.onclick=()=>{b.disabled=true;b.textContent='جاري…';const a=document.createElement('a');a.href='/web/dl?url='+encodeURIComponent(url)+'&fid='+encodeURIComponent(o.fid);a.click();setTimeout(()=>{b.disabled=false;b.textContent='تنزيل'},1800)};row.append(b);list.append(row)})};
 box.querySelectorAll('.tab').forEach(tab=>tab.onclick=()=>{kind=tab.dataset.kind;box.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===tab));render()});filter.oninput=render;render();
}
async function search(){const u=$('url').value.trim();if(!/^https?:\/\//i.test(u))return msg('أدخل رابطاً يبدأ بـ http أو https','err');$('go').disabled=true;msg('جاري جلب صيغ الفيديو والصوت…');const t=performance.now();try{const d=await json('/web/info?url='+encodeURIComponent(u));show(d,u);$('stat').textContent=Math.round(performance.now()-t)+' ms'}catch(e){msg(e.message,'err')}finally{$('go').disabled=false}}
$('go').onclick=search;$('url').onkeydown=e=>e.key==='Enter'&&search();Promise.all([json('/ping'),json('/stats'),json('/repo')]).then(([p,s,r])=>{$('ping').textContent=p.latency_ms+' ms';$('stat').textContent=s.avg_ms+' ms';$('repo').textContent=r.commit||'—'}).catch(()=>{});
</script></body></html>"""
