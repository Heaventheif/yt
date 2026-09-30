"""دوال نقية على نتيجة الاستخراج (info): اختيار الصيغ وبناء الخيارات. لا شبكة ولا Flask هنا."""

DIRECT_PROTOCOLS = ("http", "https")
DEFAULT_HEIGHT = 720


def _is_direct(f):
    return f.get("protocol") in DIRECT_PROTOCOLS and bool(f.get("url")) and f.get("ext") != "mhtml"


def _size(f):
    return f.get("filesize") or f.get("filesize_approx")


def _add_video(videos, f):
    """يحتفظ بأفضل صيغة (mp4 ثم الأعلى bitrate) لكل ارتفاع"""
    h = f.get("height") or 0
    score = (f.get("ext") == "mp4", f.get("tbr") or 0)
    if h in videos and score <= videos[h][0]:
        return
    label = (f"{h}p" if h else "جودة قياسية") + f" • {(f.get('ext') or '').upper()}"
    videos[h] = (score, {"fid": f["format_id"], "label": label, "size": _size(f), "height": h})


def _add_audio(audios, f):
    ext = (f.get("ext") or "").upper()
    abr = int(f.get("abr") or 0)
    key = (ext, abr)
    if key in audios:
        return
    label = ext + (f" • {abr}kbps" if abr else "")
    audios[key] = (abr, {"fid": f["format_id"], "label": label, "size": _size(f), "height": 0})


def collect_options(info):
    """يرجع (قائمة الفيديو، قائمة الصوت) مرتبة من الأفضل"""
    videos, audios = {}, {}
    for f in info.get("formats", []):
        if not _is_direct(f):
            continue
        has_video = f.get("vcodec") != "none"
        has_audio = f.get("acodec") != "none"
        if has_video and has_audio:
            _add_video(videos, f)
        elif has_audio:
            _add_audio(audios, f)
    video = [v[1] for _, v in sorted(videos.items(), key=lambda x: -x[0])]
    audio = [v[1] for v in sorted(audios.values(), key=lambda x: -x[0])]
    return video, audio


def get_fmt(info, fid):
    for f in info.get("formats", []):
        if f.get("format_id") == fid and f.get("url"):
            return f
    return None


def match_fmt(info, old):
    """بعد إعادة الاستخراج قد تتغير المعرفات، نبحث عن أقرب صيغة"""
    f = get_fmt(info, old.get("format_id"))
    if f:
        return f
    want_audio_only = old.get("vcodec") == "none"
    for f in info.get("formats", []):
        if (f.get("ext") == old.get("ext") and f.get("height") == old.get("height")
                and (f.get("vcodec") == "none") == want_audio_only and f.get("url")
                and f.get("protocol") in DIRECT_PROTOCOLS):
            return f
    return None


def pick_fid(info, kind, quality):
    """يختار معرّف الصيغة: أفضل صوت، أو أعلى فيديو لا يتجاوز الجودة المطلوبة"""
    video, audio = collect_options(info)
    if kind == "audio":
        return audio[0]["fid"] if audio else None
    if not video:
        return None
    limit = int(quality) if str(quality).isdigit() else DEFAULT_HEIGHT
    for o in video:
        if (o["height"] or 0) <= limit:
            return o["fid"]
    return video[-1]["fid"]


def info_payload(info):
    video, audio = collect_options(info)
    return {"ok": True, "title": info["title"], "uploader": info["uploader"],
            "duration": info["duration"], "thumbnail": info["thumbnail"],
            "video": video, "audio": audio}
