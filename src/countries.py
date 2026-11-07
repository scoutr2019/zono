"""Recognise the country or language of IPTV channels, categories and titles.

Providers label things in many ways: "BE | VTM", "NL: NPO 1", "|FR| TF1", "[UK] Sky", a category called
"BELGIË" or "Vlaamse films", or just a well-known channel name ("VRT 1"). Zono uses this to put the
countries a viewer chooses first, or to hide the rest.
"""
import re
from functools import lru_cache

# code: (Dutch name, words that point to it)
COUNTRIES = {
    "BE": ("België", ("BELGI", "BELGIQUE", "VLAAMS", "VLAANDEREN", "FLEMISH", "WALLONIE")),
    "NL": ("Nederland", ("NEDERLAND", "NETHERLANDS", "HOLLAND", "DUTCH", "NEDERLANDS")),
    "FR": ("Frankrijk / Frans", ("FRANCE", "FRANKRIJK", "FRENCH", "FRANCAIS", "FRANÇAIS")),
    "DE": ("Duitsland / Duits", ("GERMANY", "DEUTSCH", "DUITS", "GERMAN")),
    "UK": ("Verenigd Koninkrijk", ("UNITED KINGDOM", "BRITISH", "ENGLAND")),
    "US": ("Verenigde Staten", ("USA", "UNITED STATES", "AMERICA")),
    "EN": ("Engels", ("ENGLISH", "ENGELS")),
    "ES": ("Spanje / Spaans", ("SPAIN", "ESPANA", "ESPAÑA", "SPANISH", "SPAANS")),
    "IT": ("Italië / Italiaans", ("ITALY", "ITALIA", "ITALIAN")),
    "PT": ("Portugal", ("PORTUGAL", "PORTUGUES")),
    "BR": ("Brazilië", ("BRASIL", "BRAZIL")),
    "TR": ("Turkije / Turks", ("TURKEY", "TURKIYE", "TÜRKIYE", "TURKISH", "TURKS")),
    "PL": ("Polen / Pools", ("POLAND", "POLSKA", "POLISH")),
    "AR": ("Arabisch", ("ARABIC", "ARAB", "ARABISCH")),
    "MA": ("Marokko", ("MAROC", "MOROCCO", "MAROKKO")),
    "DZ": ("Algerije", ("ALGERIE", "ALGERIA")),
    "TN": ("Tunesië", ("TUNISIE", "TUNISIA")),
    "IN": ("India", ("INDIA", "HINDI", "INDIAN")),
    "PK": ("Pakistan", ("PAKISTAN", "URDU")),
    "AL": ("Albanië", ("ALBANIA", "SHQIP")),
    "RO": ("Roemenië", ("ROMANIA",)),
    "RU": ("Rusland / Russisch", ("RUSSIA", "RUSSIAN")),
    "GR": ("Griekenland", ("GREECE", "GREEK", "HELLAS")),
    "SE": ("Zweden", ("SWEDEN", "SVERIGE")),
    "DK": ("Denemarken", ("DENMARK", "DANMARK")),
    "NO": ("Noorwegen", ("NORWAY", "NORGE")),
    "FI": ("Finland", ("FINLAND", "SUOMI")),
    "CH": ("Zwitserland", ("SWITZERLAND", "SCHWEIZ", "SUISSE")),
    "AT": ("Oostenrijk", ("AUSTRIA", "ÖSTERREICH", "OSTERREICH")),
    "IE": ("Ierland", ("IRELAND",)),
    "CA": ("Canada", ("CANADA",)),
    "AU": ("Australië", ("AUSTRALIA",)),
    "MX": ("Mexico", ("MEXICO",)),
    "LAT": ("Latijns-Amerika", ("LATINO", "LATIN")),
    "AFR": ("Afrika", ("AFRICA", "AFRIQUE")),
    "EXYU": ("Ex-Joegoslavië", ("EX-YU", "EXYU", "BALKAN")),
    "CZ": ("Tsjechië", ("CZECH",)),
    "HU": ("Hongarije", ("HUNGARY", "MAGYAR")),
    "BG": ("Bulgarije", ("BULGARIA",)),
    "KU": ("Koerdisch", ("KURD",)),
    "IR": ("Iran / Perzisch", ("IRAN", "PERSIAN", "FARSI")),
    "CN": ("China", ("CHINA", "CHINESE")),
    "PH": ("Filipijnen", ("PHILIPPINES", "FILIPINO")),
}
ALIASES = {"GB": "UK", "ENG": "EN", "VL": "BE", "FL": "BE", "BEL": "BE", "NED": "NL", "FRA": "FR", "GER": "DE",
           "ITA": "IT", "ESP": "ES", "TUR": "TR", "POL": "PL", "ARA": "AR", "USA": "US", "YU": "EXYU", "LA": "LAT",
           "PER": "IR", "FA": "IR"}
