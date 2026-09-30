import base64
import os
import re
import threading

import requests
import yt_dlp
from flask import Flask, Response, jsonify, request, stream_with_context

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "")
PROXY = os.getenv("PROXY", "")  # اختياري
YT_CLIENTS = [c.strip() for c in os.getenv("YT_CLIENTS", "").split(",") if c.strip()]
COOKIES_PATH = "/tmp/cookies.txt"
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


@app.before_request
def guard():
    if request.path == "/health":
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


@app.get("/stream")
def stream():
    """يمرر الملف عبر السيرفر (يدعم Range) — يعمل مع يوتيوب لأن الـ IP نفسه"""
    url = valid_url()
    if not url:
        return jsonify(ok=False, error="url مطلوب"), 400
    kind = request.args.get("type", "video")
    try:
        d = extract(url, selector(kind, request.args.get("q")))
    except Exception as e:
        return err(e)

    direct = d.get("url")
    if not direct:
        return jsonify(ok=False, error="لم يتم العثور على صيغة مباشرة"), 404

    headers = dict(d.get("http_headers") or {})
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    try:
        r = requests.get(direct, headers=headers, stream=True, timeout=30)
    except Exception as e:
        return err(e)

    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", d.get("title") or "file")[:80]
    ext = d.get("ext") or ("m4a" if kind == "audio" else "mp4")
    out = {"Content-Disposition": f'attachment; filename="{name}.{ext}"; filename*=UTF-8\'\'{requests.utils.quote(name)}.{ext}'}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        if r.headers.get(h):
            out[h] = r.headers[h]

    return Response(
        stream_with_context(r.iter_content(chunk_size=256 * 1024)),
        status=r.status_code,
        headers=out,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
