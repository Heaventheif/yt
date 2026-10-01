"""دوال نقية على نتيجة الاستخراج (info): اختيار الصيغ وبناء الخيارات. لا شبكة ولا Flask هنا.

الخيارات:
  - صيغة مباشرة فيها فيديو+صوت (muxed)            fid = معرّف الصيغة
  - فيديو منفصل + أفضل صوت متوافق يُدمجان بـ ffmpeg   fid = "videoId+audioId"
  - فيديو بلا صوت                                  fid = معرّف الصيغة
  - صوت فقط (كل الأنواع والجودات)
"""
import re

import merge
from config import MP3_BITRATES, MP3_ENABLED

DIRECT_PROTOCOLS = ("http", "https")
DEFAULT_HEIGHT = 720
_CODEC_NAMES = (("avc1", "H.264"), ("h264", "H.264"), ("vp09", "VP9"), ("vp9", "VP9"), ("av01", "AV1"),
                ("hev1", "H.265"), ("hvc1", "H.265"), ("vp8", "VP8"))
_CODEC_RANK = {"H.264": 3, "VP9": 2, "AV1": 1}   # أفضلية التوافق داخل نفس الحاوية


def _is_direct(f):
    return f.get("protocol") in DIRECT_PROTOCOLS and bool(f.get("url")) and f.get("ext") != "mhtml"


def _size(f):
    return f.get("filesize") or f.get("filesize_approx")


def _has_video(f):
    return f.get("vcodec") != "none"   # None (مجهول) يُعدّ فيديو، كالسلوك الأصلي


def _has_audio(f):
    return f.get("acodec") != "none"


def _codec(f):
    c = (f.get("vcodec") or "").lower()
    for key, name in _CODEC_NAMES:
        if c.startswith(key):
            return name
    return ""


def _family(f):
    """حاوية الإخراج المتوقعة: mp4 أو webm (وإلا ext كما هو)"""
    ext = f.get("ext") or ""
    return "mp4" if ext in ("mp4", "m4a", "m4v", "mov") else ext


def _score(f):
    return (_CODEC_RANK.get(_codec(f), 0), f.get("tbr") or 0)


def _label(f, merged=False, silent=False):
    h = f.get("height") or 0
    fps = int(f.get("fps") or 0)
    parts = [(f"{h}p" + (str(fps) if fps > 30 else "")) if h else "جودة قياسية", (f.get("ext") or "").upper()]
    if _codec(f):
        parts.append(_codec(f))
    if merged:
        parts.append("دمج")
    if silent:
        parts.append("بدون صوت")
    return " • ".join(parts)


def _best_audio(formats, family):
    """أفضل صوت مباشر متوافق مع الحاوية: m4a للـ mp4، webm/opus للـ webm"""
    want = "m4a" if family == "mp4" else "webm"
    cands = [f for f in formats if _is_direct(f) and _has_audio(f) and not _has_video(f) and f.get("ext") == want]
    return max(cands, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)


def _mp3_source(formats):
    """مصدر التحويل: أفضل صوت منفصل (m4a أولا)، وإلا أخف صيغة جاهزة (يُهمل فيديوها بـ -vn)"""
    audio_only = [f for f in formats if _is_direct(f) and _has_audio(f) and not _has_video(f)]
    if audio_only:
        return max(audio_only, key=lambda f: (f.get("ext") == "m4a", f.get("abr") or f.get("tbr") or 0))
    muxed = [f for f in formats if _is_direct(f) and _has_audio(f) and _has_video(f)]
    return min(muxed, key=lambda f: f.get("tbr") or 1 << 30, default=None)


_MP3_FID = re.compile(r"^mp3_(\d{2,3})$")


def _add_audio(audios, f):
    ext = (f.get("ext") or "").upper()
    abr = int(f.get("abr") or 0)
    key = (ext, abr)
    if key in audios:
        return
    label = ext + (f" • {abr}kbps" if abr else "")
    audios[key] = (abr, {"fid": f["format_id"], "label": label, "size": _size(f), "height": 0})


