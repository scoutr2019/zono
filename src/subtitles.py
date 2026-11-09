"""Subtitles from OpenSubtitles.com (free API key; without an account about 5 downloads a day).

    found = search(key, "The Matrix", "nl", year="1999")          # films
    found = search(key, "Thuis", "nl", season=30, episode=12)      # episodes
    path = download(key, found[0], folder)                         # -> .srt on disk, loaded into the player
"""
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.opensubtitles.com/api/v1"
AGENT = "Zono v2.4"


class LimitReached(Exception):
    """OpenSubtitles allows only a few downloads a day without an account."""


def _call(key, path, query=None, body=None, opener=urlopen):
    url = f"{API}{path}" + (f"?{urlencode(query)}" if query else "")
    headers = {"Api-Key": key, "User-Agent": AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        with opener(Request(url, data=data, headers=headers, method="POST" if data else "GET"), timeout=15) as response:
            return json.loads(response.read(4_000_000).decode("utf-8"))
    except HTTPError as error:
        if error.code in (406, 429):
            raise LimitReached(str(error)) from error
        raise


def clean_query(title):
    """Search text from an IPTV title: no "[ALL]", country prefix, year or quality marks."""
    text = re.sub(r"^\s*(?:\[[^\]]{1,8}\]\s*)?(?:[A-Z]{2,3}\s*[-|:]\s*)?", "", str(title or ""))
    text = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text)
    text = re.sub(r"\b(4K|UHD|FHD|HD|SD|MULTI|SUB|HEVC|x26[45])\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -|:")


def search(key, title, language, year="", season=None, episode=None, tmdb_id=None, opener=urlopen):
    """Up to 10 results, most downloaded first: [{file_id, name, language, downloads}]."""
    query = {"languages": language, "order_by": "download_count", "order_direction": "desc"}
    if tmdb_id and str(tmdb_id).isdigit():
        query["parent_tmdb_id" if season else "tmdb_id"] = int(tmdb_id)
    else:
        query["query"] = clean_query(title)
        if year and not season:
            query["year"] = str(year)[:4]
    if season:
        query["season_number"], query["episode_number"] = int(season), int(episode or 1)
    answer = _call(key, "/subtitles", dict(sorted(query.items())), opener=opener)
    found = []
    for row in answer.get("data") or []:
        attributes = row.get("attributes") or {}
        files = attributes.get("files") or []
        if not files or not files[0].get("file_id"):
            continue
        found.append({"file_id": int(files[0]["file_id"]),
                      "name": attributes.get("release") or files[0].get("file_name") or "",
                      "language": attributes.get("language") or language,
                      "downloads": int(attributes.get("download_count") or 0)})
    return found[:10]


def download(key, result, folder, opener=urlopen):
    """Download one result as .srt into `folder`; returns the file path."""
    answer = _call(key, "/download", body={"file_id": result["file_id"], "sub_format": "srt"}, opener=opener)
    link = answer.get("link")
    if not link or not str(link).startswith("https://"):
        raise ValueError(answer.get("message") or "geen downloadlink")
    with opener(Request(link, headers={"User-Agent": AGENT}), timeout=20) as response:
        raw = response.read(5_000_000)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]+", "_", f"{result['file_id']}-{result.get('language', '')}")[:60] + ".srt"
    path = folder / name
    path.write_bytes(raw)
    return path


def episode_numbers(title):
    """(season, episode) from "Show - S02E05 - Name", else (None, None)."""
    match = re.search(r"\bS(\d{1,2})\s*[ .x]?\s*E(\d{1,3})\b", str(title or ""), re.I)
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)
