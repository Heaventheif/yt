"""جلسة HTTP مشتركة (إعادة استخدام الاتصالات) ومجمّع خيوط للمهام المتوازية."""
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

from config import POOL_WORKERS, PROXY

sess = requests.Session()
sess.trust_env = False
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=64, max_retries=0, pool_block=True)
sess.mount("https://", _adapter)
sess.mount("http://", _adapter)
if PROXY:
    sess.proxies = {"http": PROXY, "https": PROXY}

# فحص متوازٍ للروابط + جلب الجزء التالي مسبقا
POOL = ThreadPoolExecutor(max_workers=POOL_WORKERS)
