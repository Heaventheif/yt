import os, sys, re, time, subprocess, threading, urllib.request, psutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
app_dir = sys.argv[1]
SIZE = 96 * 1048576
BLOB = os.urandom(1048576) * 96
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        a, b = (int(m[1]), min(int(m[2]) if m[2] else SIZE-1, SIZE-1)) if m else (0, SIZE-1)
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", "video/mp4"); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b-a+1))
        if m: self.send_header("Content-Range", f"bytes {a}-{b}/{SIZE}")
        self.end_headers()
        try: self.wfile.write(BLOB[a:b+1])
        except Exception: pass
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
src = f"http://127.0.0.1:{srv.server_address[1]}/a.mp4"
env = dict(os.environ, ALLOW_PRIVATE_URLS="1", API_KEY="k", WARMUP="0", KEEP_ALIVE_MINUTES="0", COOKIES_B64="")
t0 = time.time()
p = subprocess.Popen(["gunicorn", "-b", "127.0.0.1:18081", "-w", "1", "--threads", "12", "app:app"],
                     cwd=app_dir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    while True:
        try: urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=1); break
        except Exception: time.sleep(0.05)
    print(f"boot->first /health: {time.time()-t0:.2f}s")
    root = psutil.Process(p.pid); worker = root.children()[0]
    print(f"worker RSS idle: {worker.memory_info().rss/1048576:.0f} MB")
    def get(path):
        req = urllib.request.Request("http://127.0.0.1:18081"+path, headers={"X-API-Key": "k"})
        return urllib.request.urlopen(req, timeout=60)
    t = time.time(); get(f"/info?url={src}").read(); print(f"/info (generic .mp4, local origin): {time.time()-t:.2f}s")
    c0 = sum(worker.cpu_times()[:2]); t = time.time(); n = 0
    r = get(f"/stream?url={src}&type=video&q=480")
    while True:
        b = r.read(1048576)
        if not b: break
        n += len(b)
    dt = time.time()-t; cpu = sum(worker.cpu_times()[:2]) - c0
    print(f"streamed {n/1048576:.0f} MB in {dt:.2f}s ({n/1048576/dt:.0f} MB/s), server CPU {cpu:.2f}s => {cpu/(n/1048576)*1000:.1f} ms CPU per MB")
    print(f"=> ceiling at 0.1 CPU ≈ {0.1/(cpu/(n/1048576)):.1f} MB/s total across ALL streams")
    print(f"worker RSS after: {worker.memory_info().rss/1048576:.0f} MB")
finally:
    p.kill(); p.wait()
