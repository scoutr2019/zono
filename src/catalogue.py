import json
import os
import re
import secrets
import threading
import shutil
import ctypes
import hashlib
import hmac
from base64 import b64decode, b64encode
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit, quote
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from i18n import T

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home()))
ROOT = APP_DATA / "Zono"
PROFILES = ROOT / "profiles.json"
LOG = ROOT / "zono.log"
STATE = ROOT / "library.json"
LEGACY = APP_DATA / "Luma IPTV" / "library.json"
SOURCE_LIMIT = 256 * 1024 * 1024

def check_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(T("Gebruik een geldige HTTP- of HTTPS-link."))
    return url

def fetch(url, step="M3U-afspeellijst"):
    request = Request(check_url(url), headers={"User-Agent": "VLC/3.0 LibVLC/3.0",
                                               "Accept": "*/*", "Connection": "close"})
    openers = (urlopen, build_opener(ProxyHandler({})).open)
    for open_request in openers:
        try:
            with open_request(request, timeout=30) as response:
                data = response.read(SOURCE_LIMIT + 1)
            break
        except (RemoteDisconnected, ConnectionResetError):
            continue
    else:
        scheme = urlsplit(url).scheme.upper()
        raise ValueError(T('{}: de verbinding via {} werd twee keer gesloten zonder antwoord. Controleer het protocol en de poort met je IPTV-provider.').format(step, scheme))
    if len(data) > SOURCE_LIMIT:
        raise ValueError(T('{}: het antwoord van de provider is groter dan 256 MiB.').format(step))
    return data.decode("utf-8-sig", errors="replace")

def parse_m3u(raw):
    entries = []
    info = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
            title = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line, maxsplit=1)
            info = {"title": title[-1].strip(), "image": attrs.get("tvg-logo", ""),
                    "group": attrs.get("group-title") or "Overige"}
            if attrs.get("tvg-id"):
                info["epg"] = attrs["tvg-id"]  # the channel's id in the XMLTV guide
            if attrs.get("tvg-name"):
                info["tvg_name"] = attrs["tvg-name"]
        elif info is not None and line and not line.startswith("#"):
            if urlsplit(line).scheme in ("http", "https"):
                kind = "movie" if "/movie/" in urlsplit(line).path or urlsplit(line).path.lower().endswith((".mp4", ".mkv", ".avi")) else "live"
                entries.append(dict(info, id=line, url=line, kind=kind))
            info = None
    return entries

def server_base(source):
    parts = urlsplit(check_url(source["server"]))
    path = re.sub(r"/(?:player_api|get|panel_api)\.php/?$", "", parts.path, flags=re.I)
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))

_SECURE = {}
_SECURE_LOCK = threading.Lock()


def api_base(source):
    """Prefer HTTPS for the account API when the provider offers it, so the password never travels in plain
    text (virus scanners such as Bitdefender block those requests). Falls back to the address as entered."""
    base = server_base(source)
    parts = urlsplit(base)
    if parts.scheme != "http" or not parts.hostname:
        return base
    with _SECURE_LOCK:
        if base in _SECURE:
            return _SECURE[base]
        _SECURE[base] = base
        host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
        candidates = [urlunsplit(("https", host, parts.path, "", ""))]
        if parts.port not in (None, 80, 443):
            candidates.append(urlunsplit(("https", f"{host}:{parts.port}", parts.path, "", "")))
        query = urlencode(dict(username=source["user"], password=source["password"]))
        for candidate in candidates:
            try:
                request = Request(f"{candidate}/player_api.php?{query}", headers={"User-Agent": "VLC/3.0 LibVLC/3.0"})
                with urlopen(request, timeout=4) as response:
                    answer = json.loads(response.read(2 * 1024 * 1024).decode("utf-8", "replace"))
                if isinstance(answer, dict) and isinstance(answer.get("user_info"), dict) and \
                        str(answer["user_info"].get("auth", "1")) != "0":
                    _SECURE[base] = candidate
                    break
            except Exception:
                continue
        return _SECURE[base]


