"""Optional extra information from The Movie Database (needs a free API key from themoviedb.org)."""
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/"


def _get(key, path, **query):
    query["api_key"] = key
    query.setdefault("language", "nl-NL")
    request = Request(f"{API}{path}?{urlencode(query)}", headers={"User-Agent": "Zono", "Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))


def clean_title(title):
    """IPTV titles often carry prefixes and tags like "NL - Title (2019) [4K]"."""
    text = re.sub(r"^\s*[A-Z]{2,3}\s*[-|:]\s*", "", str(title))
    text = re.sub(r"[\[(][^\])]*[\])]", " ", text)
    text = re.sub(r"\b(4K|UHD|FHD|HD|SD|MULTI|SUB|NL|VOSTFR)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -|:")


def year_of(title, fallback=""):
    match = re.search(r"\b(19[2-9]\d|20[0-4]\d)\b", str(title))
    return match.group(1) if match else str(fallback)[:4]


def lookup(key, title, kind, year="", tmdb_id=None):
    """Return (tmdb id, media type) or (None, None)."""
    media = "tv" if kind == "series" else "movie"
    if tmdb_id and str(tmdb_id).isdigit() and int(tmdb_id) > 0:
        return int(tmdb_id), media
    query = clean_title(title)
    if not query:
        return None, None
    params = {"query": query}
    if year:
        params["year" if media == "movie" else "first_air_date_year"] = year
    results = _get(key, f"/search/{media}", **params).get("results") or []
    if not results and year:
        results = _get(key, f"/search/{media}", query=query).get("results") or []
    return (results[0]["id"], media) if results else (None, None)


def extras(key, title, kind, year="", tmdb_id=None):
    """Cast with photos, a YouTube trailer key and titles of similar works."""
    found, media = lookup(key, title, kind, year, tmdb_id)
    if not found:
        return {}
    detail = _get(key, f"/{media}/{found}", append_to_response="credits,videos,recommendations",
                  include_video_language="nl,en,null")
    cast = []
    for person in (detail.get("credits") or {}).get("cast", [])[:14]:
        cast.append({"name": person.get("name", ""), "role": person.get("character", ""),
                     "photo": IMAGES + "w185" + person["profile_path"] if person.get("profile_path") else ""})
    trailer = ""
    for video in (detail.get("videos") or {}).get("results", []):
        if video.get("site") == "YouTube" and video.get("type") in ("Trailer", "Teaser"):
            trailer = video.get("key", "")
            break
    similar = [r.get("title") or r.get("name") or "" for r in (detail.get("recommendations") or {}).get("results", [])[:30]]
    backdrop = IMAGES + "w1280" + detail["backdrop_path"] if detail.get("backdrop_path") else ""
    genres = [g.get("name", "") for g in detail.get("genres") or []]
    return {"cast": cast, "trailer": trailer, "similar": similar, "backdrop": backdrop, "genres": genres,
            "overview": detail.get("overview") or ""}


def art(key, title, kind, year="", tmdb_id=None):
    """(poster link, wide backdrop link) from TMDB, or ("", "")."""
    media = "tv" if kind == "series" else "movie"
    if tmdb_id and str(tmdb_id).isdigit() and int(tmdb_id) > 0:
        found = _get(key, f"/{media}/{int(tmdb_id)}")
    else:
        query = clean_title(title)
        if not query:
            return "", ""
        params = {"query": query}
        if year:
            params["year" if media == "movie" else "first_air_date_year"] = year
        results = _get(key, f"/search/{media}", **params).get("results") or []
        if not results and year:
            results = _get(key, f"/search/{media}", query=query).get("results") or []
        if not results:
            return "", ""
        found = results[0]
    poster = IMAGES + "w500" + found["poster_path"] if found.get("poster_path") else ""
    wide = IMAGES + "w1280" + found["backdrop_path"] if found.get("backdrop_path") else ""
    return poster, wide


def check_key(key):
    _get(key, "/configuration")
    return True
