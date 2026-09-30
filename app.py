import base64
import os
import re
import threading
import time

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "")
PROXY = os.getenv("PROXY", "")  # اختياري
YT_CLIENTS = [c.strip() for c in os.getenv("YT_CLIENTS", "").split(",") if c.strip()]
COOKIES_PATH = "/tmp/cookies.txt"
WEB_PUBLIC = os.getenv("WEB_PUBLIC", "1") == "1"  # واجهة عامة بدون مفتاح
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))  # طلبات/دقيقة لكل IP للواجهة العامة
DL_SLOTS = threading.Semaphore(int(os.getenv("MAX_DOWNLOADS", "3")))  # تنزيلات متزامنة
HITS = {}
SLOTS = threading.Semaphore(int(os.getenv("MAX_CONCURRENT", "2")))  # حماية الذاكرة 512MB

# ---- cookies من متغير بيئة (base64 لملف cookies.txt بصيغة Netscape) ----
if os.getenv("COOKIES_B64"):
    with open(COOKIES_PATH, "wb") as f:
        f.write(base64.b64decode(os.environ["COOKIES_B64"]))


# ---- Keep-alive: يزور السيرفر نفسه كل 14 دقيقة لمنع النوم ----
KEEP_ALIVE_MIN = int(os.getenv("KEEP_ALIVE_MINUTES", "14"))
SELF_URL = os.getenv("SELF_URL") or os.getenv("RENDER_EXTERNAL_URL", "")


def keep_alive():
    import time
    while True:
        time.sleep(KEEP_ALIVE_MIN * 60)
        try:
            requests.get(SELF_URL.rstrip("/") + "/health", timeout=20)
        except Exception:
            pass


if SELF_URL and KEEP_ALIVE_MIN > 0:
    threading.Thread(target=keep_alive, daemon=True).start()


def auth_ok():
    if not API_KEY:
        return True
    key = request.headers.get("X-API-Key") or request.args.get("key")
    return key == API_KEY


def base_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 2,
        "js_runtimes": {"node": {}},  # yt-dlp يحتاج JS runtime ليفك تشفير يوتيوب
    }
    if YT_CLIENTS:
        opts["extractor_args"] = {"youtube": {"player_client": YT_CLIENTS}}
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    if PROXY:
        opts["proxy"] = PROXY
    return opts


def selector(kind, quality):
    if kind == "audio":
        return "bestaudio[ext=m4a]/bestaudio/best"
    q = int(quality) if str(quality).isdigit() else 720
    return f"best[ext=mp4][height<=?{q}]/best[height<=?{q}]/best"


def extract(url, fmt=None):
    opts = base_opts()
    if fmt:
        opts["format"] = fmt
    with SLOTS:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)


def valid_url():
    url = request.args.get("url", "").strip()
    if not re.match(r"^https?://", url):
        return None
    return url


