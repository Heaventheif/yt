import os, subprocess, sys, time, threading, urllib.request, urllib.error
app_dir, threads = sys.argv[1], sys.argv[2]
env = dict(os.environ, APP_DIR=app_dir, WARMUP="0", KEEP_ALIVE_MINUTES="0", API_KEY="k",
           MAX_CONCURRENT="2", FAKE_EXTRACT_SEC="15", PYTHONPATH=os.path.dirname(os.path.abspath(__file__)))
extra = sys.argv[3:]
p = subprocess.Popen(["gunicorn", "-b", "127.0.0.1:18080", "-w", "1", "--threads", threads,
                      "--timeout", "120", "bench_app:app"], env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(3)
    def hit(i):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:18080/info?url=https://example.com/v{i}",
                                         headers={"X-API-Key": "k"})
            urllib.request.urlopen(req, timeout=40).read()
        except Exception:
            pass
    for i in range(14):
        threading.Thread(target=hit, args=(i,), daemon=True).start()
    time.sleep(2)
    t = time.time()
    try:
        r = urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=5)
        res = f"HTTP {r.status}"
    except Exception as e:
        res = f"FAILED ({type(e).__name__})"
    print(f"threads={threads}: /health while 14 slow extractions are queued => {res} after {time.time()-t:.2f}s")
finally:
    p.kill(); p.wait()
