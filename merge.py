"""دمج مسار فيديو ومسار صوت منفصلين عبر ffmpeg دون ملفات مؤقتة.

التدفق: مصدر الفيديو ──pipe──┐
                              ffmpeg -c copy ──► العميل  (لا إعادة ترميز، فالكلفة منخفضة)
        مصدر الصوت  ──pipe──┘
الإخراج mp4 مجزأ (fragmented) أو webm، فيبدأ التنزيل فورا ولا يدعم Range ولا Content-Length.
"""
import os
import shutil
import subprocess
import threading

from config import MAX_MERGES, MUX_ENABLED
from streaming import STATS, open_upstream, stream_gen

MUX_SLOTS = threading.Semaphore(MAX_MERGES)
_FF = None
_FF_CHECKED = False


def ffmpeg_path():
    global _FF, _FF_CHECKED
    if not _FF_CHECKED:
        _FF_CHECKED = True
        _FF = shutil.which("ffmpeg")
        if not _FF:
            try:
                import imageio_ffmpeg
                _FF = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                _FF = None
    return _FF


def available():
    return MUX_ENABLED and bool(ffmpeg_path())


def container(vfmt):
    return "webm" if vfmt.get("ext") == "webm" else "mp4"


class _NoSlot:
    """stream_gen يستدعي slot.release()؛ هنا الخانة الحقيقية يملكها مولّد الدمج"""

    def release(self):
        pass


def _feed(fmt, up, wfd, stop):
    """ينسخ الملف كاملا (على أجزاء Range مع إعادة المحاولة) إلى طرف الكتابة في pipe"""
    gen = stream_gen(fmt, up.resp, 0, up.last, up.ranged, _NoSlot())
    try:
        with os.fdopen(wfd, "wb", buffering=0) as w:
            for piece in gen:
                if stop.is_set():
                    break
                w.write(piece)
    except OSError:
        pass   # ffmpeg أغلق الطرف الآخر (انتهى أو فشل)
    finally:
        gen.close()


def _drain(stream, sink):
    try:
        for line in iter(lambda: stream.read(1024), b""):
            if len(sink) < 4096:
                sink.append(line)
    except Exception:
        pass


def start_merge(vfmt, vup, afmt, aup):
    """يشغّل ffmpeg ويرجع (proc, stop, threads, stderr_chunks)"""
    ff = ffmpeg_path()
    vr, vw = os.pipe()
    ar, aw = os.pipe()
    cont = container(vfmt)
    flags = ["-movflags", "+frag_keyframe+empty_moov+default_base_moof"] if cont == "mp4" else []
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1",
           "-i", f"pipe:{vr}", "-i", f"pipe:{ar}", "-map", "0:v:0", "-map", "1:a:0",
           "-c", "copy", *flags, "-f", cont, "pipe:1"]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                pass_fds=(vr, ar), preexec_fn=lambda: os.nice(5))
    except Exception:
        for fd in (vr, vw, ar, aw):
            os.close(fd)
        raise
    os.close(vr)
    os.close(ar)
    stop = threading.Event()
    err = []
    threads = [threading.Thread(target=_feed, args=(vfmt, vup, vw, stop), daemon=True),
               threading.Thread(target=_feed, args=(afmt, aup, aw, stop), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True)]
    for t in threads:
        t.start()
    return proc, stop, threads, err


def stop_merge(proc, stop, threads):
    stop.set()
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    for s in (proc.stdout, proc.stderr):
        try:
            s.close()
        except Exception:
            pass
    for t in threads:
        t.join(timeout=2)


def error_text(err):
    return b"".join(err).decode("utf-8", "replace").strip()[-300:]


class MergeJob:
    """يملك عملية ffmpeg والخيوط والخانات؛ release آمن للاستدعاء أكثر من مرة"""

    def __init__(self, proc, stop, threads, slot):
        self.proc, self.stop, self.threads, self.slot = proc, stop, threads, slot
        self._lock = threading.Lock()
        self._done = False

    def release(self):
        with self._lock:
            if self._done:
                return
            self._done = True
        stop_merge(self.proc, self.stop, self.threads)
        MUX_SLOTS.release()
        self.slot.release()


def merged_chunks(job, first):
    """مولّد الاستجابة: يمرر ناتج ffmpeg ويحرّر الموارد عند الانتهاء أو انقطاع العميل"""
    try:
        yield first
        STATS["bytes"] += len(first)
        while True:
            piece = job.proc.stdout.read1(262144)
            if not piece:
                return
            STATS["bytes"] += len(piece)
            yield piece
    finally:
        job.release()
