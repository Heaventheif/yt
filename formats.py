"""دوال نقية على نتيجة الاستخراج (info): اختيار الصيغ وبناء الخيارات."""
DIRECT_PROTOCOLS = ("http", "https")
DEFAULT_HEIGHT = 720
AUDIO_EXTS = {"aac", "aiff", "flac", "m4a", "mka", "mp3", "oga", "ogg", "opus", "wav", "weba"}

def _is_direct(f):
    return f.get("protocol") in DIRECT_PROTOCOLS and bool(f.get("url")) and f.get("ext") != "mhtml"

def _has_codec(value):
    """yt-dlp يستعمل none، وأحيانا None/فراغ، للدلالة على غياب المسار."""
    return bool(value) and value != "none"

def _has_video(f):
    if _has_codec(f.get("vcodec")):
        return True
    if _has_codec(f.get("acodec")):
        return False
    # Generic direct URLs may omit both codec fields; retain the old useful
    # behavior and infer from the extension instead of dropping the format.
    return str(f.get("ext") or "").lower() not in AUDIO_EXTS

def _has_audio(f):
    if _has_codec(f.get("acodec")):
        return True
    if _has_codec(f.get("vcodec")):
        return False
    return str(f.get("ext") or "").lower() in AUDIO_EXTS

def _size(f):
    return f.get("filesize") or f.get("filesize_approx")

def _codec(value):
    return value if value and value != "none" else ""

def _option(f, kind):
    ext = (f.get("ext") or "bin").upper()
    height = f.get("height") or 0
    abr = round(float(f.get("abr") or 0)) if f.get("abr") else 0
    tbr = round(float(f.get("tbr") or 0)) if f.get("tbr") else 0
    has_video = _has_video(f)
    has_audio = _has_audio(f)
    if kind == "audio":
        label = f"{ext} • {abr}kbps" if abr else ext
    else:
        quality = f"{height}p" if height else "جودة قياسية"
        tracks = "فيديو + صوت" if has_audio else "فيديو فقط"
        label = f"{quality} • {ext} • {tracks}"
    return {"fid": str(f["format_id"]), "label": label, "size": _size(f),
            "height": height, "ext": f.get("ext"), "vcodec": _codec(f.get("vcodec")),
            "acodec": _codec(f.get("acodec")), "abr": abr or None, "tbr": tbr or None,
            "fps": f.get("fps"), "resolution": f.get("resolution"),
            "format_note": f.get("format_note"), "has_audio": has_audio, "has_video": has_video}

def collect_options(info):
    """يرجع كل الصيغ المباشرة، بلا اختزال صيغة واحدة لكل جودة."""
    videos, audios, seen = [], [], set()
    for f in info.get("formats", []):
        if not _is_direct(f) or not f.get("format_id"):
            continue
        fid = str(f["format_id"])
        if fid in seen:
            continue
        seen.add(fid)
        if _has_video(f):
            videos.append(_option(f, "video"))
        elif _has_audio(f):
            audios.append(_option(f, "audio"))
    videos.sort(key=lambda o: (o["height"] or 0, o["tbr"] or 0, o["has_audio"], o["ext"] == "mp4"), reverse=True)
    audios.sort(key=lambda o: (o["abr"] or 0, o["tbr"] or 0, o["ext"] in ("m4a", "mp3")), reverse=True)
    return videos, audios

def get_fmt(info, fid):
    for f in info.get("formats", []):
        if str(f.get("format_id")) == str(fid) and f.get("url") and _is_direct(f):
            return f
    return None

def match_fmt(info, old):
    f = get_fmt(info, old.get("format_id"))
    if f:
        return f
    want_audio_only = not _has_codec(old.get("vcodec"))
    for f in info.get("formats", []):
        if (f.get("ext") == old.get("ext") and f.get("height") == old.get("height")
                and (not _has_video(f)) == want_audio_only and f.get("url")
                and f.get("protocol") in DIRECT_PROTOCOLS):
            return f
    return None

def pick_fid(info, kind, quality):
    video, audio = collect_options(info)
    if kind == "audio":
        return audio[0]["fid"] if audio else None
    if not video:
        return None
    try:
        limit = int(quality) if str(quality).isdigit() else DEFAULT_HEIGHT
    except (TypeError, ValueError):
        limit = DEFAULT_HEIGHT
    for option in video:
        if (option["height"] or 0) <= limit:
            return option["fid"]
    return video[-1]["fid"]

def info_payload(info):
    video, audio = collect_options(info)
    return {"ok": True, "title": info.get("title"), "uploader": info.get("uploader"),
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"),
            "extractor": info.get("extractor"), "format_count": len(video) + len(audio),
            "video": video, "audio": audio}
