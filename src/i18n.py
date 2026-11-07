"""Zono in four languages: Nederlands (the source text), Français, English and Deutsch.

Every text on screen is written in Dutch in the code and passed through `T()`. The translations live in
`locale/<code>.json` as {"Dutch text": "translation"}. Texts with values use `{}` placeholders:
`T("Alle {} resultaten bekijken").format(count)`.

The language is chosen once at start (it is stored in %LOCALAPPDATA%\\Zono\\language.json); the first time,
Zono follows the Windows display language. Changing the language restarts Zono.
"""
import json
import locale
import os
import re
from pathlib import Path

LANGUAGES = {"nl": "Nederlands", "fr": "Français", "en": "English", "de": "Deutsch"}
FOLDER = Path(__file__).with_name("locale")
SETTING = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Zono" / "language.json"


def system_language():
    """nl/fr/de when Windows (or the system) is set to one of those, otherwise English."""
    code = ""
    try:
        import ctypes
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        code = locale.windows_locale.get(lcid, "")
    except (AttributeError, OSError):
        code = os.environ.get("LANG", "") or (locale.getlocale()[0] or "")
    code = code[:2].lower()
    return code if code in LANGUAGES else "en"


def stored_language():
    try:
        code = json.loads(SETTING.read_text(encoding="utf-8")).get("language", "")
    except (OSError, ValueError, AttributeError):
        code = ""
    return code if code in LANGUAGES else ""


def load(code):
    if code == "nl":
        return {}
    try:
        table = json.loads((FOLDER / f"{code}.json").read_text(encoding="utf-8"))
        return {k: v for k, v in table.items() if isinstance(v, str) and v}
    except (OSError, ValueError):
        return {}


CODE = os.environ.get("ZONO_LANGUAGE", "") or stored_language() or system_language()
if CODE not in LANGUAGES:
    CODE = "nl"
_TABLE = load(CODE)


def T(text):
    """The text in the chosen language (the Dutch text itself when there is no translation).

    "Afspelen||instellingen": the part after || only tells translators which meaning is meant."""
    found = _TABLE.get(text)
    if found is not None:
        return found
    return text.split("||", 1)[0] if "||" in text else text


def save_language(code):
    if code not in LANGUAGES:
        raise ValueError(code)
    SETTING.parent.mkdir(parents=True, exist_ok=True)
    SETTING.write_text(json.dumps({"language": code}), encoding="utf-8")


# Names that come from the provider data but are made by Zono: "Seizoen 2", "Aflevering 5", "Overige".
_SEASON = re.compile(r"^Seizoen (\d+)$")
_EPISODE = re.compile(r"^Aflevering (\d+)$")


def shown(text):
    """Translate the few Dutch words Zono puts into provider data, at the moment they are shown."""
    if CODE == "nl" or not isinstance(text, str):
        return text
    if text == "Overige":
        return T("Overige")
    match = _SEASON.match(text) or _EPISODE.match(text)
    if match:
        return T(text[:match.start(1)].strip() + " {}").format(match.group(1))
    return text
