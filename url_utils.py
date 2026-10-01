"""
تطبيع الروابط (URL normalization)

يحوّل:  m.site.com / mobile.site.com / youtu.be / music.youtube.com ...
إلى الصيغة القياسية:  https://www.site.com/...
ويحذف باراميترات التتبع (utm_*, fbclid, si, ...).

الفائدة الأساسية: نفس الفيديو بأي صيغة رابط => نفس مفتاح الكاش => لا استخراج مكرر.

استخدام كمكتبة:
    from url_utils import normalize_url
    normalize_url("https://m.youtube.com/watch?v=abc&si=xyz")

استخدام كسكريبت:
    python url_utils.py "https://youtu.be/dQw4w9WgXcQ?si=xx" "m.facebook.com/watch?v=1"
    cat links.txt | python url_utils.py
"""
import re
import socket
import sys
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# بادئات نسخ الموبايل/AMP التي تُحوَّل إلى www
MOBILE = {"m", "mobile", "mob", "touch", "mbasic", "wap", "amp", "m2", "mweb", "lite"}
# نطاقات ثانوية شائعة (site.co.uk)
SLD2 = {"co", "com", "org", "net", "gov", "edu", "ac"}
# روابط قصيرة/خدمات لا نضيف لها www
NO_WWW = {"t.co", "bit.ly", "goo.gl", "tinyurl.com", "redd.it", "fb.watch", "fb.me", "is.gd",
          "ow.ly", "buff.ly", "t.me", "wa.me", "dai.ly", "youtu.be", "spoti.fi", "amzn.to"}

# باراميترات تتبع لا تؤثر على المحتوى
TRACKING = {
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "igsh", "si", "feature", "pp",
    "ref", "ref_src", "ref_url", "mc_cid", "mc_eid", "_r", "_t", "is_from_webapp",
    "sender_device", "share_id", "share_app_id", "spm", "spm_id_from",
}

# موقع => (المضيف القياسي، الباراميترات المسموح بها [() = احذف الكل، None = احذف التتبع فقط]، نطاقات فرعية بديلة)
SITES = {
    "facebook.com":    ("www.facebook.com", ("v", "story_fbid", "id", "fbid", "set"), {"web", "touch", "mbasic"}),
    "instagram.com":   ("www.instagram.com", (), set()),
    "tiktok.com":      ("www.tiktok.com", (), set()),
    "twitter.com":     ("x.com", (), set()),
    "x.com":           ("x.com", (), set()),
    "reddit.com":      ("www.reddit.com", (), {"old", "new", "np"}),
    "dailymotion.com": ("www.dailymotion.com", (), set()),
    "twitch.tv":       ("www.twitch.tv", (), set()),
    "vimeo.com":       ("vimeo.com", (), set()),
    "soundcloud.com":  ("soundcloud.com", (), set()),
    "bilibili.com":    ("www.bilibili.com", ("p",), set()),
    "pinterest.com":   ("www.pinterest.com", (), set()),
}

YT_HOSTS = ("youtube.com", "youtube-nocookie.com")
YT_ID = re.compile(r"^[\w-]{6,}$")
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
HOST_OK = re.compile(r"^[\w.-]+\.\w{2,}$")


@lru_cache(maxsize=1024)
def _resolves(host):
    """هل يوجد سجل DNS لهذا المضيف؟ (يُخزَّن في الذاكرة)"""
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return True
    except OSError:
        return False


def _is_tracking(key):
    k = key.lower()
    return k.startswith("utm_") or k in TRACKING


def _query(query, keep=None):
    pairs = parse_qsl(query, keep_blank_values=True)
    if keep is None:
        pairs = [(k, v) for k, v in pairs if not _is_tracking(k)]
    else:
        pairs = [(k, v) for k, v in pairs if k in keep]
    return urlencode(pairs)


def _under(host, base):
    """يرجع النطاق الفرعي (قد يكون "") إن كان host تابعا لـ base، وإلا None"""
    if host == base:
        return ""
    if host.endswith("." + base):
        return host[: -len(base) - 1]
    return None