def xtream(source, action, **extra):
    query = dict(username=source["user"], password=source["password"], action=action, **extra)
    data = json.loads(fetch(api_base(source) + "/player_api.php?" + urlencode(query), f"Xtream ({action})"))
    return data

def stream_url(source, kind, stream_id, extension=""):
    credentials = "/".join(quote(source[key], safe="") for key in ("user", "password"))
    suffix = "." + extension if extension else ""
    return f'{server_base(source)}/{kind}/{credentials}/{quote(str(stream_id), safe="")}{suffix}'

def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and number > 0 else 0.0


def catalog(source):
    source = dict(source, server=server_base(source))
    entries = []
    for kind, action, key in (("live", "live_streams", "stream_id"),
                              ("movie", "vod_streams", "stream_id"),
                              ("series", "series", "series_id")):
        categories = xtream(source, "get_" + ("vod" if kind == "movie" else kind) + "_categories")
        groups = {str(c["category_id"]): c["category_name"] for c in (categories if isinstance(categories, list) else []) if isinstance(c, dict) and "category_id" in c and "category_name" in c}
        rows = xtream(source, "get_" + action)
        if not isinstance(rows, list):
            raise ValueError(T("Xtream gaf geen geldige catalogus terug. Controleer je gegevens."))
        for row in rows:
            if not isinstance(row, dict) or key not in row:
                continue
            sid = str(row[key])
            entry = dict(id=f'{source["server"]}|{kind}|{sid}', sid=sid, kind=kind,
                         title=row.get("name") or sid,
                         group=groups.get(str(row.get("category_id")), "Overige"),
                         image=row.get("cover") or row.get("stream_icon") or "",
                         url="" if kind == "series" else stream_url(source, kind, sid,
                             "m3u8" if kind == "live" else row.get("container_extension") or "mp4"))
            if kind == "live":
                entry["archive"] = 1 if str(row.get("tv_archive") or "0") not in ("0", "", "None") else 0
                entry["archive_days"] = int(_number(row.get("tv_archive_duration")))
                if row.get("epg_channel_id"):
                    entry["epg"] = str(row["epg_channel_id"])  # id in the provider's XMLTV guide (for searching)
            if kind != "live":
                rating = _number(row.get("rating")) or _number(row.get("rating_5based")) * 2
                entry["rating"] = round(min(rating, 10.0), 1)
                entry["added"] = int(_number(row.get("added") or row.get("last_modified")))
                wide = row.get("backdrop_path")
                wide = wide[0] if isinstance(wide, list) and wide else wide
                if isinstance(wide, str) and wide.startswith(("http://", "https://")):
                    entry["backdrop"] = wide
            entries.append(entry)
    return entries

def episodes(source, sid):
    data = xtream(source, "get_series_info", series_id=sid)
    return episode_rows(source, data)

def episode_rows(source, data):
    seasons = data.get("episodes") or {}
    if isinstance(seasons, list):
        seasons = dict(enumerate(seasons, 1))
    import countries
    rows = []
    for season, items in seasons.items():
        for ep in items or []:
            raw = ep.get("title") or str(ep["id"])
            try:
                number = int(ep.get("episode_num") or 0)
            except (TypeError, ValueError):
                number = 0
            rows.append(dict(id=f'{source["server"]}|episode|{ep["id"]}', title=countries.clean_episode(raw, number),
                             raw_title=raw, group=f"Seizoen {season}", kind="movie",
                             url=stream_url(source, "series", ep["id"], ep.get("container_extension") or "mp4")))
    return rows

def _programs(data):
    if not isinstance(data, dict):
        return []
    programs = []
    for row in data.get("epg_listings") or []:
        if not isinstance(row, dict):
            continue
        title = row.get("title") or ""
        try:
            title = b64decode(title, validate=True).decode()
        except (ValueError, UnicodeError):
            pass
        try:
            start = int(row.get("start_timestamp") or 0)
            end = int(row.get("stop_timestamp") or 0)
        except (TypeError, ValueError):
            start = end = 0
        archive = None if "has_archive" not in row else str(row.get("has_archive")) not in ("0", "", "None", "False")
        programs.append(dict(title=title, start=start, end=end, label=row.get("start") or "", archive=archive))
    return programs


