"""يزور السيرفر نفسه دوريا لمنع النوم على الخطة المجانية."""
import threading
import time

import requests

from config import KEEP_ALIVE_MIN, SELF_URL


def _loop():
    while True:
        time.sleep(KEEP_ALIVE_MIN * 60)
        try:
            requests.get(SELF_URL.rstrip("/") + "/health", timeout=20)
        except Exception:
            pass


def start():
    if SELF_URL and KEEP_ALIVE_MIN > 0:
        threading.Thread(target=_loop, daemon=True).start()