def collect_options(info, allow_merge=True):
    """يرجع (قائمة الفيديو، قائمة الصوت) مرتبة من الأفضل.
    allow_merge=False يستبعد خيارات الدمج (مثلا عند طلب رابط مباشر واحد)."""
    formats = info.get("formats", [])
    can_merge = allow_merge and merge.available()
    best = {}      # (height, family) -> (score, option, has_audio)
    silent = {}    # (height, family) -> (score, option)

    def put(table, key, score, opt, prefer_new):
        old = table.get(key)
        if old is None or prefer_new(score, old[0]):
            table[key] = (score, opt)

    audios = {}
    for f in formats:
        if not _is_direct(f):
            continue
        v, a = _has_video(f), _has_audio(f)
        if a and not v:
            _add_audio(audios, f)
            continue
        if not v:
            continue
        h, fam = f.get("height") or 0, _family(f)
        if a:   # صيغة جاهزة بصوت: الأفضلية لها على الدمج (أخف وتدعم الاستئناف)
            opt = {"fid": f["format_id"], "label": _label(f), "size": _size(f), "height": h, "sound": True}
            put(best, (h, fam), (1,) + _score(f), opt, lambda n, o: n > o)
            continue
        # فيديو بلا صوت
        opt = {"fid": f["format_id"], "label": _label(f, silent=True), "size": _size(f), "height": h, "sound": False}
        put(silent, (h, fam), _score(f), opt, lambda n, o: n > o)
        if can_merge and fam in ("mp4", "webm"):
            au = _best_audio(formats, fam)
            if au:
                size = (_size(f) + _size(au)) if _size(f) and _size(au) else None
                mopt = {"fid": f"{f['format_id']}+{au['format_id']}", "label": _label(f, merged=True),
                        "size": size, "height": h, "sound": True}
                put(best, (h, fam), (0,) + _score(f), mopt, lambda n, o: n > o)

    rows = [(h, fam, 0, opt) for (h, fam), (_, opt) in best.items()]
    rows += [(h, fam, 1, opt) for (h, fam), (_, opt) in silent.items()]
    rows.sort(key=lambda r: (-r[0], r[2], 0 if r[1] == "mp4" else 1))
    video = [dict(r[3]) for r in rows]
    audio = [v[1] for v in sorted(audios.values(), key=lambda x: -x[0])]
    if allow_merge and MP3_ENABLED and merge.available():
        src = _mp3_source(formats)
        if src:   # خيارات التحويل أولا في تبويب الصوت
            mp3 = [{"fid": f"{src['format_id']}+mp3_{k}", "label": f"MP3 • {k}kbps • تحويل", "size": None,
                    "height": 0, "convert": True} for k in MP3_BITRATES]
            audio = mp3 + audio
    return video, audio


def _find(info, fid):
    for f in info.get("formats", []):
        if f.get("format_id") == fid and f.get("url"):
            return f
    return None


def split_fid(fid):
    """'137+140' -> ('137', '140') ؛ صيغة عادية -> (fid, None)"""
    if "+" in fid:
        v, a = fid.split("+", 1)
        return v, a
    return fid, None


def get_fmt(info, fid):
    return _find(info, split_fid(fid)[0])


def get_mp3_job(info, fid):
    """(source_fmt, kbps) إن كان fid خيار تحويل MP3 (مثل 140+mp3_128) وإلا None"""
    src, tag = split_fid(fid)
    m = _MP3_FID.match(tag or "")
    if not m or not MP3_ENABLED or int(m.group(1)) not in MP3_BITRATES:
        return None
    fmt = _find(info, src)
    return (fmt, int(m.group(1))) if fmt else None


def get_merge_pair(info, fid):
    """(video_fmt, audio_fmt) إن كان fid خيار دمج، وإلا None"""
    v, a = split_fid(fid)
    if not a or _MP3_FID.match(a):
        return None
    vf, af = _find(info, v), _find(info, a)
    return (vf, af) if vf and af else None


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


def pick_fid(info, kind, quality, allow_merge=True):
    """يختار معرّف الصيغة: أفضل صوت، أو أعلى فيديو (بصوت) لا يتجاوز الجودة المطلوبة"""
    video, audio = collect_options(info, allow_merge)
    if kind == "mp3":   # type=mp3&q=192 → أعلى معدل لا يتجاوز q (الافتراضي 128)
        want = int(quality) if str(quality).isdigit() else 128
        opts = [(int(o["fid"].rsplit("_", 1)[1]), o["fid"]) for o in audio if o.get("convert")]
        ok = [o for o in opts if o[0] <= want] or opts[-1:]
        return ok[0][1] if ok else None
    if kind == "audio":
        raw = [o for o in audio if not o.get("convert")]
        return raw[0]["fid"] if raw else None
    video = [o for o in video if o.get("sound")]
    if not video:
        return None
    limit = int(quality) if str(quality).isdigit() else DEFAULT_HEIGHT
    for o in video:
        if (o["height"] or 0) <= limit:
            return o["fid"]
    return video[-1]["fid"]


def info_payload(info, allow_merge=True):
    video, audio = collect_options(info, allow_merge)
    return {"ok": True, "title": info["title"], "uploader": info["uploader"],
            "duration": info["duration"], "thumbnail": info["thumbnail"],
            "video": video, "audio": audio}


def detail_options(info):
    """كل الصيغ المباشرة بلا دمج أو تجميع (للوضع المتقدم): الحاوية والترميز والإطارات والحجم.
    fid هنا هو معرّف الصيغة الخام؛ الصيغ المنفصلة تُنزَّل كما هي (فيديو بلا صوت أو صوت فقط)."""
    rows = []
    for f in info.get("formats", []):
        if not _is_direct(f) or not f.get("format_id"):
            continue
        v, a = _has_video(f), _has_audio(f)
        rows.append({"fid": f["format_id"], "kind": "av" if v and a else ("video" if v else "audio"),
                     "height": f.get("height") or 0, "fps": int(f.get("fps") or 0), "container": f.get("ext") or "",
                     "codec": _codec(f) or (f.get("acodec") or "").split(".")[0], "tbr": int(f.get("tbr") or 0),
                     "size": _size(f)})
    rows.sort(key=lambda r: (r["kind"] == "audio", -r["height"], -r["fps"], -r["tbr"]))
    return rows
