"""Talking to zono.be: anonymous daily usage statistics (can be switched off) and "Probleem melden".

What the statistics send, once a day: a random number made on this PC (not linked to a person or account), the
Zono version, the app language and the Windows version. Never: the provider, what is watched, channels, passwords
or the computer's name. See https://zono.be/privacy.html.
"""
import json
import os
import platform
import re
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from i18n import T

API = "https://zono.be/api"
ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Zono"
SETTINGS = ROOT / "install.json"


def settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**values):
    state = settings()
    state.update(values)
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return state


def install_id():
    state = settings()
    value = str(state.get("id") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        value = uuid.uuid4().hex
        save(id=value)
    return value


def sharing():
    return settings().get("share", True) is not False


def set_sharing(on):
    save(share=bool(on))


def windows_version():
    try:
        release, build = platform.release(), platform.version()
        number = int(build.split(".")[-1]) if build else 0
        name = "Windows 11" if release == "10" and number >= 22000 else f"Windows {release}"
        return f"{name} ({build})"[:40]
    except (ValueError, OSError):
        return "Windows"


def _post(path, body, opener=urlopen, timeout=15):
    request = Request(f"{API}/{path}", data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "User-Agent": "Zono"})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read(65536).decode("utf-8") or "{}")


def ping(version, language, opener=urlopen, now=None):
    """Once a day, when sharing is on. Returns True when a ping was sent."""
    if not sharing():
        return False
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if settings().get("pinged") == day:
        return False
    _post("ping.php", {"id": install_id(), "version": version, "language": language, "windows": windows_version()},
          opener=opener)
    save(pinged=day)
    return True


_SECRETS = [
    (re.compile(r"(/(?:live|movie|series|timeshift)/)[^/\s]+/[^/\s]+/", re.I), r"\1***/***/"),
    (re.compile(r"((?:username|password|user|pass)=)[^&\s'\"]+", re.I), r"\1***"),
    (re.compile(r"([A-Za-z]:\\Users\\)[^\\\s]+", re.I), r"\1***"),
    (re.compile(r"(/home/|/Users/)[^/\s]+"), r"\1***"),
]


def clean_log(text, limit=200_000):
    """The log without provider logins or the Windows user name; the newest part when it is long."""
    text = str(text or "")[-limit:]
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def report(version, language, message, contact="", log="", opener=urlopen):
    """Send a problem report to support. Returns the report number."""
    try:
        answer = _post("report.php", {"version": version, "language": language, "windows": windows_version(),
                                      "message": str(message or "")[:4000], "contact": str(contact or "")[:200],
                                      "log": clean_log(log)}, opener=opener, timeout=25)
    except HTTPError as error:
        if error.code == 429:
            raise ValueError(T("Je hebt al veel meldingen verstuurd. Probeer het over een uur opnieuw.")) from error
        raise ValueError(T("zono.be antwoordde met HTTP {}").format(error.code)) from error
    if not answer.get("ok"):
        raise ValueError(answer.get("error") or "geen antwoord")
    return int(answer.get("number") or 0)
