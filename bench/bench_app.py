# harness: يحاكي استخراجاً بطيئاً (CPU 0.1 على Render) لقياس تجويع الخيوط
import os, sys, time
sys.path.insert(0, os.environ.get("APP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
import info_cache
def slow(url):
    time.sleep(float(os.environ.get("FAKE_EXTRACT_SEC", "20")))
    return {"title": "t", "uploader": None, "duration": 1, "thumbnail": None, "extractor": "x", "formats": []}
info_cache.smart_extract = slow
from app import app
