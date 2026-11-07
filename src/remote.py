"""Zono on your phone: a small web app served on the local network.

The phone (or a smart TV / TV box browser) opens http://<pc>:<port>/?t=<token>. Streams are relayed through
this PC, so the phone never sees the provider password and HLS playlists work in every browser; on an iPhone the
built-in AirPlay button sends them on to an Apple TV.
"""
import base64
import gzip
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import catalogue as data


def lan_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class RemoteServer:
    def __init__(self, snapshot, token, stop_pc=None):
        """`snapshot()` returns (profile name, library list, source); `token()` returns the access token;
        `stop_pc()` stops playback on the PC (providers often allow one stream at a time)."""
        self.snapshot, self.token, self.stop_pc = snapshot, token, stop_pc
        self.converter = None  # (code, Transcoder, last use)
        self.redirects = {}  # provider link -> (final link, time): asking the provider again for every playlist
                             # refresh can count as a new connection and get refused
        self.converter_lock = threading.Lock()
        self.server = None
        self.port = None

    @property
    def running(self):
        return self.server is not None

    def check(self, code):
        """Why does a stream not start? Asks the provider once and explains the answer."""
        try:
            url = self.unrelay(code)
        except (ValueError, UnicodeDecodeError):
            return {"reason": "link"}
        try:
            with urlopen(Request(url, headers={"User-Agent": "VLC/3.0 LibVLC/3.0", "Range": "bytes=0-1"}), timeout=10):
                return {"reason": "ok"}
        except HTTPError as error:
            if error.code in (401, 402, 403, 405, 429, 456, 458, 509, 551, 552, 553, 554):
                return {"reason": "limit", "status": error.code}
            if error.code in (404, 410):
                return {"reason": "gone", "status": error.code}
            return {"reason": "provider", "status": error.code}
        except OSError:
            return {"reason": "offline"}

    def compat(self, url, live):
        """Link to a phone-friendly (H.264) version of `url`, made on this PC when asked for."""
        if not url:
            return ""
        code = self.relay(url)[3:].split("?", 1)[0]
        return f"/t/{code}/index.m3u8?t={quote(self.token(), safe='')}&l={1 if live else 0}"

    def relay(self, url):
        """A link on this server that streams `url` from the provider."""
        if not url:
            return ""
        code = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
        return f"/s/{code}?t={quote(self.token(), safe='')}"

    @staticmethod
    def unrelay(code):
        url = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode("utf-8")
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("bad link")
        return url

    def convert(self, code, live):
        """Start (or keep) converting one stream for phones that cannot show the original picture."""
        import time
        with self.converter_lock:
            if self.converter and self.converter[0] == code and not self.converter[1].failed():
                self.converter[2] = time.monotonic()
                return self.converter[1]
            self.stop_converter()
            import player
            from pathlib import Path
            folder = Path(data.STATE).parent / "phone" / code[-24:]
            converter = player.Transcoder(self.unrelay(code), folder, live)
            self.converter = [code, converter, time.monotonic()]
            if not getattr(self, "watchdog", None):
                self.watchdog = threading.Thread(target=self.watch_converter, daemon=True)
                self.watchdog.start()
            return converter

    def stop_converter(self):
        if self.converter:
            converter, self.converter = self.converter[1], None
            try:
                converter.close()
            except Exception:
                pass

    def watch_converter(self):
        """Stop converting once the phone stopped asking for pieces of the stream."""
        import time
        while True:
            time.sleep(5)
            with self.converter_lock:
                if self.converter and time.monotonic() - self.converter[2] > 40:
                    self.stop_converter()
            if not self.server:
                with self.converter_lock:
                    self.stop_converter()
                self.watchdog = None
                return

    def playlist(self, text, base):
        """Point every link in an HLS playlist back at this server."""
        out = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                line = self.relay(urljoin(base, stripped))
            elif 'URI="' in line:
                line = re.sub(r'URI="([^"]+)"', lambda m: f'URI="{self.relay(urljoin(base, m.group(1)))}"', line)
            out.append(line)
        return "\n".join(out) + "\n"

    def url(self):
        return f"http://{lan_address()}:{self.port}/?t={self.token()}" if self.server else ""

    def start(self):
        if self.server:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, body, kind="application/json; charset=utf-8"):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                zipped = "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 1400
                if zipped:
                    body = gzip.compress(body, 5)
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                if zipped:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                if parts.path in ("/logo.png", "/icon.png"):
                    image = brand_image(parts.path[1:])
                    if image:
                        self.send(200, image, "image/png")
                    else:
                        self.send(404, "{}")
                    return
                if not owner.token() or query.get("t") != owner.token():
                    self.send(403, "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                                   "<body style='margin:0;background:#0b0b0f;color:#f5f5f7;font:17px -apple-system,"
                                   "Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;"
                                   "height:100vh;text-align:center;padding:24px'><div><div style='font-size:28px;"
                                   "font-weight:800'><img src='/logo.png' alt='zono tv' style='height:40px'></div><p>Deze link is "
                                   "niet (meer) geldig.<br>Scan de QR-code in Zono opnieuw.</p></div></body>",
                              "text/html; charset=utf-8")
                    return
                if parts.path.startswith("/s/"):
                    self.stream(parts.path[3:])
                    return
                if parts.path.startswith("/t/"):
                    self.converted(parts.path[3:], query)
                    return
                try:
                    if parts.path == "/api/check":
                        self.send(200, json.dumps(owner.check(query.get("c", ""))))
                    elif parts.path == "/api/stop-pc":
                        if owner.stop_pc:
                            owner.stop_pc()
                        self.send(200, "{}")
                    elif parts.path in ("/", "/index.html"):
                        self.send(200, PAGE.replace("__TOKEN__", owner.token()), "text/html; charset=utf-8")
                    elif parts.path == "/api/library":
                        self.send(200, json.dumps(owner.library(), ensure_ascii=False, separators=(",", ":")))
                    elif parts.path == "/api/episodes":
                        name, library, source = owner.snapshot()
                        rows = data.episodes(source, query.get("sid", "")) if source else []
                        self.send(200, json.dumps([{"n": r["title"], "g": r["group"], "u": owner.relay(r["url"]),
                                                    "c": owner.compat(r["url"], False),
                                                    "x": extension(r["url"])} for r in rows], ensure_ascii=False))
                    elif parts.path == "/api/guide":
                        name, library, source = owner.snapshot()
                        rows = data.guide(source, query.get("sid", "")) if source else []
                        self.send(200, json.dumps([{"n": r["title"], "s": r["start"], "e": r["end"]} for r in rows],
                                                  ensure_ascii=False))
                    else:
                        self.send(404, "{}")
                except Exception as error:  # report, never crash the server thread
                    self.send(500, json.dumps({"error": type(error).__name__}))

            def converted(self, rest, query):
                import time
                code, _, name = rest.partition("/")
                try:
                    owner.unrelay(code)
                except (ValueError, UnicodeDecodeError):
                    self.send(400, "{}")
                    return
                try:
                    if name == "index.m3u8":
                        converter = owner.convert(code, query.get("l") == "1")
                        index = converter.folder / "index.m3u8"
                        waited = 0
                        def pieces():  # iPhones start more smoothly with a few pieces ready
                            try:
                                return index.read_text(encoding="utf-8", errors="replace").count("#EXTINF")
                            except OSError:
                                return 0
                        while waited < 35 and not converter.failed() and pieces() < (3 if waited < 20 else 1):
                            time.sleep(0.25)
                            waited += 0.25
                        if not index.exists():
                            self.send(504, "{}")
                            return
                        text = index.read_text(encoding="utf-8", errors="replace")
                        token = quote(owner.token(), safe="")
                        text = "\n".join(line + f"?t={token}" if line.strip() and not line.startswith("#") else line
                                         for line in text.splitlines()) + "\n"
                        self.send(200, text, "application/vnd.apple.mpegurl")
                        return
                    with owner.converter_lock:
                        current = owner.converter
                        if current and current[0] == code:
                            current[2] = time.monotonic()
                            folder = current[1].folder
                        else:
                            folder = None
                    if not folder or not re.fullmatch(r"seg-\d+\.ts", name) or not (folder / name).is_file():
                        self.send(404, "{}")
                        return
                    self.send(200, (folder / name).read_bytes(), "video/mp2t")
                except Exception as error:
                    self.send(500, json.dumps({"error": type(error).__name__}))

            def stream(self, code):
                try:
                    url = owner.unrelay(code)
                except (ValueError, UnicodeDecodeError):
                    self.send(400, "{}")
                    return
                headers = {"User-Agent": "VLC/3.0 LibVLC/3.0", "Accept": "*/*"}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]
                import time as clock
                cached = owner.redirects.get(url)
                target = cached[0] if cached and clock.monotonic() - cached[1] < 300 else url
                upstream = None
                for attempt in (target, url) if target != url else (url,):
                    try:
                        upstream = urlopen(Request(attempt, headers=headers), timeout=15)
                        break
                    except HTTPError as error:
                        owner.redirects.pop(url, None)
                        if attempt == url:
                            owner.last_error = error.code
                            self.send(error.code if 400 <= error.code < 600 else 502, "{}")
                            return
                    except OSError:
                        owner.redirects.pop(url, None)
                        if attempt == url:
                            owner.last_error = 0
                            self.send(502, "{}")
                            return
                with upstream:
                    kind = upstream.headers.get("Content-Type", "") or "application/octet-stream"
                    final = upstream.geturl()
                    if final != url and urlsplit(url).path.lower().endswith(".m3u8"):
                        owner.redirects[url] = (final, clock.monotonic())
                    hls = "mpegurl" in kind.lower() or urlsplit(final).path.lower().endswith(".m3u8")
                    if hls:
                        text = upstream.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
                        self.send(200, owner.playlist(text, final), "application/vnd.apple.mpegurl")
                        return
                    if urlsplit(final).path.lower().endswith(".ts") and "video" not in kind:
                        kind = "video/mp2t"
                    self.send_response(upstream.status)
                    for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
                        if upstream.headers.get(name):
                            self.send_header(name, upstream.headers[name])
                    self.send_header("Content-Type", kind)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    try:
                        while True:
                            chunk = upstream.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    except OSError:
                        pass  # the phone skipped ahead or closed the player

        for port in range(8899, 8920):
            try:
                self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
                self.port = port
                break
            except OSError:
                continue
        if not self.server:
            raise OSError("Geen vrije poort gevonden.")
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        with self.converter_lock:
            self.stop_converter()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def library(self):
        name, library, source = self.snapshot()
        live, movies, series = [], [], []
        for item in library:
            kind = item.get("kind")
            row = {"n": item.get("title", ""), "g": item.get("group") or "Overige", "i": item.get("image") or ""}
            if kind == "live":
                link = item.get("url", "")
                parts = urlsplit(link)
                if parts.path.lower().endswith(".ts"):
                    link = urlunsplit(parts._replace(path=parts.path[:-3] + ".m3u8"))
                row.update(u=self.relay(link), c=self.compat(item.get("url", ""), True), s=item.get("sid", ""))
                live.append(row)
            elif kind == "movie":
                row.update(u=self.relay(item.get("url", "")), c=self.compat(item.get("url", ""), False),
                           r=item.get("rating") or 0, x=extension(item.get("url", "")))
                movies.append(row)
            elif kind == "series":
                row.update(s=item.get("sid", ""), r=item.get("rating") or 0)
                series.append(row)
        return {"profile": name, "live": live, "movie": movies, "series": series, "guide": bool(source)}


