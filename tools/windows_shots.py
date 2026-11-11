"""Pictures of Zono for Windows for zono.be: the real app with an invented library (titles and drawn posters made
here, no real posters or logos), in four languages. Linux with a virtual screen:

    xvfb-run -a -s "-screen 0 1672x941x24" python3 tools/windows_shots.py <output folder> [nl fr en de]

Use a Python whose Tk draws with fontconfig (ZONO_SHOT_PYTHON=/usr/bin/python3.12 here). Tip: map "Segoe UI" to Inter with fontconfig and point WINDIR at a folder whose Fonts/ holds segoeui*.ttf links to
Inter, so the letters look like on Windows.
"""
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1])
LANGS = sys.argv[2:] or ["nl", "fr", "en", "de"]
PALETTES = [("#0f1b4d", "#6a3bd6", "#ff8f6b"), ("#081c2e", "#11698e", "#5ad1c8"), ("#2a0f3d", "#c2185b", "#ffb74d"),
            ("#0b1d14", "#2e7d5b", "#c5e1a5"), ("#1a1033", "#3949ab", "#90caf9"), ("#2b1608", "#b4532a", "#ffd180"),
            ("#0d0d1f", "#5e35b1", "#f48fb1"), ("#06262e", "#00838f", "#ffe082")]
FILMS = [("Noorderlicht", 8.4), ("Stad van Glas", 7.9), ("Zoutwater", 7.6), ("Orbit", 8.1), ("De Vuurtoren", 7.3),
         ("Koud Spoor", 7.8), ("Middernacht in Gent", 7.1), ("Wolkenkrabber", 7.4), ("Het Stille Dorp", 7.7),
         ("Neon Nachten", 7.2), ("De Erfenis", 6.9), ("Woestijnwind", 7.5), ("Diepblauw", 8.2), ("Laatste Ronde", 7.0),
         ("Papieren Vogels", 7.3), ("Schaduwspel", 7.6)]
SERIES = ["De Haven", "Kustwacht", "Familie Peeters", "Het Kantoor", "Spoorloos", "Bloed & Bier", "De Brug", "Achter de Dijk"]
CHANNELS = ["Nieuws 24", "Sport 1", "Cinema Max 4K", "Natuur & Reizen 4K", "Kids Club", "Muziek Hits", "Koken & Wonen",
            "Docu Plus", "Lach TV", "Sport 2", "Wereld Nieuws", "Retro Films"]


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def art(name, w, h, title=None):
    """A drawn landscape in the colours of the title (the same idea as the TV pictures)."""
    rng = random.Random(name)
    top, mid, low = (hex_rgb(c) for c in rng.choice(PALETTES))
    image = Image.new("RGB", (w, h))
    px = image.load()
    for y in range(h):
        t = y / h
        a, b, k = (top, mid, t / .65) if t < .65 else (mid, low, (t - .65) / .35)
        colour = tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
        for x in range(w):
            px[x, y] = colour
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(40):
        x, y, r = rng.random() * w, rng.random() * h * .45, rng.random() * 1.6 + .4
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(rng.random() * 180)))
    sx, sy, sr = w * (.25 + rng.random() * .5), h * (.42 + rng.random() * .12), min(w, h) * (.12 + rng.random() * .08)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((sx - sr * 2, sy - sr * 2, sx + sr * 2, sy + sr * 2), fill=low + (130,))
    image.paste(glow.filter(ImageFilter.GaussianBlur(sr * .8)), (0, 0), glow.filter(ImageFilter.GaussianBlur(sr * .8)))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((sx - sr * .55, sy - sr * .55, sx + sr * .55, sy + sr * .55), fill=(255, 243, 224, 235))
    for layer in range(4):
        base, amp, steps = h * (.55 + layer * .11), h * (.16 - layer * .03), 6 + layer * 2
        points = [(0, h), (0, base)] + [(i / steps * w, base - rng.random() * amp) for i in range(steps + 1)] + [(w, h)]
        draw.polygon(points, fill=top + (int(255 * (.45 + layer * .18)),))
    shade = Image.new("L", (1, h))
    for y in range(h):
        shade.putpixel((0, y), int(max(0, (y / h - .55) / .45) * 190))
    image.paste((0, 0, 0), (0, 0), shade.resize((w, h)))
    if title:
        draw = ImageDraw.Draw(image)
        words, lines = title.upper().split(), []
        for word in words:
            if lines and len(lines[-1] + " " + word) <= 11:
                lines[-1] += " " + word
            else:
                lines.append(word)
        size = int(min(w * .12, w * .8 / (max(map(len, lines)) * .74)))
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", size)
        for i, line in enumerate(lines):
            y = h * .9 - (len(lines) - 1 - i) * size * 1.1
            draw.text((w / 2, y), line, font=font, fill="white", anchor="ms")
    return image