# well-known channel names, for providers that do not label countries
BRANDS = {
    "BE": ("VRT", "VTM", "EEN", "CANVAS", "KETNET", "PLAY4", "PLAY 4", "PLAY5", "PLAY 5", "PLAY6", "PLAY 6",
           "PLAY7", "PLAY 7", "PLAY SPORTS", "VIER", "VIJF", "ZES", "RTBF", "LA UNE", "TIPIK", "RTL-TVI", "RTL TVI",
           "CLUB RTL", "PLUG RTL", "CAZ", "KANAAL Z", "LN24", "ATV", "ROB-TV", "TV OOST", "FOCUS-WTV", "NOTELE",
           "ELEVEN PRO", "ELEVEN SPORTS BE", "DOBBIT", "ACTUA TV", "TVL", "BRUZZ", "RINGTV"),
    "NL": ("NPO", "RTL 4", "RTL4", "RTL 5", "RTL5", "RTL 7", "RTL7", "RTL 8", "RTL8", "RTL Z", "SBS6", "SBS 6",
           "SBS9", "NET5", "NET 5", "VERONICA", "ZIGGO", "VIDEOLAND", "AT5", "OMROEP", "TV WEST", "RTV ", "ESPN NL"),
    "FR": ("TF1", "FRANCE 2", "FRANCE 3", "FRANCE 5", "M6", "CANAL+", "ARTE FR", "BFM", "TMC"),
    "DE": ("ARD", "ZDF", "PRO7", "PROSIEBEN", "SAT.1", "SAT1", "RTL2", "VOX", "KABEL 1", "KABEL EINS"),
    "UK": ("BBC", "ITV", "SKY ", "CHANNEL 4", "CHANNEL 5"),
}
SKIP = {"HD", "FHD", "UHD", "SD", "4K", "8K", "VIP", "ALL", "MULTI", "VOD", "TV", "NEW", "TOP", "PPV", "LIVE",
        "24/7", "247", "XXX", "HEVC", "H265", "RAW", "SUB", "DUB"}

_LABEL = re.compile(r"(?:^|[\[\(|])\s*([A-Z]{2,4})\s*(?:[\]\)|:]|\s[-–»|]\s?|\s*$)")
_cache = {}


def _code(token):
    token = token.upper().replace("-", "")
    token = ALIASES.get(token, token)
    return token if token in COUNTRIES and token not in SKIP else ""


def detect_text(text, brands=False, words=True):
    """Country code for a group name or title, or "" when it cannot be told."""
    if not text:
        return ""
    upper = str(text).upper()
    key = (upper, brands, words)
    if key in _cache:
        return _cache[key]
    found = ""
    for match in _LABEL.finditer(upper[:40]):
        found = _code(match.group(1))
        if found:
            break
    if not found and words:
        for code, (_, keys) in COUNTRIES.items():
            if any(word in upper for word in keys):
                found = code
                break
    if not found and brands:
        padded = f" {upper} "
        for code, names in BRANDS.items():
            if any(re.search(rf"(?<![A-Z0-9]){re.escape(name.strip())}(?![A-Z0-9])", padded) for name in names):
                found = code
                break
    if len(_cache) > 50000:
        _cache.clear()
    _cache[key] = found
    return found


def detect(item):
    """Country of a library item: from its category first, then its title, then (channels) its name."""
    if "cc" in item:
        return item["cc"]
    group = str(item.get("group") or "")
    title = str(item.get("raw_title") or item.get("title") or "")
    return detect_text(group) or detect_text(title, brands=item.get("kind") == "live", words=False)


def name(code):
    return COUNTRIES.get(code, (code,))[0]


_PREFIX = re.compile(r"^\s*(?:[\[\(|]?\s*(?:[A-Z]{2,4}|4K|8K|UHD|FHD|HD|SD|VIP|HEVC|ᴴᴰ|ᵁᴴᴰ)\s*[\]\)|:]\s*|"
                     r"(?:[A-Z]{2,4}|4K|8K|UHD|FHD|HD|SD|VIP|HEVC)\s+[-–»|]\s+)", re.I)
