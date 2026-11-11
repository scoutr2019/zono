"""Linking Zono apps: "continue watching", favourites and the last channel, shared between Windows, LG and Android TV.

How it works (the same in the TV app, js/sync.js):
- The id and the key come from the subscription (server, user, password) or from a link code, on the device itself.
  zono.be only sees the id and a locked package (NaCl secretbox: XSalsa20-Poly1305) it cannot open.
- The package holds, per profile name: progress, favourites and the last channel, each with the time it changed.
  Every device merges: per title the newest change wins (also "finished" and "removed from favourites").
- Titles are matched across apps by kind + the provider's id ("m123" film, "e456" episode, "l7" channel,
  "s9" series), or for playlists by a hash of the stream link.
"""
import base64
import hashlib
import hmac
import json
import os
import struct
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API = "https://zono.be/api/sync.php"
VERSION = 1
MAX_PROGRESS, MAX_FAVORITES = 300, 600


# ---------------------------------------------------------------- NaCl secretbox (XSalsa20-Poly1305), pure Python
def _rotl(v, c):
    return ((v << c) & 0xffffffff) | (v >> (32 - c))


def _salsa_rounds(x):
    for _ in range(10):
        for a, b, c, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11)):
            x[b] ^= _rotl((x[a] + x[d]) & 0xffffffff, 7)
            x[c] ^= _rotl((x[b] + x[a]) & 0xffffffff, 9)
            x[d] ^= _rotl((x[c] + x[b]) & 0xffffffff, 13)
            x[a] ^= _rotl((x[d] + x[c]) & 0xffffffff, 18)
        for a, b, c, d in ((0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
            x[b] ^= _rotl((x[a] + x[d]) & 0xffffffff, 7)
            x[c] ^= _rotl((x[b] + x[a]) & 0xffffffff, 9)
            x[d] ^= _rotl((x[c] + x[b]) & 0xffffffff, 13)
            x[a] ^= _rotl((x[d] + x[c]) & 0xffffffff, 18)
    return x


_SIGMA = struct.unpack("<4I", b"expand 32-byte k")


def _state(key, nonce16):
    k = struct.unpack("<8I", key)
    n = struct.unpack("<4I", nonce16)
    return [_SIGMA[0], k[0], k[1], k[2], k[3], _SIGMA[1], n[0], n[1], n[2], n[3], _SIGMA[2], k[4], k[5], k[6], k[7],
            _SIGMA[3]]


def _hsalsa20(key, nonce16):
    x = _salsa_rounds(_state(key, nonce16))
    return struct.pack("<8I", x[0], x[5], x[10], x[15], x[6], x[7], x[8], x[9])


def _salsa20_stream(key, nonce8, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        start = _state(key, nonce8 + struct.pack("<Q", counter))
        x = _salsa_rounds(list(start))
        out += struct.pack("<16I", *((x[i] + start[i]) & 0xffffffff for i in range(16)))
        counter += 1
    return bytes(out[:length])


def _poly1305(key, message):
    r = int.from_bytes(key[:16], "little") & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key[16:], "little")
    p, acc = (1 << 130) - 5, 0
    for i in range(0, len(message), 16):
        block = message[i:i + 16] + b"\x01"
        acc = (acc + int.from_bytes(block, "little")) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def seal(message, key):
    """nonce (24) + Poly1305 tag (16) + ciphertext: the same as tweetnacl's nonce + secretbox(message)."""
    nonce = os.urandom(24)
    subkey = _hsalsa20(key, nonce[:16])
    stream = _salsa20_stream(subkey, nonce[16:], 32 + len(message))
    cipher = bytes(a ^ b for a, b in zip(message, stream[32:]))
    return nonce + _poly1305(stream[:32], cipher) + cipher


def unseal(box, key):
    """The message, or None when the package was not locked with this key (or was changed)."""
    if len(box) < 40:
        return None
    nonce, tag, cipher = box[:24], box[24:40], box[40:]
    subkey = _hsalsa20(key, nonce[:16])
    stream = _salsa20_stream(subkey, nonce[16:], 32 + len(cipher))
    if not hmac.compare_digest(_poly1305(stream[:32], cipher), tag):
        return None
    return bytes(a ^ b for a, b in zip(cipher, stream[32:]))


# ---------------------------------------------------------------- id and key
def secret_for(source):
    """What links devices: the subscription itself (server without http/https or path, user, password)."""
    if not isinstance(source, dict):
        return ""
    if source.get("type") == "m3u" or source.get("m3u"):
        link = str(source.get("m3u") or "").strip()
        return "m3u\n" + link if link else ""
    server = str(source.get("server") or "").strip()
    host = urlsplit(server if "://" in server else "http://" + server).netloc.lower()
    user, password = str(source.get("user") or "").strip(), str(source.get("password") or "")
    return "xtream\n" + host + "\n" + user + "\n" + password if host and user and password else ""


def link_secret(code):
    return "code\n" + "".join(ch for ch in str(code).upper() if ch.isalnum())


def derive(secret):
    """(id for zono.be, 32-byte key). Slow on purpose (1000 rounds), so the id does not give the login away."""
    raw = secret.encode("utf-8")
    digest = raw
    for _ in range(1000):
        digest = hashlib.sha512(digest + raw).digest()
    return hashlib.sha512(b"zono-sync-id" + digest).digest()[:32].hex(), hashlib.sha512(b"zono-sync-key" + digest).digest()[:32]


def new_link_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(alphabet[b % len(alphabet)] for b in os.urandom(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------- the shared package
def item_key(kind, sid="", url=""):
    """The same title in every Zono app: kind letter + the provider's id, or a hash of the link."""
    letter = {"live": "l", "movie": "m", "series": "s", "episode": "e"}.get(kind, "")
    if letter and sid:
        return letter + str(sid)
    if url:
        return "u" + hashlib.sha512(str(url).encode("utf-8")).hexdigest()[:16]
    return ""


def empty():
    return {"v": VERSION, "profiles": {}}


def profile_name(name):
    return " ".join(str(name or "").lower().split()) or "main"


def merge(a, b):
    """Both packages together: per title the newest change wins."""
    out = empty()
    for package in (a, b):
        if not isinstance(package, dict):
            continue
        for name, part in (package.get("profiles") or {}).items():
            if not isinstance(part, dict):
                continue
            mine = out["profiles"].setdefault(name, {"progress": {}, "fav": {}, "last": None})
            for field in ("progress", "fav"):
                for key, entry in (part.get(field) or {}).items():
                    if isinstance(entry, dict) and (key not in mine[field] or entry.get("t", 0) > mine[field][key].get("t", 0)):
                        mine[field][key] = entry
            last = part.get("last")
            if isinstance(last, dict) and (not mine["last"] or last.get("t", 0) > mine["last"].get("t", 0)):
                mine["last"] = last
    for part in out["profiles"].values():  # keep it small: the newest ones
        for field, keep in (("progress", MAX_PROGRESS), ("fav", MAX_FAVORITES)):
            if len(part[field]) > keep:
                newest = sorted(part[field].items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:keep]
                part[field] = dict(newest)
    return out


def lock(package, key):
    raw = json.dumps(package, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(seal(raw, key)).decode("ascii")


def open_package(data, key):
    if not data:
        return empty()
    try:
        raw = unseal(base64.b64decode(data), key)
        package = json.loads(raw.decode("utf-8")) if raw is not None else None
    except (ValueError, UnicodeError):
        package = None
    return package if isinstance(package, dict) and package.get("v") == VERSION else None


# ---------------------------------------------------------------- talking to zono.be
def _get(sync_id, timeout):
    request = Request(API + "?id=" + sync_id, headers={"User-Agent": "Zono", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(1_000_000).decode("utf-8"))


def _post(sync_id, rev, data, timeout):
    body = json.dumps({"id": sync_id, "rev": rev, "data": data}).encode("utf-8")
    request = Request(API, data=body, headers={"User-Agent": "Zono", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200, json.loads(response.read(1_000_000).decode("utf-8"))
    except Exception as error:  # HTTPError 409: another device was first
        code = getattr(error, "code", 0)
        if code == 409:
            return 409, json.loads(error.read(1_000_000).decode("utf-8"))
        raise


def exchange(secret, local, timeout=12):
    """Merge `local` with what is on zono.be, store the result there and return it (or raise OSError/ValueError)."""
    sync_id, key = derive(secret)
    current = _get(sync_id, timeout)
    for _ in range(4):
        theirs = open_package(current.get("data", ""), key)
        merged = merge(theirs if theirs is not None else empty(), local)
        if theirs is not None and json.dumps(merged, sort_keys=True) == json.dumps(merge(theirs, empty()), sort_keys=True):
            return merged  # nothing new from here: no write
        status, current = _post(sync_id, int(current.get("rev", 0)), lock(merged, key), timeout)
        if status == 200:
            return merged
    raise OSError("sync: te veel gelijktijdige wijzigingen")