def main():
    temp = Path(tempfile.mkdtemp(prefix="zono-shots-"))
    pictures = temp / "art"
    pictures.mkdir()
    for title, _ in FILMS:
        art(title, 342, 513, title).save(pictures / f"p-{abs(hash(title)) % 10**8}.jpg", quality=88)
        art(title + " wide", 1280, 720).save(pictures / f"w-{abs(hash(title)) % 10**8}.jpg", quality=86)
    for title in SERIES:
        art(title, 342, 513, title).save(pictures / f"p-{abs(hash(title)) % 10**8}.jpg", quality=88)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(pictures)))
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    web = f"http://127.0.0.1:{server.server_address[1]}"
    base = "http://provider.example"
    now = int(time.time())
    library = []
    for i, name in enumerate(CHANNELS):
        library.append({"id": f"{base}|live|{i + 1}", "sid": str(i + 1), "kind": "live", "title": name,
                        "group": "België" if i % 3 else "Nederland", "image": "", "url": f"{base}/live/u/p/{i + 1}.m3u8"})
    for i, (title, rating) in enumerate(FILMS):
        key = abs(hash(title)) % 10**8
        library.append({"id": f"{base}|movie|{100 + i}", "sid": str(100 + i), "kind": "movie", "title": title,
                        "group": "Nieuw", "image": f"{web}/p-{key}.jpg", "backdrop": f"{web}/w-{key}.jpg",
                        "url": f"{base}/movie/u/p/{100 + i}.mkv", "rating": rating, "added": now - i * 86400})
    for i, title in enumerate(SERIES):
        key = abs(hash(title)) % 10**8
        library.append({"id": f"{base}|series|{500 + i}", "sid": str(500 + i), "kind": "series", "title": title,
                        "group": "Vlaams", "image": f"{web}/p-{key}.jpg", "url": "", "rating": 7.5, "added": now - i * 86400})
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        home = temp / f"home-{lang}"
        (home / "Zono").mkdir(parents=True)
        (home / "Zono" / "library.json").write_text(json.dumps({"revision": "shots", "library": library, "source": None,
                                                                "favorites": {}, "progress": {}}))
        (home / "Zono" / "preferences.json").write_text(json.dumps({"countries_asked": True}))
        env = dict(os.environ, LOCALAPPDATA=str(home), APPDATA=str(home), ZONO_LANGUAGE=lang, ZONO_SYNC_API="http://127.0.0.1:9/x",
                   NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        for tab in ("home", "movie"):
            target = OUT / f"zono-windows-{tab}-{lang}.png"
            subprocess.run([os.environ.get("ZONO_SHOT_PYTHON", sys.executable), "-c", SHOT, str(ROOT / "src"), str(target), tab],
                           env=env, check=True, timeout=180)
            print(lang, target)
    server.shutdown()


SHOT = r"""
import sys, time, subprocess
sys.path.insert(0, sys.argv[1])
import tkinter as tk
import catalogue as data, app
root = tk.Tk()
app.configure_scale(root)
root.geometry("1672x941+0+0")
zono = app.Zono(root, data.load_profiles())
for _ in range(20):
    root.update(); time.sleep(0.03)
root.geometry("1672x941+0+0")
if sys.argv[3] != "home":
    zono.select(sys.argv[3])
end = time.time() + 9
while time.time() < end:
    root.update(); time.sleep(0.03)
w, h = root.winfo_width(), root.winfo_height()
subprocess.run(["import", "-window", "root", "-crop", f"{w}x{h}+0+0", sys.argv[2]], check=True)
root.destroy()
"""

if __name__ == "__main__":
    main()