def err(e, code=502):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return jsonify(ok=False, error=msg[:500]), code


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
function dl(){location.href=B+'/stream?'+P()+'&key='+encodeURIComponent($('key').value)}
$('ex').textContent=`curl -H "X-API-Key: YOUR_KEY" "${B}/info?url=https://youtu.be/VIDEO_ID"\n\ncurl -H "X-API-Key: YOUR_KEY" -o video.mp4 "${B}/stream?url=https://youtu.be/VIDEO_ID&q=480"`;
$('ex2').textContent=`const res = await fetch("${B}/stream?url=" + encodeURIComponent(url) + "&type=video&q=480",\n  { headers: { "X-API-Key": process.env.YTDLP_KEY } });\nif (!res.ok) throw new Error((await res.json()).error);\nconst buf = Buffer.from(await res.arrayBuffer());`;
</script></body></html>"""


@app.get("/docs")
def docs():
    return Response(DOCS_HTML, mimetype="text/html")


WEB_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>تنزيل الفيديو والصوت</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;background:#0f1115;color:#eee;margin:0;padding:24px 14px;line-height:1.6}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 4px;text-align:center}
.sub{text-align:center;color:#9aa;margin:0 0 18px;font-size:.9rem}
.bar{display:flex;gap:8px}
.bar input{flex:1;min-width:0;padding:14px;border-radius:12px;border:1px solid #333;background:#1a1d24;color:#eee;font-size:1rem;direction:ltr}
button,.btn{cursor:pointer;border:0;border-radius:12px;background:#2b6cff;color:#fff;padding:12px 18px;font:inherit;text-decoration:none;display:inline-block}
button:disabled{opacity:.5;cursor:wait}
.msg{text-align:center;color:#9aa;margin:18px 0}
.err{color:#ff7b7b}
.card{background:#1a1d24;border-radius:14px;padding:14px;margin-top:16px}
.head{display:flex;gap:12px;align-items:flex-start}
.head img{width:120px;max-width:38%;border-radius:10px;flex-shrink:0}
.head h3{margin:0 0 4px;font-size:1rem;word-break:break-word}
.head small{color:#9aa}
.tabs{display:flex;gap:8px;margin:14px 0 6px}
.tabs button{flex:1;background:#262a33}
.tabs button.on{background:#2b6cff}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 4px;border-top:1px solid #2a2e38}
.row span small{color:#9aa;margin-inline-start:6px}
.foot{text-align:center;color:#667;font-size:.8rem;margin-top:24px}
</style></head><body><div class="wrap">
<h1>تنزيل الفيديو والصوت</h1>
<p class="sub">الصق الرابط، اختر الصيغة والجودة، ثم نزّل</p>
<div class="bar">
  <input id="url" placeholder="https://..." autocomplete="off" inputmode="url">
  <button id="go">بحث</button>
</div>
<div id="res"></div>
<p class="foot">للاستخدام الشخصي فقط. تأكد من حقك في تنزيل المحتوى.</p>
</div>
<script>
const $=id=>document.getElementById(id);
function el(t,c,txt){const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e}
function dur(s){if(!s)return'';s=Math.round(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
  return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')}
function mb(n){return n?(n/1048576).toFixed(n>10485760?0:1)+' MB':''}
function msg(t,cls){const b=$('res');b.innerHTML='';b.appendChild(el('p','msg '+(cls||''),t))}

async function search(){
  const url=$('url').value.trim();
  if(!/^https?:\/\//i.test(url)){msg('الصق رابطاً صحيحاً يبدأ بـ http','err');return}
  msg('جارٍ التحليل… (قد يستغرق أول طلب دقيقة إن كانت الخدمة نائمة)');
  $('go').disabled=true;
  try{
    const r=await fetch('/web/info?url='+encodeURIComponent(url));
    const d=await r.json();
    if(!d.ok)throw new Error(d.error||'فشل جلب المعلومات');
    render(d,url);
  }catch(e){msg(e.message,'err')}
  $('go').disabled=false;
}

function render(d,url){
  const box=$('res');box.innerHTML='';
  const card=el('div','card');
  const head=el('div','head');
  if(d.thumbnail){const im=el('img');im.src=d.thumbnail;im.referrerPolicy='no-referrer';head.appendChild(im)}
  const meta=el('div');
  meta.appendChild(el('h3',null,d.title||'بدون عنوان'));
  meta.appendChild(el('small',null,[d.uploader,dur(d.duration)].filter(Boolean).join(' • ')));
  head.appendChild(meta);card.appendChild(head);

  const tabs=el('div','tabs'),list=el('div');
  const bV=el('button','on','فيديو ('+d.video.length+')'),bA=el('button',null,'صوت ('+d.audio.length+')');
  tabs.appendChild(bV);tabs.appendChild(bA);card.appendChild(tabs);card.appendChild(list);

  function show(items){
    list.innerHTML='';
    if(!items.length){list.appendChild(el('p','msg','لا توجد صيغ متاحة في هذا القسم'));return}
    items.forEach(o=>{
      const row=el('div','row'),sp=el('span',null,o.label);
      if(o.size)sp.appendChild(el('small',null,mb(o.size)));
      const a=el('a','btn','تنزيل');
      a.href='/web/dl?url='+encodeURIComponent(url)+'&fid='+encodeURIComponent(o.fid);
      a.setAttribute('download','');
      row.appendChild(sp);row.appendChild(a);list.appendChild(row);
    });
  }
  bV.onclick=()=>{bV.className='on';bA.className='';show(d.video)};
  bA.onclick=()=>{bA.className='on';bV.className='';show(d.audio)};
  if(d.video.length||!d.audio.length)show(d.video);else{bA.click()}
  box.appendChild(card);
}
$('go').onclick=search;
$('url').addEventListener('keydown',e=>{if(e.key==='Enter')search()});
</script></body></html>"""


@app.get("/")
def index():
    if not WEB_PUBLIC:
        return Response(DOCS_HTML, mimetype="text/html")
    return Response(WEB_HTML, mimetype="text/html")


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() or request.remote_addr or "?")


def rate_ok():
    now = time.time()
    ip = client_ip()
    if len(HITS) > 5000:
        HITS.clear()
    hits = [t for t in HITS.get(ip, []) if now - t < 60]
    if len(hits) >= RATE_LIMIT:
        HITS[ip] = hits
        return False
    hits.append(now)
    HITS[ip] = hits
    return True


@app.before_request
def guard():
    p = request.path
    if p in ("/", "/health", "/docs"):
        return None
    if p.startswith("/web/"):
        if not WEB_PUBLIC:
            return jsonify(ok=False, error="الواجهة العامة معطلة"), 404
        if not rate_ok():
            return jsonify(ok=False, error="طلبات كثيرة، انتظر دقيقة ثم حاول مجددا"), 429
        return None
    if not auth_ok():
        return jsonify(ok=False, error="unauthorized"), 401


@app.get("/health")
def health():
    return jsonify(ok=True, yt_dlp=yt_dlp.version.__version__)


