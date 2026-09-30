"""تنزيل الملف عبر السيرفر ودمج صيغ الفيديو/الصوت المنفصلة عبر ffmpeg."""
import re
import subprocess

from flask import Response, jsonify, request
from requests.utils import quote

from config import MAX_FILE_MB, REFRESH_CODES
from errors import HttpFailure, UpstreamError
from formats import collect_options, get_fmt, match_fmt
from info_cache import get_info
from responses import jerr, err
from security import client_ip
from streaming import acquire_slot, open_upstream, stream_gen

CONTENT_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg",
                 "opus": "audio/ogg", "ogg": "audio/ogg", "flv": "video/x-flv", "3gp": "video/3gpp"}
_RANGE = re.compile(r"bytes=(\d+)-(\d*)$")


def disposition(name, ext):
    fn = f"{name}.{ext}"
    ascii_fn = re.sub(r"[^A-Za-z0-9._ \-\[\]()]+", "_", fn) or f"file.{ext}"
    return 'attachment; filename="' + ascii_fn + '"; filename*=UTF-8' + "''" + quote(fn)


def _requested_range():
    """(بداية، نهاية أو None) من هيدر Range، أو (0, None)"""
    m = _RANGE.match((request.headers.get("Range") or "").strip())
    if not m:
        return 0, None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def _open_with_refresh(url, info, fmt, cstart, cend):
    """يفتح المصدر؛ إن انتهى الرابط (401/403/404/410) يعيد الاستخراج ويحاول مرة أخيرة.
    يرجع (upstream, info, fmt)."""
    try:
        return open_upstream(fmt, cstart, cend), info, fmt
    except UpstreamError as e:
        if e.code not in REFRESH_CODES:
            raise HttpFailure(f"رفض المصدر الطلب (HTTP {e.code})")
    info = get_info(url, fresh=True)
    fmt = match_fmt(info, fmt)
    if not fmt:
        raise HttpFailure("تغيرت الصيغ المتاحة، أعد البحث عن الرابط", 409)
    try:
        return open_upstream(fmt, cstart, cend), info, fmt
    except UpstreamError as e:
        raise HttpFailure(f"رفض المصدر الطلب (HTTP {e.code})")


def _content_type(fmt):
    ext = fmt.get("ext") or "bin"
    if fmt.get("vcodec") == "none" and ext == "webm":
        return "audio/webm"
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def _file_title(info, fmt):
    title = re.sub(r'[\\/:*?"<>|\r\n]+', "_", info.get("title") or "file")[:80]
    if fmt.get("height") and fmt.get("vcodec") != "none":
        title += f" [{fmt['height']}p]"
    return title


def _needs_merge(fmt):
    return fmt.get("vcodec") not in (None, "", "none") and fmt.get("acodec") in (None, "", "none")


def _input_headers(fmt):
    headers = dict(fmt.get("http_headers") or {})
    return "\r\n".join(f"{key}: {value}" for key, value in headers.items())


def _merged_response(info, video_fmt, audio_fmt, slot):
    """يمرر ناتج ffmpeg المتدفق دون إنشاء ملف مؤقت كبير على القرص."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
    video_headers = _input_headers(video_fmt)
    audio_headers = _input_headers(audio_fmt)
    if video_headers:
        command += ["-headers", video_headers]
    command += ["-i", video_fmt["url"]]
    if audio_headers:
        command += ["-headers", audio_headers]
    command += ["-i", audio_fmt["url"], "-map", "0:v:0", "-map", "1:a:0",
                "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   bufsize=1024 * 1024)
    except FileNotFoundError:
        slot.release()
        return jerr("ffmpeg غير مثبت على الخادم", 503)

    def generate():
        try:
            while True:
                chunk = process.stdout.read(512 * 1024)
                if not chunk:
                    break
                yield chunk
            code = process.wait(timeout=15)
            if code:
                detail = process.stderr.read(1000).decode("utf-8", "ignore")
                print(f"[FFMPEG] exit={code} {detail[:300]}", flush=True)
        except Exception as error:
            process.kill()
            print(f"[FFMPEG] {error}", flush=True)
        finally:
            slot.release()

    headers = {"Content-Type": "video/mp4",
               "Content-Disposition": disposition(_file_title(info, video_fmt), "mp4"),
               "Cache-Control": "no-store"}
    response = Response(generate(), status=200, headers=headers)
    response.call_on_close(slot.release)
    return response


def _response_headers(info, fmt, up, cstart, cend):
    """يرجع (هيدرات الاستجابة، كود الحالة)"""
    headers = {"Content-Type": _content_type(fmt),
               "Content-Disposition": disposition(_file_title(info, fmt), fmt.get("ext") or "bin"),
               "Cache-Control": "no-store"}
    status = 200
    if up.ranged and up.total:
        headers["Accept-Ranges"] = "bytes"
    if up.total:
        headers["Content-Length"] = str(up.last - cstart + 1)
        if cstart > 0 or (cend is not None and cend < up.total - 1):
            status = 206
            headers["Content-Range"] = f"bytes {cstart}-{up.last}/{up.total}"
    return headers, status


def serve(url, fid, check=False, per_ip=False):
    """check=True: يتحقق فقط ويرجع الحجم دون تنزيل"""
    info = get_info(url)
    fmt = get_fmt(info, fid)
    if not fmt:
        return jerr("الصيغة غير موجودة، أعد البحث عن الرابط", 404)
    if not check and _needs_merge(fmt):
        _, audio_options = collect_options(info)
        audio_fmt = get_fmt(info, audio_options[0]["fid"]) if audio_options else None
        if not audio_fmt:
            return jerr("لا توجد صيغة صوت لدمجها مع هذا الفيديو", 409)
        slot = acquire_slot(client_ip() if per_ip else None)
        if slot is None:
            return jerr("الخادم مشغول بتنزيلات أخرى، حاول بعد قليل", 429)
        return _merged_response(info, fmt, audio_fmt, slot)
    cstart, cend = (0, None) if check else _requested_range()

    slot = acquire_slot(client_ip() if per_ip else None)
    if slot is None:
        return jerr("الخادم مشغول بتنزيلات أخرى، حاول بعد قليل", 429)
    handed_off = False
    try:
        up, info, fmt = _open_with_refresh(url, info, fmt, cstart, cend)
        if MAX_FILE_MB and up.total and up.total > MAX_FILE_MB * 1048576:
            up.resp.close()
            return jerr(f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB}MB)", 413)
        if up.last < cstart:
            up.resp.close()
            return jerr("نطاق غير صالح", 416)
        if check:
            up.resp.close()
            return jsonify(ok=True, size=up.total)
        headers, status = _response_headers(info, fmt, up, cstart, cend)
        resp = Response(stream_gen(fmt, up.resp, cstart, up.last, up.ranged, slot),
                        status=status, headers=headers)
        resp.call_on_close(slot.release)
        handed_off = True
        return resp
    except HttpFailure as f:
        return jerr(f.msg, f.code)
    except RuntimeError as e:
        return err(e)
    finally:
        if not handed_off:
            slot.release()
