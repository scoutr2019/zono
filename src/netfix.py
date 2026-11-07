"""Find servers that the computer's own DNS cannot find.

Some internet providers and filters block the names of IPTV picture servers (the log then says
"getaddrinfo failed"), although the server itself is reachable. When the normal lookup fails, Zono asks a
secure DNS service (DNS over HTTPS, at a fixed IP address so that it needs no lookup itself) for the address.
Only lookups that failed are retried this way; everything else goes through Windows as usual.
"""
import json
import socket
import ssl
import threading
import time
from urllib.parse import quote

SERVICES = ("https://1.1.1.1/dns-query?name={}&type=A", "https://8.8.8.8/resolve?name={}&type=A")
_original = socket.getaddrinfo
_cache = {}  # host -> (addresses, expiry)
_lock = threading.Lock()
_enabled = False


def _ask(host):
    """IPv4 addresses for `host` from a DNS-over-HTTPS service, [] when none answers."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    for service in SERVICES:
        try:
            request = urllib.request.Request(service.format(quote(host)), headers={"Accept": "application/dns-json"})
            with opener.open(request, timeout=4) as response:
                answer = json.loads(response.read(65536).decode("utf-8"))
            addresses = [a["data"] for a in answer.get("Answer", []) if a.get("type") == 1]
            if addresses:
                return addresses
        except (OSError, ValueError, KeyError):
            continue
    return []


def lookup(host):
    now = time.monotonic()
    with _lock:
        cached = _cache.get(host)
        if cached and cached[1] > now:
            return cached[0]
    addresses = _ask(host)
    with _lock:
        _cache[host] = (addresses, now + (1800 if addresses else 300))  # retry failures after 5 minutes
    return addresses


def _is_name(host):
    if not isinstance(host, str) or not host or host == "localhost" or "." not in host:
        return False
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        return False  # already an address
    except OSError:
        return True


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original(host, port, family, type, proto, flags)
    except socket.gaierror:
        if not _enabled or not _is_name(host) or family == socket.AF_INET6:
            raise
        addresses = lookup(host)
        if not addresses:
            raise
        results = []
        for address in addresses:
            results += _original(address, port, socket.AF_INET, type, proto, flags)
        return results


def enable():
    """Switch the fallback on for the whole program (idempotent)."""
    global _enabled
    _enabled = True
    socket.getaddrinfo = getaddrinfo
