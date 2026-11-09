"""Automatic updates from the GitHub releases of Zono.

How it works:
1. Zono asks GitHub for the newest release (at most once per start, in the background).
2. When it is newer than the running version, its `Zono.exe` is downloaded to %LOCALAPPDATA%\\Zono\\Zono.exe
   (checked: size, SHA-256 that GitHub publishes for the file, a real Windows program).
3. Zono offers "Herstarten": the new Zono.exe starts and this one closes. Users never uninstall anything.
4. A Start-menu shortcut "Zono" points at that installed Zono.exe; an existing desktop shortcut "Zono" too.
5. Old unpacked versions under %LOCALAPPDATA%\\Zono\\app are removed to free disk space.

Only links from github.com/scoutr2019/zono are used, always over HTTPS.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPO = "scoutr2019/zono"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "Zono.exe"
ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Zono"
INSTALLED = ROOT / "Zono.exe"
STATE = ROOT / "update.json"
CREATE_NO_WINDOW = 0x08000000
ALLOWED_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                 "github-releases.githubusercontent.com", "api.github.com"}


def version_tuple(text):
    """ "v2.2.10" -> (2, 2, 10); anything unreadable -> ()."""
    numbers = re.findall(r"\d+", str(text or "").split("-")[0])
    return tuple(int(n) for n in numbers[:4]) if numbers else ()


def newer(candidate, current):
    return bool(version_tuple(candidate)) and version_tuple(candidate) > version_tuple(current)


def read_state():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(**values):
    state = read_state()
    state.update(values)
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        temporary = STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, STATE)
    except OSError:
        pass


def latest(timeout=10):
    """{version, url, size, sha256, notes} of the newest published release with a Zono.exe, or None."""
    request = Request(LATEST, headers={"Accept": "application/vnd.github+json", "User-Agent": "Zono-updater"})
    with urlopen(request, timeout=timeout) as response:
        release = json.loads(response.read(2_000_000).decode("utf-8"))
    if release.get("draft") or release.get("prerelease"):
        return None
    assets = release.get("assets") or []
    asset = next((a for a in assets if a.get("name") == ASSET), None) or \
        next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    if not asset:
        return None
    digest = str(asset.get("digest") or "")
    return {"version": str(release.get("tag_name", "")).lstrip("vV"), "url": asset.get("browser_download_url", ""),
            "size": int(asset.get("size") or 0), "sha256": digest[7:].lower() if digest.startswith("sha256:") else "",
            "notes": str(release.get("body") or "")[:2000]}


def release_notes(body, language="nl"):
    """Bullet lines of a release text for one language.

    Convention (also used by zono.be): bullets ("- ...") under headings "### NL", "### FR", "### EN", "### DE".
    Without those headings every bullet counts. Markdown marks are removed."""
    parts, plain, current = {}, [], None
    for line in str(body or "").splitlines():
        head = re.match(r"^#{1,4}\s*(NL|FR|EN|DE)\b", line, re.I)
        if head:
            current = head.group(1).lower()
            parts.setdefault(current, [])
            continue
        item = re.match(r"^\s*[-*]\s+(.+)", line)
        if item:
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", item.group(1))
            text = re.sub(r"\*\*|__|`", "", text).strip()
            (parts[current] if current else plain).append(text)
    return (parts.get(language) or parts.get("nl") or plain)[:8]


def _check_link(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"onverwachte downloadlink: {url}")


def download(info, progress=None, cancel=None):
    """Download the release into INSTALLED (via a temporary file) and check it. Returns the path."""
    _check_link(info["url"])
    ROOT.mkdir(parents=True, exist_ok=True)
    part = ROOT / "Zono.exe.part"
    digest, received = hashlib.sha256(), 0
    request = Request(info["url"], headers={"User-Agent": "Zono-updater", "Accept": "application/octet-stream"})
    with urlopen(request, timeout=30) as response, part.open("wb") as output:
        _check_link(response.geturl())  # GitHub redirects to its file servers: those must be GitHub's too
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("geannuleerd")
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            if progress:
                progress(received, info.get("size") or 0)
    try:
        if info.get("size") and received != info["size"]:
            raise ValueError(f"onvolledige download ({received} van {info['size']} bytes)")
        if info.get("sha256") and digest.hexdigest() != info["sha256"]:
            raise ValueError("de download klopt niet (SHA-256)")
        with part.open("rb") as check:
            if check.read(2) != b"MZ":
                raise ValueError("de download is geen Windows-programma")
        if received < 5_000_000:
            raise ValueError("de download is te klein")
        replace_installed(part)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    write_state(installed=info["version"], downloaded=info["version"], notes=info.get("notes", ""),
                notes_version=info["version"])
    return INSTALLED


def replace_installed(new_file):
    """Windows cannot overwrite a running program, but it can rename it: move the old one aside first."""
    if INSTALLED.exists():
        old = INSTALLED.with_name("Zono.old.exe")
        try:
            old.unlink(missing_ok=True)
        except OSError:
            old = INSTALLED.with_name(f"Zono.old.{os.getpid()}.exe")
        os.replace(INSTALLED, old)
    os.replace(new_file, INSTALLED)


def adopt(launcher, version):
    """Copy the Zono.exe the user started (from Downloads, say) to the fixed place, so Start menu, updates and
    the desktop shortcut always point at one Zono."""
    launcher = Path(launcher)
    if launcher.resolve() == INSTALLED.resolve():
        write_state(installed=version)
        return INSTALLED
    ROOT.mkdir(parents=True, exist_ok=True)
    part = ROOT / "Zono.exe.part"
    shutil.copyfile(launcher, part)
    replace_installed(part)
    write_state(installed=version)
    return INSTALLED


def installed_version():
    """Version of %LOCALAPPDATA%\\Zono\\Zono.exe when it is there, else ""."""
    return read_state().get("installed", "") if INSTALLED.is_file() else ""


def start_installed():
    subprocess.Popen([str(INSTALLED)], cwd=str(ROOT), close_fds=True,
                     env=dict(os.environ, ZONO_UPDATED="1"))


def make_shortcuts(desktop=False):
    """Start-menu shortcut "Zono" (always) and the desktop shortcut "Zono" (when one exists, or `desktop`)."""
    if os.name != "nt" or not INSTALLED.is_file():
        return
    script = (
        "$t=$env:ZONO_TARGET;$w=New-Object -ComObject WScript.Shell;"
        "$m=Join-Path ([Environment]::GetFolderPath('Programs')) 'Zono.lnk';"
        "$d=Join-Path ([Environment]::GetFolderPath('Desktop')) 'Zono.lnk';"
        "foreach($p in @($m,$d)){ if($p -eq $d -and -not (Test-Path $d) -and $env:ZONO_DESKTOP -ne '1'){continue};"
        "$s=$w.CreateShortcut($p);$s.TargetPath=$t;$s.WorkingDirectory=(Split-Path $t);"
        "$s.IconLocation=\"$t,0\";$s.Description='Zono';$s.Save() }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                       env=dict(os.environ, ZONO_TARGET=str(INSTALLED), ZONO_DESKTOP="1" if desktop else "0"), creationflags=CREATE_NO_WINDOW,
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def cleanup(current_folder):
    """Remove unpacked older versions (each is a few hundred MB) and the set-aside old Zono.exe."""
    removed = 0
    apps = ROOT / "app"
    current = Path(current_folder).resolve() if current_folder else None
    try:
        folders = [f for f in apps.iterdir() if f.is_dir()] if apps.is_dir() else []
    except OSError:
        folders = []
    for folder in folders:
        if current is not None and folder.resolve() == current:
            continue
        if not version_tuple(folder.name) or (current is not None and not newer(current.name, folder.name)):
            continue  # only folders of older versions than the one running now
        shutil.rmtree(folder, ignore_errors=True)
        removed += not folder.exists()
    for old in ROOT.glob("Zono.old*.exe"):
        try:
            old.unlink()
        except OSError:
            pass  # still running: next time
    return removed


def running_folder():
    """%LOCALAPPDATA%\\Zono\\app\\<version> when Zono runs from its unpacked release, else None (source checkout)."""
    executable = Path(sys.executable).resolve()
    if executable.parent.name.lower() == "runtime" and executable.parents[2].name.lower() == "app":
        return executable.parents[1]
    return None
