"""Make zono.be fast: take the big all-in-one index.html apart into small files.

    python tools/build_site.py <index.html> <output folder>

- the screenshots (one set per language) become WebP files in two sizes; the page loads only the current
  language, the big size only on big screens, and pictures further down only when you scroll to them;
- the fonts become WOFF2 files with just the letters the site uses;
- the page itself becomes a small HTML file.
Upload the output folder's contents to public_html (index.html + the folder "assets").
"""
import base64
import hashlib
import io
import re
import sys
from pathlib import Path

from PIL import Image

LATIN = list(range(0x20, 0x7F)) + list(range(0xA0, 0x180)) + list(range(0x2000, 0x2070)) + \
    [0x20AC, 0x2122, 0x2190, 0x2192, 0x2197, 0x203A, 0x2039, 0x2713, 0x2715, 0x2026, 0x00D7]


def short_hash(data):
    return hashlib.sha1(data).hexdigest()[:8]


def to_woff2(raw):
    from fontTools import subset
    from fontTools.ttLib import TTFont
    font = TTFont(io.BytesIO(raw))
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=LATIN)
    subsetter.subset(font)
    out = io.BytesIO()
    font.flavor = "woff2"
    font.save(out)
    return out.getvalue()


def webp(raw, width):
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=80, method=6)
    return out.getvalue()


def main():
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    html = source.read_text(encoding="utf-8")
    assets = target / "assets"
    (assets / "fonts").mkdir(parents=True, exist_ok=True)
    (assets / "img").mkdir(parents=True, exist_ok=True)

    # fonts
    def font(match):
        block = match.group(0)
        family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        raw = base64.b64decode(re.search(r"base64,([A-Za-z0-9+/=]+)", block).group(1))
        data = to_woff2(raw)
        name = f"{family.replace(' ', '')}-{weight}.{short_hash(data)}.woff2"
        (assets / "fonts" / name).write_bytes(data)
        return re.sub(r"src:\s*url\(data:font/ttf;base64,[A-Za-z0-9+/=]+\)\s*format\('truetype'\)",
                      f"src: url(assets/fonts/{name}) format('woff2')", block)
    html = re.sub(r"@font-face\s*\{[^}]*\}", font, html)

    # screenshots: "zono-live-fr.png": "data:image/png;base64,..." -> two WebP sizes per picture
    pictures = {}
    for key, encoded in re.findall(r'"([\w.-]+\.png)":"data:image/png;base64,([A-Za-z0-9+/=]+)"', html):
        raw = base64.b64decode(encoded)
        stem = key[:-4]
        small, big = webp(raw, 840), webp(raw, 1672)
        names = []
        for data, width in ((small, 840), (big, 1672)):
            name = f"{stem}-{width}.{short_hash(data)}.webp"
            (assets / "img" / name).write_bytes(data)
            names.append(name)
        pictures[key] = names
    start = html.index("const embeddedImages=")
    end = html.index("};", start) + 2
    entries = ",".join(f'"{key}":{{small:"assets/img/{small}",big:"assets/img/{big}"}}'
                       for key, (small, big) in pictures.items())
    html = html[:start] + "const embeddedImages={" + entries + "};" + html[end:]
    # the language switch sets small + big pictures; the browser picks the size
    html = html.replace(
        "img.src=embeddedImages[lang==='nl'?`zono-${asset}-v2.png`:`zono-${asset}-${lang}.png`];",
        "const pic=embeddedImages[lang==='nl'?`zono-${asset}-v2.png`:`zono-${asset}-${lang}.png`];"
        "img.srcset=`${pic.small} 840w, ${pic.big} 1672w`;img.sizes='(max-width: 900px) 100vw, 1120px';img.src=pic.small;")
    # only the first picture is needed right away; the others load when you scroll to them
    count = {"n": 0}

    def image_tag(match):
        count["n"] += 1
        extra = ' fetchpriority="high"' if count["n"] == 1 else ' loading="lazy"'
        return match.group(0)[:-1] + extra + ">"
    html = re.sub(r'<img width="1672" height="941" decoding="async"[^>]*>', image_tag, html)
    (target / "index.html").write_text(html, encoding="utf-8")
    size = sum(f.stat().st_size for f in assets.rglob("*") if f.is_file())
    print(f"index.html {len(html.encode()) / 1024:.0f} KB, assets {size / 1024:.0f} KB "
          f"({len(pictures)} pictures x 2 sizes, fonts in WOFF2)")


if __name__ == "__main__":
    main()
