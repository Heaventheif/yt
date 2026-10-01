# صفحات الواجهة (HTML)

DOCS_HTML = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>yt-dlp API</title>
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;line-height:1.7;background:#111;color:#eee}
input,select,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #444;background:#1c1c1c;color:#eee;margin:4px 0}
input{width:100%;box-sizing:border-box}
button{cursor:pointer;background:#2b6cff;border:0;margin-inline-end:6px}
button.alt{background:#333}
pre{background:#1c1c1c;padding:12px;border-radius:8px;overflow:auto;direction:ltr;text-align:left;white-space:pre-wrap}
code{direction:ltr;unicode-bidi:embed}
h1,h2{margin-bottom:4px}
</style></head><body>
<h1>yt-dlp API</h1>
<p>الخدمة تعمل. جرّبها من هنا أو استخدمها كـ API من بوتك.</p>

<input id="key" placeholder="API Key (من Render ← Environment)" type="password">
<input id="url" placeholder="رابط الفيديو https://..." dir="ltr">
<select id="type"><option value="video">فيديو</option><option value="audio">صوت</option></select>
<select id="q"><option>360</option><option>480</option><option selected>720</option></select><br>
<button onclick="info()">معلومات</button>
<button onclick="dl()">تحميل</button>
<button class="alt" onclick="lnk()">رابط مباشر</button>
<pre id="out">النتيجة تظهر هنا…</pre>

<h2>التوثيق</h2>
<p>كل الطلبات (عدا <code>/health</code>) تحتاج المفتاح: هيدر <code>X-API-Key</code> أو <code>?key=</code>.</p>
<pre>GET /health
GET /info?url=URL
GET /link?url=URL&amp;type=video|audio&amp;q=720
GET /stream?url=URL&amp;type=video|audio&amp;q=720</pre>
<p>مثال curl:</p>
<pre id="ex"></pre>
<p>مثال Node.js (للبوت):</p>
<pre id="ex2"></pre>

<script>
const $=id=>document.getElementById(id), B=location.origin;
$('key').value=localStorage.k||''; $('url').value=localStorage.u||'';
function P(){localStorage.k=$('key').value;localStorage.u=$('url').value;
 return 'url='+encodeURIComponent($('url').value)+'&type='+$('type').value+'&q='+$('q').value}
async function call(path){ $('out').textContent='جارٍ التنفيذ…';
 try{const r=await fetch(B+path+'?'+P(),{headers:{'X-API-Key':$('key').value}});
 $('out').textContent=JSON.stringify(await r.json(),null,2)}catch(e){$('out').textContent=e}}
const info=()=>call('/info'), lnk=()=>call('/link');
async function dl(){$('out').textContent='جارٍ التنزيل…';try{const r=await fetch(B+'/stream?'+P(),{headers:{'X-API-Key':$('key').value}});
 if(!r.ok){$('out').textContent=JSON.stringify(await r.json(),null,2);return}
 const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download='download';a.click();$('out').textContent='تم'}catch(e){$('out').textContent=e}}
$('ex').textContent=`curl -H "X-API-Key: YOUR_KEY" "${B}/info?url=https://youtu.be/VIDEO_ID"\n\ncurl -H "X-API-Key: YOUR_KEY" -o video.mp4 "${B}/stream?url=https://youtu.be/VIDEO_ID&q=480"`;
$('ex2').textContent=`const res = await fetch("${B}/stream?url=" + encodeURIComponent(url) + "&type=video&q=480",\n  { headers: { "X-API-Key": process.env.YTDLP_KEY } });\nif (!res.ok) throw new Error((await res.json()).error);\nconst buf = Buffer.from(await res.arrayBuffer());`;
</script></body></html>"""


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
