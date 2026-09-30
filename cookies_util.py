import base64
import json
import os
import re

COOKIES_PATH = "/tmp/cookies.txt"

# ---- cookies: تحميل مرن (base64 / نص مباشر / JSON) وتحويل تلقائي لصيغة Netscape ----
COOKIE_STATS = {"loaded": False, "cookies": 0, "domains": []}


def _normalize_cookies(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = []
    if text[:1] in ("[", "{"):  # تصدير JSON من بعض الإضافات
        try:
            data = json.loads(text)
        except Exception:
            data = []
        if isinstance(data, dict):
            data = data.get("cookies", [])
        for c in data if isinstance(data, list) else []:
            dom, name = c.get("domain", ""), c.get("name")
            if not dom or not name:
                continue
            try:
                exp = max(int(float(c.get("expirationDate") or c.get("expires") or 0)), 0)
            except Exception:
                exp = 0
            lines.append("\t".join([
                ("#HttpOnly_" if c.get("httpOnly") else "") + dom,
                "TRUE" if dom.startswith(".") else "FALSE",
                c.get("path", "/"),
                "TRUE" if c.get("secure") else "FALSE",
                str(exp), name, str(c.get("value", "")),
            ]))
    else:
        for ln in text.split("\n"):
            if not ln.strip() or (ln.startswith("#") and not ln.startswith("#HttpOnly_")):
                continue
            parts = ln.split("\t")
            if len(parts) != 7:  # إذا تحولت التابات إلى مسافات
                parts = re.split(r"\s+", ln.strip(), maxsplit=6)
            if len(parts) == 7:
                lines.append("\t".join(parts))
    return lines


def load_cookies():
    raw = (os.getenv("COOKIES_B64") or "").strip().strip("\"'")
    if not raw:
        return
    text = raw
    lines = []
    for _ in range(3):  # يتعامل أيضا مع base64 مزدوج
        lines = _normalize_cookies(text)
        if lines:
            break
        compact = re.sub(r"\s+", "", text)
        compact += "=" * (-len(compact) % 4)
        try:
            text = base64.b64decode(compact).decode("utf-8-sig", errors="ignore")
        except Exception:
            break
    if not lines:
        print("[cookies] لم يتم العثور على أسطر كوكيز صالحة — تأكد من الملف/الترميز", flush=True)
        return
    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n")
    doms = sorted({l.split("\t")[0].replace("#HttpOnly_", "").lstrip(".") for l in lines})
    COOKIE_STATS.update(loaded=True, cookies=len(lines), domains=doms[:30])
    print(f"[cookies] loaded {len(lines)} cookies", flush=True)


load_cookies()