_TAIL_WORDS = {"4K", "8K", "UHD", "FHD", "HD", "SD", "HEVC", "H265", "H.265", "50FPS", "60FPS", "RAW", "BACKUP",
               "720P", "1080P", "2160P", "1080I", "ᴴᴰ", "ᵁᴴᴰ", "ᶠᴴᴰ", "ᴴᴰ⁺", "+HD", "HD+", "FHD+", "MULTI", "VIP"}
_DECOR = re.compile(r"[◉●○◆◇♦★☆✦✪▶►◀◄■□▪▫•|#=*~_]+")


def is_separator(title):
    """Lines like "♦♦♦ WELCOME ♦♦♦" or "##### BELGIË #####" that providers put between channel groups."""
    text = str(title).strip()
    symbols = len(_DECOR.findall(text)) and sum(len(m) for m in _DECOR.findall(text))
    letters = re.sub(r"[^\w]", "", text)
    return bool(symbols and symbols >= 3 and (len(letters) <= 24) and _DECOR.match(text) is not None)


_SUPERSCRIPT = re.compile(r"[\u02b0-\u02ff\u1d2c-\u1d6a\u1d9b-\u1dbf\u2070-\u209f\u00b2\u00b3\u00b9]+")
_QUALITY_START = re.compile(r"^\s*(?:\d{1,2}K|UHD|FHD|HD|SD|VIP|HEVC)\s+(?=\S)", re.I)
_VOD_PREFIX = re.compile(r"^\s*(?:\[[^\]]{1,8}\]|\((?:[A-Z]{2,4}|ALL|MULTI)\)|\|[A-Z]{2,4}\||[A-Z]{2,3}\s*[|:]|"
                         r"[A-Z]{2,3}\s+-\s+)\s*")


@lru_cache(maxsize=200000)
def clean_title(title):
    """Films and series: "[ALL] The Birthday Gift (2025)" -> "The Birthday Gift (2025)", "[TR] Uzak Şehir" -> "Uzak Şehir"."""
    text = str(title).strip()
    for _ in range(3):
        stripped = _VOD_PREFIX.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = _SUPERSCRIPT.sub("", text).strip(" -|:")
    # the year is shown next to the title already ("2026 · Mystery"), like Netflix
    without_year = re.sub(r"\s*[\(\[](?:19|20)\d{2}[\)\]]\s*$", "", text).strip()
    if len(without_year) >= 2:
        text = without_year
    return text if len(text) >= 2 else str(title)


@lru_cache(maxsize=200000)
def clean_name(title):
    """ "4K | VRT 1 HD" -> "VRT 1", "BE: VTM 2 FHD" -> "VTM 2" (keeps the name when cleaning would empty it)."""
    text = _SUPERSCRIPT.sub(" ", str(title)).strip()
    original = str(title).strip()
    for _ in range(3):
        stripped = _QUALITY_START.sub("", _PREFIX.sub("", text, count=1), count=1)
        if stripped == text:
            break
        text = stripped
    words = text.split()
    while len(words) > 1:
        last = words[-1].strip("()[]").upper()
        if last in _TAIL_WORDS or (re.fullmatch(r"[\(\[][A-Z]{2,3}[\)\]]", words[-1]) is not None):
            words.pop()
        else:
            break
    text = " ".join(words)
    text = re.sub(r"\s{2,}", " ", _DECOR.sub(" ", text)).strip(" -–|:")
    return text if len(text) >= 2 else original


_EPISODE_CODE = re.compile(r"\bS(\d{1,2})\s*[ .x]?\s*E(\d{1,3})\b", re.I)
_GENERIC = re.compile(r"^(?:episode|aflevering|afl\.?|ep\.?|bölüm|capitulo|capítulo|folge|épisode)\s*\d+$", re.I)


@lru_cache(maxsize=50000)
def clean_episode(title, number=0):
    """ "[ALL] Dead-End Job (2026) - S01E01 - Convenience Store Rules" -> "Convenience Store Rules";
    "… - S01E02 - Episode 2" -> "Aflevering 2"."""
    text = str(title).strip()
    match = _EPISODE_CODE.search(text)
    if match:
        number = number or int(match.group(2))
        text = text[match.end():].strip(" -–:|.")
    else:
        text = clean_title(text)
    counted = re.search(r"(\d+)\.?\s*(?:bölüm|folge|episode|aflevering|capitulo|capítulo)$", text, re.I)
    if counted and len(text) - len(counted.group(0)) > 0:
        return f"Aflevering {int(counted.group(1))}"
    if not text or _GENERIC.match(text) or text.isdigit():
        return f"Aflevering {number}" if number else (clean_title(title) or str(title))
    return text
