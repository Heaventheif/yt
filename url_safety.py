"""التحقق من الروابط: منع SSRF (عناوين داخلية) + قائمة مواقع مسموحة اختيارية."""
import ipaddress
import socket
from urllib.parse import urlsplit

import config


def _host_allowed(host):
    if not config.ALLOWED_HOSTS:
        return True
    return any(host == h or host.endswith("." + h) for h in config.ALLOWED_HOSTS)


def _is_global(addr):
    ip = ipaddress.ip_address(addr.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def is_public_url(url):
    """True فقط إذا كان الرابط http(s) ومضيفه مسموح وكل عناوينه عامة (ليست loopback/private/link-local)."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    # يمنع تسريب بيانات اعتماد أو تمريرها إلى طلبات HTTP، بما فيها روابط التحويل.
    if parts.scheme not in ("http", "https") or parts.username is not None or parts.password is not None:
        return False
    if not host or not _host_allowed(host):
        return False
    if config.ALLOW_PRIVATE_URLS:
        return True
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    return bool(addrs) and all(_is_global(a) for a in addrs)