def _youtube(host, path, query):
    vid = None
    if host == "youtu.be":
        vid = path.strip("/").split("/")[0]
    else:
        for base in YT_HOSTS:
            sub = _under(host, base)
            if sub is None:
                continue
            q = dict(parse_qsl(query))
            m = re.match(r"^/(?:shorts|live|embed|v)/([\w-]+)", path)
            if path.rstrip("/") == "/watch" and q.get("v"):
                vid = q["v"]
            elif m:
                vid = m.group(1)
            else:  # قوائم/قنوات: نبقي المسار مع v و list فقط
                qs = _query(query, keep=("v", "list"))
                return urlunsplit(("https", "www.youtube.com", path, qs, ""))
            break
        else:
            return None
    if vid and YT_ID.match(vid):
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def normalize_url(raw, check_dns=True, add_www=True):
    """يرجع الرابط بصيغته القياسية، وإن لم يكن رابطا صالحا يرجعه كما هو."""
    if not raw:
        return raw
    url = raw.strip().strip("<>\"'")
    if url.startswith("//"):
        url = "https:" + url
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        if re.match(r"^[\w.-]+\.\w{2,}([/:?#]|$)", url):
            url = "https://" + url
        else:
            return raw.strip()
    try:
        sp = urlsplit(url)
        port = sp.port
    except ValueError:
        return url
    host = (sp.hostname or "").lower().rstrip(".")
    if sp.scheme.lower() not in ("http", "https") or not HOST_OK.match(host):
        return url

    scheme = sp.scheme.lower()
    if scheme == "http" and not port and not IPV4.match(host):
        scheme = "https"  # يوفر إعادة توجيه http -> https
    path = sp.path or "/"

    # 1) يوتيوب (youtu.be, shorts, music, m.) => watch?v=ID
    if host == "youtu.be" or any(_under(host, b) is not None for b in YT_HOSTS):
        yt = _youtube(host, path, sp.query)
        if yt:
            return yt

    # 2) روابط قصيرة معروفة
    if host == "dai.ly":
        vid = path.strip("/").split("/")[0]
        if vid:
            return f"https://www.dailymotion.com/video/{vid}"

    # 3) مواقع معروفة => مضيف قياسي + تنظيف
    for base, (canon, keep, alias) in SITES.items():
        sub = _under(host, base)
        if sub is None:
            continue
        if sub in ("", "www") or sub in MOBILE or sub in alias:
            p = path.rstrip("/") or "/"
            return urlunsplit((scheme, canon, p, _query(sp.query, keep), ""))

    # 4) أي موقع آخر (عام)
    host = _generic_host(host, check_dns, add_www)
    netloc = host + (f":{port}" if port else "")
    return urlunsplit((scheme, netloc, path, _query(sp.query), ""))


def _is_bare(labels):
    """site.com أو site.co.uk (بدون أي نطاق فرعي)"""
    return len(labels) == 2 or (len(labels) == 3 and len(labels[-1]) == 2 and labels[-2] in SLD2)


def _generic_host(host, check_dns, add_www):
    labels = host.split(".")
    www_ok = lambda h: (not check_dns) or _resolves(h)
    # أ) بادئة موبايل في أي موضع: m.site.com => www.site.com ، en.m.wikipedia.org => en.wikipedia.org
    for i, lab in enumerate(labels[:-2]):
        if lab in MOBILE:
            rest = labels[:i] + labels[i + 1:]
            if i == 0:  # كانت في البداية: نستبدلها بـ www إن كان موجودا
                www = ".".join(["www"] + rest)
                return www if www_ok(www) else ".".join(rest)
            return ".".join(rest)
    # ب) نطاق بلا www: site.com => www.site.com (إن وُجد في DNS)
    if add_www and _is_bare(labels) and host not in NO_WWW and not IPV4.match(host):
        www = "www." + host
        if www_ok(www):
            return www
    return host


if __name__ == "__main__":
    lines = sys.argv[1:] or (ln for ln in sys.stdin)
    for ln in lines:
        ln = ln.strip()
        if ln:
            print(normalize_url(ln))
