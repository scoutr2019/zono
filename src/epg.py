"""TV guide from an XMLTV file: for M3U playlists (which have no guide of their own) and for searching programmes.

Where the XMLTV comes from:
- an M3U playlist's own header: #EXTM3U url-tvg="..." (or x-tvg-url),
- a link the user types in when connecting the playlist,
- for Xtream Codes providers: <server>/xmltv.php?username=...&password=... (used for searching).

The file is downloaded at most every few hours and kept on disk; only programmes from two days ago up to four days
ahead are kept in memory.
"""
import gzip
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from pathlib import Path
from urllib.request import Request, urlopen

LIMIT = 400 * 1024 * 1024  # bigger guides are not downloaded
MAX_PROGRAMS = 400_000  # about 100 MB of memory at most
MAX_AGE = 6 * 3600
_STAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-]\d{4})?")


def parse_time(text):
    """ "20261109150000 +0100" -> unix time (UTC). None when unreadable."""
    match = _STAMP.match(str(text or "").strip())
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    stamp = timegm((int(year), int(month), int(day), int(hour), int(minute), int(second or 0)))
    if zone:
        sign = -1 if zone[0] == "-" else 1
        stamp -= sign * (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60)
    return stamp


def key_name(name):
    """Channel names compared loosely: "NPO 1 HD" ~ "npo1"."""
    text = re.sub(r"\b(hd|fhd|uhd|4k|sd|hevc|backup)\b", "", str(name or "").casefold())
    return re.sub(r"[^\w]", "", text)


class Guide:
    """Programmes per XMLTV channel id, plus display names to find channels without a tvg-id."""

    def __init__(self):
        self.programs = {}  # channel id -> [(start, end, title, description)], sorted by start
        self.names = {}  # key_name(display name) -> channel id

    def __len__(self):
        return sum(len(rows) for rows in self.programs.values())

    @classmethod
    def read(cls, handle, now=None, before=2 * 86400, after=4 * 86400, keep=None, limit=MAX_PROGRAMS):
        """`keep`: only these channel ids (the library's channels); `limit`: at most this many programmes, so a
        huge guide cannot fill the memory. Reading pauses briefly now and then so the screen stays smooth."""
        guide = cls()
        now = time.time() if now is None else now
        low, high = now - before, now + after
        count = 0
        for index, (_, element) in enumerate(ET.iterparse(handle, events=("end",))):
            if index % 4000 == 3999:
                time.sleep(0.003)  # let the screen thread run
            tag = element.tag
            if tag == "programme":
                start, end = parse_time(element.get("start")), parse_time(element.get("stop"))
                channel = element.get("channel")
                if channel and start and end and end > low and start < high and count < limit \
                        and (keep is None or channel in keep):
                    count += 1
                    title = (element.findtext("title") or "").strip()
                    description = (element.findtext("desc") or "").strip()[:240]
                    guide.programs.setdefault(channel, []).append((start, end, title, description))
                element.clear()
            elif tag == "channel":
                channel = element.get("id")
                for name in element.findall("display-name"):
                    if channel and name.text:
                        guide.names.setdefault(key_name(name.text), channel)
                if channel:
                    guide.names.setdefault(key_name(channel), channel)
                element.clear()
        for rows in guide.programs.values():
            rows.sort()
        return guide

    @classmethod
    def load(cls, path, now=None, keep=None):
        path = Path(path)
        with path.open("rb") as raw:
            packed = raw.read(2) == b"\x1f\x8b"
        opener = gzip.open if packed else open
        with opener(path, "rb") as handle:
            return cls.read(handle, now, keep=keep)

    def channel_for(self, item):
        """The XMLTV channel id of a channel in the library (tvg-id first, then by name)."""
        for value in (item.get("epg"),):
            if value and value in self.programs:
                return value
        for value in (item.get("epg"), item.get("tvg_name"), item.get("raw_title"), item.get("title")):
            found = self.names.get(key_name(value)) if value else None
            if found and found in self.programs:
                return found
        return None

    def rows(self, item):
        channel = self.channel_for(item)
        return [{"title": title, "start": start, "end": end, "label": "", "description": description}
                for start, end, title, description in self.programs.get(channel, [])] if channel else []

    def search(self, query, channels, now=None, limit=40, ahead=2 * 86400):
        """Programmes whose title contains `query`, now or later (up to `ahead`), on the given library channels.
        Returns [(channel item, row)] sorted by start time."""
        words = [w for w in str(query or "").casefold().split() if w]
        if not words:
            return []
        now = time.time() if now is None else now
        found, seen = [], set()
        for item in channels:
            channel = self.channel_for(item)
            if not channel or channel in seen:
                continue
            seen.add(channel)
            for start, end, title, description in self.programs.get(channel, []):
                if end <= now or start > now + ahead:
                    continue
                text = title.casefold()
                if all(w in text for w in words):
                    found.append((item, {"title": title, "start": start, "end": end, "label": "",
                                         "description": description}))
        found.sort(key=lambda pair: (pair[1]["start"], pair[0].get("title", "")))
        return found[:limit]


def m3u_guide_url(raw):
    """The guide link in a playlist's first line: #EXTM3U url-tvg="..." / x-tvg-url="..." (first of a list)."""
    for line in str(raw or "").splitlines()[:5]:
        if line.startswith("#EXTM3U"):
            match = re.search(r'(?:url-tvg|x-tvg-url|tvg-url)="([^"]+)"', line)
            if match:
                first = match.group(1).split(",")[0].strip()
                return first if first.startswith(("http://", "https://")) else ""
    return ""


def cached_path(folder, url):
    return Path(folder) / ("guide-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".xml")


def download(url, folder, max_age=MAX_AGE, opener=urlopen):
    """The guide file on disk, downloaded again when older than `max_age`."""
    path = cached_path(folder, url)
    if path.is_file() and time.time() - path.stat().st_mtime < max_age:
        return path
    Path(folder).mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    request = Request(url, headers={"User-Agent": "VLC/3.0 LibVLC/3.0", "Accept-Encoding": "identity"})
    received = 0
    with opener(request, timeout=60) as response, part.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > LIMIT:
                raise ValueError("de gids is te groot")
            output.write(chunk)
    if received < 100:
        part.unlink(missing_ok=True)
        raise ValueError("de gids is leeg")
    part.replace(path)
    return path