@app.get("/info")
def info():
    url = valid_url()
    if not url:
        return jsonify(ok=False, error="url مطلوب"), 400
    try:
        d = extract(url)
    except Exception as e:
        return err(e)
    formats = [
        {
            "id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": f.get("height"),
            "size": f.get("filesize") or f.get("filesize_approx"),
            "video": f.get("vcodec") not in (None, "none"),
            "audio": f.get("acodec") not in (None, "none"),
        }
        for f in d.get("formats", [])
    ]
    return jsonify(
        ok=True,
        title=d.get("title"),
        uploader=d.get("uploader"),
        duration=d.get("duration"),
        thumbnail=d.get("thumbnail"),
        formats=formats,
    )


@app.get("/link")
def link():
    """يرجع رابط مباشر. ملاحظة: روابط يوتيوب مرتبطة بـ IP السيرفر، الأفضل استخدام /stream"""
    url = valid_url()
    if not url:
        return jsonify(ok=False, error="url مطلوب"), 400
    try:
        d = extract(url, selector(request.args.get("type", "video"), request.args.get("q")))
    except Exception as e:
        return err(e)
    return jsonify(ok=True, title=d.get("title"), ext=d.get("ext"), url=d.get("url"))


def do_stream(url, fmt, kind="video"):
    """يمرر الملف عبر السيرفر (يدعم Range). يوتيوب يربط الرابط بـ IP لذلك التمرير ضروري."""
    if not DL_SLOTS.acquire(blocking=False):
        return jsonify(ok=False, error="الخادم مشغول بتنزيلات أخرى، حاول بعد قليل"), 429
    try:
        d = extract(url, fmt)
        direct = d.get("url")
        if not direct:
            DL_SLOTS.release()
            return jsonify(ok=False, error="لم يتم العثور على صيغة مباشرة"), 404

        headers = dict(d.get("http_headers") or {})
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        r = requests.get(direct, headers=headers, stream=True, timeout=30)
    except Exception as e:
        DL_SLOTS.release()
        return err(e)

    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", d.get("title") or "file")[:80]
    ext = d.get("ext") or ("m4a" if kind == "audio" else "mp4")
    out = {"Content-Disposition": "attachment; filename*=UTF-8''" + requests.utils.quote(name + "." + ext)}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        if r.headers.get(h):
            out[h] = r.headers[h]

    def gen():
        try:
            yield from r.iter_content(chunk_size=256 * 1024)
        finally:
            r.close()
            DL_SLOTS.release()

    return Response(stream_with_context(gen()), status=r.status_code, headers=out)


@app.get("/stream")
def stream():
    url = valid_url()
    if not url:
        return jsonify(ok=False, error="url مطلوب"), 400
    kind = request.args.get("type", "video")
    return do_stream(url, selector(kind, request.args.get("q")), kind)


# ------------------- الواجهة العامة (بدون مفتاح) -------------------
def collect_options(d):
    vids, auds = {}, {}
    for f in d.get("formats", []):
        if f.get("protocol") not in ("http", "https") or not f.get("url") or f.get("ext") == "mhtml":
            continue
        has_v = f.get("vcodec") != "none"
        has_a = f.get("acodec") != "none"
        size = f.get("filesize") or f.get("filesize_approx")
        ext = (f.get("ext") or "").upper()
        if has_v and has_a:
            h = f.get("height") or 0
            score = (f.get("ext") == "mp4", f.get("tbr") or 0)
            if h not in vids or score > vids[h][0]:
                label = (f"{h}p" if h else "جودة قياسية") + f" • {ext}"
                vids[h] = (score, {"fid": f["format_id"], "label": label, "size": size})
        elif has_a and not has_v:
            abr = int(f.get("abr") or 0)
            key = (ext, abr)
            if key not in auds:
                label = f"{ext}" + (f" • {abr}kbps" if abr else "")
                auds[key] = ((abr,), {"fid": f["format_id"], "label": label, "size": size})
    video = [v[1] for _, v in sorted(vids.items(), key=lambda x: -x[0])]
    audio = [v[1] for v in sorted(auds.values(), key=lambda x: -x[0][0])]
    return video, audio


@app.get("/web/info")
def web_info():
    url = valid_url()
    if not url:
        return jsonify(ok=False, error="الرابط غير صحيح"), 400
    try:
        d = extract(url)
    except Exception as e:
        return err(e)
    video, audio = collect_options(d)
    if not video and not audio:
        return jsonify(ok=False, error="لا توجد صيغ قابلة للتنزيل المباشر لهذا الرابط"), 404
    return jsonify(
        ok=True,
        title=d.get("title"),
        uploader=d.get("uploader"),
        duration=d.get("duration"),
        thumbnail=d.get("thumbnail"),
        video=video,
        audio=audio,
    )


@app.get("/web/dl")
def web_dl():
    url = valid_url()
    fid = request.args.get("fid", "")
    if not url or not re.match(r"^[\w.\-+]+$", fid):
        return jsonify(ok=False, error="طلب غير صحيح"), 400
    return do_stream(url, fid)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