def extension(url):
    path = urlsplit(url or "").path.lower()
    return path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""


_BRAND = {}


def brand_image(name):
    """The wordmark, or an opaque square home-screen icon for iPhone."""
    if name not in _BRAND:
        try:
            from io import BytesIO
            from pathlib import Path
            from PIL import Image
            folder = Path(__file__).parent
            if name == "logo.png":
                _BRAND[name] = (folder / "zono_logo.png").read_bytes()
            else:
                mark = Image.open(folder / "zono_mark.png").convert("RGBA")
                square = Image.new("RGBA", mark.size, mark.getpixel((mark.width // 2, mark.height // 8)))
                square.alpha_composite(mark)
                out = BytesIO()
                square.convert("RGB").resize((180, 180), Image.Resampling.LANCZOS).save(out, "PNG", optimize=True)
                _BRAND[name] = out.getvalue()
        except Exception:
            _BRAND[name] = b""
    return _BRAND[name]


PAGE = r"""<!doctype html>
<html lang="nl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0b0b0f">
<title>Zono</title>
<link rel="icon" type="image/png" href="/icon.png">
<link rel="apple-touch-icon" href="/icon.png">
<style>
:root{--bg:#0b0b0f;--panel:#18181f;--raised:#23232b;--line:#2b2b34;--text:#f5f5f7;--soft:#d3d3db;--muted:#9b9ba8;--dim:#64646f;--accent:#5558f5;--accent2:#8f91fb;--live:#e5243b}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(11,11,15,.92);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);padding:calc(env(safe-area-inset-top) + 12px) 16px 10px;border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;justify-content:space-between}
.logo{display:flex;align-items:center}.logo img{height:30px;display:block}
.who{color:var(--muted);font-size:13px}
.search{margin-top:10px;display:flex;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:0 12px}
.search input{flex:1;background:none;border:0;color:var(--text);font-size:16px;padding:11px 8px;outline:none}
.tabs{display:flex;gap:8px;margin-top:10px}
.tab{flex:1;text-align:center;padding:9px 0;border-radius:999px;background:var(--panel);color:var(--soft);font-weight:600;font-size:14px;border:1px solid var(--line)}
.tab.on{background:#fff;color:#0b0b0f;border-color:#fff}
.chips{display:flex;gap:8px;overflow-x:auto;padding:12px 16px 4px;scrollbar-width:none}.chips::-webkit-scrollbar{display:none}
.chip{flex:none;padding:7px 13px;border-radius:999px;background:var(--panel);border:1px solid var(--line);color:var(--soft);font-size:13px;font-weight:600;white-space:nowrap}
.chip.on{background:#fff;color:#0b0b0f;border-color:#fff}
main{padding:8px 16px calc(env(safe-area-inset-bottom) + 30px)}
.row{display:flex;align-items:center;gap:12px;padding:10px 8px;border-radius:12px}
.row:active{background:var(--raised)}
.num{width:28px;text-align:right;color:var(--dim);font-weight:700;font-size:13px}
.logo40{width:44px;height:44px;border-radius:11px;background:var(--raised);display:flex;align-items:center;justify-content:center;overflow:hidden;font-weight:800;font-size:14px;color:#fff;flex:none}
.logo40 img{width:78%;height:78%;object-fit:contain}
.logo40.has{background:#f1f1f5}
.name{font-weight:650}.sub{color:var(--muted);font-size:12.5px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
@media(min-width:640px){.grid{grid-template-columns:repeat(5,minmax(0,1fr))}}
.card .art{aspect-ratio:2/3;border-radius:12px;background:linear-gradient(160deg,#4c1d95,#db2777);overflow:hidden;position:relative}
.card .art img{width:100%;height:100%;object-fit:cover;display:block}
.card .art span{position:absolute;left:8px;right:8px;bottom:8px;font-weight:800;font-size:13px;text-shadow:0 1px 6px #000}
.card .t{font-weight:650;font-size:13px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card .r{color:var(--muted);font-size:12px}
.more{display:block;width:100%;margin:18px 0;padding:13px;border-radius:999px;border:0;background:var(--raised);color:var(--text);font-weight:700;font-size:15px}
.empty{color:var(--muted);text-align:center;padding:60px 0}
.sheet{position:fixed;inset:0;background:var(--bg);z-index:20;display:none;flex-direction:column;overflow-y:auto}
.sheet.open{display:flex}
.bar{display:flex;align-items:center;gap:12px;padding:calc(env(safe-area-inset-top) + 10px) 14px 10px}
.back{width:40px;height:40px;border-radius:50%;background:var(--raised);border:0;color:#fff;font-size:20px;flex:none}
.bar .ttl{font-weight:750;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badge{background:var(--live);color:#fff;font-weight:800;font-size:11px;padding:3px 7px;border-radius:5px;flex:none}
video{width:100%;aspect-ratio:16/9;background:#000;display:block}
.err{display:none;margin:14px 16px 0;padding:14px;border-radius:12px;background:#2a1418;border:1px solid #5b2330;color:#ffd9de;font-size:14px;line-height:1.45}
.err.on{display:block}.err .btns{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.err button{border:0;border-radius:999px;padding:9px 14px;font-weight:700;font-size:14px;background:#fff;color:#0b0b0f}.err button+button{background:var(--raised);color:var(--text)}
.note{display:none;margin:12px 16px 0;padding:12px 14px;border-radius:12px;background:#1b1d3a;color:#d6d7ff;font-size:13.5px}
.modebar{display:flex;justify-content:flex-end;padding:8px 16px 0}.mode{border:0;background:none;color:var(--accent2);font-weight:700;font-size:13.5px;padding:6px 0}
.hint{display:flex;gap:10px;align-items:center;margin:14px 16px;padding:12px 14px;border-radius:12px;background:var(--panel);color:var(--soft);font-size:13.5px}
.air{margin-left:auto;flex:none;padding:8px 14px;border-radius:999px;border:0;background:#fff;color:#0b0b0f;font-weight:700;display:none}
.list{padding:0 12px 40px}
.sec{color:var(--dim);font-size:11.5px;font-weight:800;letter-spacing:.6px;margin:16px 6px 6px}
.ep{padding:12px 10px;border-radius:10px}.ep:active{background:var(--raised)}
.ep.on{background:var(--raised)}.ep.on .name{color:var(--accent2)}
</style></head><body>
<header>
  <div class="top"><div class="logo"><img src="/logo.png" alt="zono tv"></div><div class="who" id="who"></div></div>
  <label class="search"><span style="color:var(--muted)">⌕</span><input id="q" type="search" placeholder="Zoek films, series of zenders" autocomplete="off"></label>
  <div class="tabs"><div class="tab on" data-k="live">Live TV</div><div class="tab" data-k="movie">Films</div><div class="tab" data-k="series">Series</div></div>
</header>
<div class="chips" id="chips"></div>
<main id="main"><div class="empty">Laden…</div></main>
<div class="sheet" id="sheet">
  <div class="bar"><button class="back" id="back">‹</button><span class="badge" id="badge">LIVE</span><div class="ttl" id="ttl"></div></div>
  <video id="v" controls playsinline autoplay x-webkit-airplay="allow"></video>
  <div class="err" id="err"><div id="errt"></div><div class="btns"><button id="retry">Opnieuw proberen</button><button id="stoppc">Stop afspelen op pc</button></div></div>
  <div class="note" id="note"></div>
  <div class="modebar"><button class="mode" id="mode">Zwart beeld? Tik hier</button></div>
  <div class="hint" id="hint"><span>📺</span><span>Kijken op je Apple TV? Tik op het AirPlay-icoon in de speler.</span><button class="air" id="air">AirPlay</button></div>
  <div class="list" id="list"></div>
</div>
<script>
const T="__TOKEN__";let D=null,kind="live",cat=null,limit=60,hls=null;
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const api=p=>fetch(p+(p.includes("?")?"&":"?")+"t="+T).then(r=>r.json());
const hue=n=>{let h=0;for(const c of n)h=(h*31+c.charCodeAt(0))%360;return h};
const tile=n=>`background:linear-gradient(140deg,hsl(${hue(n)} 65% 38%),hsl(${(hue(n)+50)%360} 75% 55%))`;
const initials=n=>(n.split(/\s+/).filter(w=>/^\w/.test(w)).slice(0,2).map(w=>w[0]).join("")||n.slice(0,2)).toUpperCase();
function items(){const q=$("#q").value.trim().toLowerCase();let a=D[kind];if(q){return ["live","movie","series"].flatMap(k=>D[k].filter(x=>x.n.toLowerCase().includes(q)).map(x=>({...x,k})))}
 if(cat)a=a.filter(x=>x.g===cat);return a.map(x=>({...x,k:kind}))}
function chips(){const q=$("#q").value.trim();const el=$("#chips");if(q){el.innerHTML="";return}
 const c={};D[kind].forEach(x=>c[x.g]=(c[x.g]||0)+1);const g=Object.keys(c).sort((a,b)=>c[b]-c[a]).slice(0,30);
 el.innerHTML=`<div class="chip ${cat?"":"on"}" data-c="">Alle</div>`+g.map(x=>`<div class="chip ${x===cat?"on":""}" data-c="${esc(x)}">${esc(x)}</div>`).join("");
 el.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{cat=c.dataset.c||null;limit=60;draw()})}
function draw(){chips();const all=items(),a=all.slice(0,limit),m=$("#main");
 if(!all.length){m.innerHTML=`<div class="empty">Niets gevonden</div>`;return}
 const lives=a.filter(x=>x.k==="live"),vod=a.filter(x=>x.k!=="live");let h="";
 if(lives.length)h+=lives.map((x,i)=>`<div class="row" data-i="${all.indexOf(x)}"><div class="num">${i+1}</div><div class="logo40 ${x.i?"has":""}" style="${x.i?"":tile(x.n)}">${x.i?`<img loading="lazy" src="${esc(x.i)}" onerror="this.parentNode.classList.remove('has');this.replaceWith('${initials(x.n)}')">`:initials(x.n)}</div><div><div class="name">${esc(x.n)}</div><div class="sub">${esc(x.g)}</div></div></div>`).join("");
 if(vod.length)h+=`<div class="grid" style="margin-top:${lives.length?16:4}px">`+vod.map(x=>`<div class="card" data-i="${all.indexOf(x)}"><div class="art" style="${tile(x.n)}">${x.i?`<img loading="lazy" src="${esc(x.i)}" onerror="this.remove()">`:""}<span>${x.i?"":esc(x.n)}</span></div><div class="t">${esc(x.n)}</div><div class="r">${x.r?"★ "+Number(x.r).toFixed(1)+" · ":""}${x.k==="series"?"Serie":"Film"}</div></div>`).join("")+"</div>";
 if(all.length>limit)h+=`<button class="more" id="more">Meer tonen</button>`;
 m.innerHTML=h;m.querySelectorAll("[data-i]").forEach(e=>e.onclick=()=>open(all[+e.dataset.i],all));
 const mo=$("#more");if(mo)mo.onclick=()=>{limit+=90;draw()}}
let cur=null,wait=null,check=null;
let COMPAT=false;try{COMPAT=localStorage.getItem("zono-compat")==="1"}catch(e){}
const IOS=/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
const ODD=["mkv","avi","wmv","flv","divx"];
const WIRELESS=()=>!!$("#v").webkitCurrentPlaybackTargetIsWireless;
const MSG={limit:"Je provider weigert deze stream nu. Meestal speelt er al iets op een ander toestel (je pc, een opname of multiview) en laat je abonnement maar één stream tegelijk toe.",
 gone:"Deze zender of titel bestaat niet meer bij je provider.",offline:"Je pc kan je provider nu niet bereiken. Controleer de internetverbinding van je pc.",
 provider:"Je provider gaf een fout terug. Probeer het over een minuutje opnieuw.",
 ok:"De stream is bereikbaar, maar je toestel kan hem niet tonen. Tik op ‘Zwart beeld? Tik hier’ om hem door je pc te laten omzetten.",
 link:"Deze link is niet geldig. Scan de QR-code in Zono opnieuw."};
function fail(){if(!cur)return;clearTimeout(wait);clearTimeout(check);
 if(!cur.url){show("Voor deze titel heeft je provider geen link gegeven.",false);return}
 if(WIRELESS())return;
 $("#errt").textContent="Even kijken wat er mis is…";$("#err").classList.add("on");$("#stoppc").style.display="none";
 const code=(cur.url.match(/\/s\/([^?]+)/)||[])[1]||"";
 api("/api/check?c="+encodeURIComponent(code)).then(r=>show(MSG[r.reason]||MSG.provider,r.reason==="limit")).catch(()=>show(MSG.offline,false))}
function show(t,limit){$("#errt").textContent=t;$("#stoppc").style.display=limit?"":"none";$("#err").classList.add("on")}
function note(t){$("#note").textContent=t;$("#note").style.display=t?"block":"none"}
function setCompat(on){COMPAT=on;try{localStorage.setItem("zono-compat",on?"1":"0")}catch(e){}}
function play(url,live,ext,curl,force){const v=$("#v");if(hls){hls.destroy();hls=null}clearTimeout(check);
 const compat=!!curl&&(force===true||(force!==false&&(COMPAT||ODD.includes((ext||"").toLowerCase()))));
 cur={url,live,ext,curl,compat};$("#err").classList.remove("on");clearTimeout(wait);if(!url){fail();return}
 const src=compat?curl:url;
 note(compat?"Je pc zet deze stream om zodat je telefoon het beeld kan tonen. Even geduld…":"");
 $("#mode").textContent=compat?"Originele weergave":"Zwart beeld? Tik hier";
 $("#mode").style.display=curl?"":"none";
 let last=-1;wait=setTimeout(function tick(){if(WIRELESS())return;const v=$("#v");
  if(v.readyState>=2&&!v.paused)return;          // playing
  if(v.currentTime!==last&&v.currentTime>0){last=v.currentTime;wait=setTimeout(tick,8000);return}  // slow, but moving
  if(!compat&&curl&&!WIRELESS())retryCompat();else fail()},compat?45000:25000);
 const isHls=compat||live;
 if(isHls&&!v.canPlayType("application/vnd.apple.mpegurl")){
  const go=()=>{if(!window.Hls||!Hls.isSupported()){v.src=src;v.play().catch(()=>{});return}
   hls=new Hls();hls.on(Hls.Events.ERROR,(e,d)=>{if(d.fatal){if(!compat&&curl)retryCompat();else fail()}});hls.loadSource(src);hls.attachMedia(v);v.play().catch(()=>{})};
  if(window.Hls)go();else{const s=document.createElement("script");s.src="https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js";s.onload=go;s.onerror=go;document.head.appendChild(s)}}
 else{v.src=src;v.play().catch(()=>{})}}
function retryCompat(){if(!cur||cur.compat||!cur.curl)return;play(cur.url,cur.live,cur.ext,cur.curl,true)}
function open(x,all){$("#sheet").classList.add("open");$("#ttl").textContent=x.n;$("#badge").style.display=x.k==="live"?"":"none";
 const L=$("#list");L.innerHTML="";
 if(x.k==="live"){play(x.u,true,"m3u8",x.c);const near=all.filter(y=>y.k==="live");L.innerHTML=`<div class="sec">ZENDERS</div>`+near.slice(0,80).map((y,i)=>`<div class="ep ${y===x?"on":""}" data-i="${i}"><div class="name">${i+1}. ${esc(y.n)}</div><div class="sub">${esc(y.g)}</div></div>`).join("");
  L.querySelectorAll(".ep").forEach(e=>e.onclick=()=>open(near[+e.dataset.i],all));
  if(D.guide&&x.s)api("/api/guide?sid="+encodeURIComponent(x.s)).then(g=>{if(!g.length)return;const now=Date.now()/1000;
   const t=s=>new Date(s*1000).toLocaleTimeString("nl-BE",{hour:"2-digit",minute:"2-digit"});
   L.insertAdjacentHTML("afterbegin",`<div class="sec">NU EN STRAKS</div>`+g.filter(r=>r.e>now).slice(0,5).map(r=>`<div class="ep ${r.s<=now?"on":""}"><div class="name">${t(r.s)}  ${esc(r.n)}</div></div>`).join(""))}).catch(()=>{})}
 else if(x.k==="movie"){play(x.u,false,x.x,x.c)}
 else{cur=null;clearTimeout(wait);$("#err").classList.remove("on");$("#v").removeAttribute("src");L.innerHTML=`<div class="sec">AFLEVERINGEN</div><div class="sub" style="padding:8px">Laden…</div>`;
  api("/api/episodes?sid="+encodeURIComponent(x.s)).then(eps=>{let h="",g=null;eps.forEach((e,i)=>{if(e.g!==g){g=e.g;h+=`<div class="sec">${esc(g).toUpperCase()}</div>`}h+=`<div class="ep" data-i="${i}"><div class="name">${esc(e.n)}</div></div>`});
   L.innerHTML=h||`<div class="empty">Geen afleveringen</div>`;L.querySelectorAll(".ep").forEach(el=>el.onclick=()=>{L.querySelectorAll(".ep").forEach(z=>z.classList.remove("on"));el.classList.add("on");$("#ttl").textContent=eps[+el.dataset.i].n;play(eps[+el.dataset.i].u,eps[+el.dataset.i].x==="m3u8",eps[+el.dataset.i].x,eps[+el.dataset.i].c);window.scrollTo(0,0)})})}}
$("#v").addEventListener("error",()=>{if(!hls)fail()});
$("#v").addEventListener("playing",()=>{clearTimeout(wait);$("#err").classList.remove("on");note("");
 clearTimeout(check);if(cur&&!cur.compat&&cur.curl)check=setTimeout(()=>{const v=$("#v");
  if(cur&&!cur.compat&&!v.paused&&!WIRELESS()&&v.readyState>=2&&v.videoWidth===0&&v.currentTime>1){setCompat(true);retryCompat()}},4000)});
$("#v").addEventListener("webkitcurrentplaybacktargetiswirelesschanged",()=>{clearTimeout(check);clearTimeout(wait);$("#err").classList.remove("on");
 $("#note").textContent=WIRELESS()?"Speelt af op je Apple TV.":"";$("#note").style.display=WIRELESS()?"block":"none"});
$("#mode").onclick=()=>{if(!cur||!cur.curl)return;const on=!cur.compat;setCompat(on);play(cur.url,cur.live,cur.ext,cur.curl,on)};
$("#retry").onclick=()=>{if(cur)play(cur.url,cur.live,cur.ext,cur.curl,cur.compat)};
$("#stoppc").onclick=()=>{api("/api/stop-pc").catch(()=>{});$("#stoppc").textContent="Gestopt op pc";setTimeout(()=>{$("#stoppc").textContent="Stop afspelen op pc";if(cur)play(cur.url,cur.live,cur.ext,cur.curl,cur.compat)},1500)};
$("#back").onclick=()=>{cur=null;clearTimeout(wait);$("#err").classList.remove("on");const v=$("#v");v.pause();v.removeAttribute("src");v.load();if(hls){hls.destroy();hls=null}$("#sheet").classList.remove("open")};
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{document.querySelectorAll(".tab").forEach(z=>z.classList.toggle("on",z===t));kind=t.dataset.k;cat=null;limit=60;$("#q").value="";draw();window.scrollTo(0,0)});
$("#q").oninput=()=>{limit=60;draw()};
const v=$("#v");if(window.WebKitPlaybackTargetAvailabilityEvent){v.addEventListener("webkitplaybacktargetavailabilitychanged",e=>{$("#air").style.display=e.availability==="available"?"block":"none"});$("#air").onclick=()=>v.webkitShowPlaybackTargetPicker()}
api("/api/library").then(d=>{D=d;$("#who").textContent=d.profile;draw()}).catch(()=>{$("#main").innerHTML=`<div class="empty">Zono op je pc is niet bereikbaar.</div>`});
</script></body></html>"""
