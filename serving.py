"""تنزيل الملف عبر السيرفر كاستجابة Flask (يدعم Range والاستئناف)."""
import re

from flask import Response, jsonify, request
from requests.utils import quote

from config import MAX_FILE_MB, REFRESH_CODES
from errors import HttpFailure, UpstreamError
from formats import get_fmt, get_merge_pair, get_mp3_job, match_fmt
import merge
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
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "_", info.get("title") or "file")[:80].strip(" .") or "file"
    if fmt.get("height") and fmt.get("vcodec") != "none":
        title += f" [{fmt['height']}p]"
    return title


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


def _serve_ffmpeg(url, info, fmts, make_plan, slot, check):
    """مدخل أو أكثر → ffmpeg (دمج أو تحويل MP3) → العميل. يرجع (response, handed_off)"""
    if not merge.MUX_SLOTS.acquire(blocking=False):
        return jerr("عمليات الدمج/التحويل مشغولة، حاول بعد قليل", 429), False
    mux_held = True
    opened = []   # [(fmt, upstream)]
    try:
        for fmt in fmts:
            up, info, fmt = _open_with_refresh(url, info, fmt, 0, None)
            opened.append((fmt, up))
        totals = [up.total for _, up in opened]
        total = sum(totals) if all(totals) else None
        if MAX_FILE_MB and total and total > MAX_FILE_MB * 1048576:
            return jerr(f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB}MB)", 413), False
        plan = make_plan([f for f, _ in opened], info)
        if check:
            return jsonify(ok=True, size=total if len(opened) > 1 else None, merged=True), False
        proc, stop, threads, errbuf = merge.start_job(plan, [up for _, up in opened])
        opened = []   # صارت الاتصالات بيد خيوط التغذية
        first = b""
        try:
            first = proc.stdout.read1(262144)   # ننتظر أول بايتات ناتجة لنكشف الفشل قبل إرسال الهيدرات
        except Exception:
            pass
        if not first:
            code = proc.poll()
            msg = merge.error_text(errbuf)
            merge.stop_merge(proc, stop, threads)
            print(f"[FFMPEG] failed code={code} {msg}", flush=True)
            return jerr("تعذر الدمج/التحويل لهذه الصيغة، جرّب صيغة أخرى", 502), False
        headers = {"Content-Type": plan.content_type,
                   "Content-Disposition": disposition(_file_title(info, plan.inputs[0] if plan.ext != "mp3" else {}), plan.ext),
                   "Cache-Control": "no-store", "Accept-Ranges": "none", "X-Accel-Buffering": "no"}
        job = merge.MergeJob(proc, stop, threads, slot)
        resp = Response(merge.merged_chunks(job, first), status=200, headers=headers)
        resp.call_on_close(job.release)   # يغطي حالة انقطاع العميل قبل بدء المولّد
        mux_held = False                  # صارت MergeJob مسؤولة عن تحرير MUX_SLOTS والخانة
        return resp, True
    finally:
        for _, up in opened:
            up.resp.close()
        if mux_held:
            merge.MUX_SLOTS.release()


def serve(url, fid, check=False, per_ip=False):
    """check=True: يتحقق فقط ويرجع الحجم دون تنزيل"""
    info = get_info(url)
    fmt = get_fmt(info, fid)
    if not fmt:
        return jerr("الصيغة غير موجودة، أعد البحث عن الرابط", 404)
    pair = get_merge_pair(info, fid) if "+" in fid else None
    mp3 = get_mp3_job(info, fid) if "+" in fid else None
    if "+" in fid and not (pair or mp3) or ("+" in fid and not merge.available()):
        return jerr("الدمج/التحويل غير متاح لهذه الصيغة، أعد البحث عن الرابط", 404)
    # الدمج وMP3 لا يدعمان Range؛ If-Range بلا مُصادِق مصدر => نرسل الملف كاملا (سلوك RFC 9110 الآمن)
    full = check or pair or mp3 or bool(request.headers.get("If-Range"))
    cstart, cend = (0, None) if full else _requested_range()

    slot = acquire_slot(client_ip() if per_ip else None)
    if slot is None:
        return jerr("الخادم مشغول بتنزيلات أخرى، حاول بعد قليل", 429)
    handed_off = False
    try:
        if pair:
            resp, handed_off = _serve_ffmpeg(url, info, list(pair), lambda f, i: merge.plan_merge(*f), slot, check)
            return resp
        if mp3:
            afmt, kbps = mp3
            resp, handed_off = _serve_ffmpeg(url, info, [afmt], lambda f, i: merge.plan_mp3(f[0], kbps, i.get("title") or ""),
                                             slot, check)
            return resp
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