def guide(source, sid):
    return _programs(xtream(source, "get_short_epg", stream_id=sid, limit=12))


def full_guide(source, sid):
    """Whole schedule including past programmes (needed for catch-up). Falls back to the short guide."""
    try:
        rows = _programs(xtream(source, "get_simple_data_table", stream_id=sid))
    except (ValueError, HTTPError, URLError, OSError):
        rows = []
    return rows or guide(source, sid)


def timeshift_url(source, sid, label, minutes):
    """Xtream catch-up link. `label` is the programme start in the server's own time ("YYYY-MM-DD HH:MM:SS")."""
    text = str(label).replace("T", " ")
    stamp = f"{text[:10]}:{text[11:16].replace(':', '-')}"
    credentials = "/".join(quote(source[key], safe="") for key in ("user", "password"))
    return f"{server_base(source)}/timeshift/{credentials}/{max(1, int(minutes))}/{stamp}/{quote(str(sid), safe='')}.ts"


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(secrets.token_hex(8) + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)



ACTIVITY = STATE.with_name("activity.json")

AUTH = "{zono-auth}"
NOTICE = ""


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    """Encrypt/decrypt bytes for the current Windows user. Returns None when unavailable."""
    if not hasattr(ctypes, "windll"):
        return None
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    crypt = ctypes.windll.crypt32
    call = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):
        return None
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def _segment(source):
    return "/" + "/".join(quote(str(source.get(key, "")), safe="") for key in ("user", "password")) + "/"


def _replace(value, old, new):
    """Swap `old` for `new` in every string inside `value`. Only copies what changes (fast on big libraries)."""
    kind = type(value)
    if kind is str:
        return value.replace(old, new) if old in value else value
    if kind is list:
        changed = None
        for index, item in enumerate(value):
            result = _replace(item, old, new)
            if result is not item:
                if changed is None:
                    changed = list(value)
                changed[index] = result
        return value if changed is None else changed
    if kind is dict:
        changed = None
        for key, item in value.items():
            t = type(item)
            if t is str:
                if old not in item:
                    continue
            elif t is not list and t is not dict:
                continue
            result = _replace(item, old, new)
            if result is not item:
                if changed is None:
                    changed = dict(value)
                changed[key] = result
        return value if changed is None else changed
    return value


def seal(value, source):
    """Remove the Xtream credentials from every stored stream link."""
    if not source or not source.get("password"):
        return value
    return _replace(value, _segment(source), "/" + AUTH + "/")


def unseal(value, source):
    if not source or not source.get("password"):
        return value
    return _replace(value, "/" + AUTH + "/", _segment(source))


def stored_source(source):
    if not source:
        return source
    secret = _dpapi(str(source.get("password", "")).encode("utf-8"), True)
    if secret is None:
        return dict(source)
    stored = {k: v for k, v in source.items() if k != "password"}
    stored["password_dpapi"] = b64encode(secret).decode("ascii")
    return stored


def restore_source(stored):
    if not stored or "password_dpapi" not in stored:
        return stored
    secret = _dpapi(b64decode(stored["password_dpapi"]), False)
    if secret is None:
        raise ValueError(T("Je opgeslagen wachtwoord kon niet worden ontsleuteld."))
    source = {k: v for k, v in stored.items() if k != "password_dpapi"}
    source["password"] = secret.decode("utf-8")
    return source


def needs_protection(state):
    source = state.get("source")
    return bool(source and source.get("password") and hasattr(ctypes, "windll") and not state.get("protected"))


def save_state(state):
    source = state.get("source")
    stored = dict(state, library=seal(state.get("library", []), source), source=stored_source(source))
    for key in ("favorites", "progress"):
        if key in stored:
            stored[key] = seal(stored[key], source)
    stored.pop("protected", None)
    write_json(STATE, stored)
    state["protected"] = True


def save_activity(state, favorites, progress):
    source = state.get("source")
    write_json(ACTIVITY, {"revision": state.get("revision"), "favorites": seal(favorites, source),
                          "progress": seal(progress, source)})


