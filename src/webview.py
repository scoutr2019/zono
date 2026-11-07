"""Show a web page (a YouTube trailer) inside a Zono window on Windows.

Windows 10/11 always ship Microsoft Edge. Zono starts Edge in app mode with its own small profile, waits for
its window and docks it into a frame of the app (SetParent), so the trailer plays inside Zono instead of in
a browser tab. When that is not possible, `open()` reports failure and the caller falls back to the browser.
"""
import ctypes
import os
import subprocess
import re
import threading
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from i18n import T

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP = 0x40000000, 0x10000000, 0x80000000
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00020000, 0x00010000
WS_EX_APPWINDOW, WS_EX_WINDOWEDGE, WS_EX_CLIENTEDGE = 0x00040000, 0x00000100, 0x00000200
SWP_NOZORDER, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0004, 0x0020, 0x0040
CREATE_NO_WINDOW = 0x08000000

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Zono trailer __TOKEN__</title>
<meta name="referrer" content="strict-origin-when-cross-origin">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}iframe{border:0;width:100%;height:100%}</style>
</head><body><iframe src="https://www.youtube.com/embed/__KEY__?autoplay=1&rel=0&modestbranding=1&playsinline=1&hl=nl"
allow="autoplay; encrypted-media; fullscreen; picture-in-picture" allowfullscreen
referrerpolicy="strict-origin-when-cross-origin"></iframe></body></html>"""

_server = None
_server_lock = threading.Lock()


def page_url(key, token=""):
    """A local page that embeds the YouTube player (YouTube refuses embeds that have no page around them)."""
    global _server
    if not re.fullmatch(r"[\w-]{6,20}", key or ""):
        raise ValueError("bad trailer key")
    with _server_lock:
        if _server is None:
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    parts = urlsplit(self.path)
                    value = parse_qs(parts.query).get("v", [""])[0]
                    token = parse_qs(parts.query).get("k", [""])[0]
                    if parts.path != "/trailer" or not re.fullmatch(r"[\w-]{6,20}", value):
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = PAGE.replace("__KEY__", value).replace("__TOKEN__", re.sub(r"\W", "", token)[:20]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            _server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{_server.server_address[1]}/trailer?v={quote(key)}&k={quote(token)}"


def find_browser():
    """Path of Microsoft Edge (or Chrome), or None."""
    if os.name != "nt":
        return None
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for name in ("msedge.exe", "chrome.exe"):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                        path = winreg.QueryValue(key, None)
                        if path and Path(path).is_file():
                            return path
                except OSError:
                    continue
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for tail in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            path = Path(base) / tail
            if path.is_file():
                return str(path)
    return None


def available():
    return find_browser() is not None


class EmbeddedPage:
    """One docked browser window. Use from the Tk thread only."""

    def __init__(self, root, container, profile_dir):
        self.root, self.container, self.profile_dir = root, container, Path(profile_dir)
        self.process = None
        self.hwnd = None
        self.closed = False
        self.binding = None
        self.owner_pid = None

    def open(self, url, on_ready=None, on_fail=None, timeout=20.0, title=""):
        browser = find_browser()
        if not browser:
            if on_fail:
                on_fail(T("Geen Edge gevonden"))
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        width = max(320, self.container.winfo_width())
        height = max(200, self.container.winfo_height())
        arguments = [browser, f"--app={url}", f"--user-data-dir={self.profile_dir}", "--no-first-run",
                     "--no-default-browser-check", "--disable-features=Translate,msEdgeSidebarV2,msHubApps",
                     "--autoplay-policy=no-user-gesture-required", "--hide-crash-restore-bubble",
                     "--window-position=-32000,-32000", f"--window-size={width},{height}"]
        try:
            self.process = subprocess.Popen(arguments, creationflags=CREATE_NO_WINDOW)
        except OSError as error:
            if on_fail:
                on_fail(str(error))
            return
        user32 = ctypes.windll.user32
        waited = {"ms": 0}

        def find():
            """Edge sometimes hands the window to another of its processes, so look for our page title."""
            found = []
            pid = self.process.pid if self.process else -1
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def visit(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                name = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, name, 64)
                if not name.value.startswith("Chrome_WidgetWin"):
                    return True
                caption = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, caption, 256)
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if (title and title in caption.value) or (not title and owner.value == pid):
                    found.append((hwnd, owner.value))
                    return False
                return True
            user32.EnumWindows(callback_type(visit), 0)
            return found[0] if found else (None, None)

        def poll():
            if self.closed:
                return
            hwnd, owner = find()
            if hwnd:
                self.owner_pid = owner
                self.dock(hwnd)
                if on_ready:
                    on_ready()
                return
            if waited["ms"] > timeout * 1000:
                self.close()
                if on_fail:
                    on_fail(T("Edge startte niet"))
                return
            waited["ms"] += 120
            self.root.after(120, poll)
        poll()

    def dock(self, hwnd):
        user32 = ctypes.windll.user32
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.restype = ctypes.c_ssize_t
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        set_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        style = get_long(hwnd, GWL_STYLE)
        style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        set_long(hwnd, GWL_STYLE, style | WS_CHILD | WS_VISIBLE)
        extra = get_long(hwnd, GWL_EXSTYLE)
        set_long(hwnd, GWL_EXSTYLE, extra & ~(WS_EX_APPWINDOW | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE))
        user32.SetParent(hwnd, self.container.winfo_id())
        self.hwnd = hwnd
        self.fit()
        self.binding = self.container.bind("<Configure>", lambda _: self.fit(), add="+")

    def fit(self):
        if not self.hwnd or self.closed:
            return
        ctypes.windll.user32.SetWindowPos(self.hwnd, None, 0, 0, max(1, self.container.winfo_width()),
                                          max(1, self.container.winfo_height()),
                                          SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)

    def close(self):
        self.closed = True
        if self.hwnd:
            try:
                ctypes.windll.user32.ShowWindow(self.hwnd, 0)
                ctypes.windll.user32.SetParent(self.hwnd, None)
            except Exception:
                pass
            self.hwnd = None
        process, self.process = self.process, None
        owner, self.owner_pid = self.owner_pid, None
        pids = {p for p in ((process.pid if process and process.poll() is None else None), owner) if p}
        for pid in pids:
            threading.Thread(target=_stop, args=(pid,), daemon=True).start()


def _stop(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=8)
    except Exception:
        pass