def profile_folder(profile):
    folder = str(profile.get("folder") or "")
    return ROOT / "profiles" / folder if folder else ROOT


def use_profile(profile):
    global STATE, ACTIVITY, NOTICE
    folder = profile_folder(profile)
    STATE = folder / "library.json"
    ACTIVITY = folder / "activity.json"
    NOTICE = ""


def load_profiles():
    stored = read_json(PROFILES, None)
    if isinstance(stored, dict) and isinstance(stored.get("profiles"), list) and stored["profiles"]:
        return stored
    name = (os.environ.get("USERNAME") or os.environ.get("USER") or "Profiel 1").strip().capitalize()
    return {"profiles": [{"id": "main", "name": name or "Profiel 1", "color": 0, "folder": "", "kids": False}],
            "last": "main"}


def save_profiles(profiles):
    write_json(PROFILES, profiles)


def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.sha256((salt + str(pin)).encode("utf-8")).hexdigest()


def check_pin(stored, pin):
    if not stored or "$" not in stored:
        return False
    return hmac.compare_digest(hash_pin(pin, stored.split("$", 1)[0]), stored)


def copy_provider(source_profile, target_profile):
    """Give a new profile the same library and provider as an existing one."""
    source = profile_folder(source_profile) / "library.json"
    if not source.exists():
        return
    target = profile_folder(target_profile)
    target.mkdir(parents=True, exist_ok=True)
    stored = json.loads(source.read_text(encoding="utf-8"))
    stored.pop("favorites", None)
    stored.pop("progress", None)
    write_json(target / "library.json", stored)


def delete_profile(profile):
    folder = profile_folder(profile)
    if folder == ROOT:
        for name in ("library.json", "activity.json", "preferences.json", "downloads.json"):
            (ROOT / name).unlink(missing_ok=True)
    else:
        shutil.rmtree(folder, ignore_errors=True)


def log_note(text):
    """A notice (not a crash) in the log, so a support question can be answered from it."""
    from datetime import datetime
    log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Melding: {text}")


def log_error(text):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 2_000_000:
            LOG.unlink()
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n\n")
    except OSError:
        pass


def load():
    global NOTICE
    path = STATE if STATE.exists() else (LEGACY if STATE.parent == ROOT else STATE)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stored = state.get("source")
    protected = bool(stored and "password_dpapi" in stored)
    try:
        source = restore_source(stored)
    except ValueError:
        NOTICE = T("Je opgeslagen providergegevens konden op deze computer niet worden gelezen. Koppel je provider opnieuw.")
        return {}
    state["source"] = source
    for key in ("library", "favorites", "progress"):
        if key in state:
            state[key] = unseal(state[key], source)
    state["protected"] = protected
    if ACTIVITY.exists():
        activity = json.loads(ACTIVITY.read_text(encoding="utf-8"))
        if activity.get("revision") == state.get("revision"):
            state.update(favorites=unseal(activity.get("favorites", {}), source),
                         progress=unseal(activity.get("progress", {}), source))
    return state

def details(source, item):
    if item["kind"] == "series":
        response = xtream(source, "get_series_info", series_id=item["sid"])
        return response.get("info") or {}, episode_rows(source, response)
    if item["kind"] == "movie":
        response = xtream(source, "get_vod_info", vod_id=item["sid"])
        return response.get("info") or {}, []
    return {}, []

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

class Cancelled(Exception):
    pass


def download(url, path, progress=None, cancel=None):
    """Save a video file. `progress(done, total)` is called from this worker thread; `cancel` is a threading.Event."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".part")
    try:
        request = Request(check_url(url), headers={"User-Agent": "VLC/3.0 LibVLC/3.0"})
        with urlopen(request, timeout=30) as response, temp.open("wb") as output:
            kind = response.headers.get_content_type()
            if kind.startswith("text/") or "mpegurl" in kind or kind == "application/json":
                raise ValueError(T("De provider stuurde geen videobestand."))
            expected = response.headers.get("Content-Length")
            total = int(expected) if expected and expected.isdecimal() else 0
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = response.read(512 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
            if not done or (total and done != total):
                raise ValueError(T("De download is onvolledig."))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
