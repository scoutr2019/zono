# After tests/showcase.js and a phone screenshot of server/tv/ per language: python3 tests/compose_login.py <shots folder> ../tv/screens
"""tv/screens/<lang>/login.jpg: the TV's login screen with the QR code, and the phone page next to it."""
import sys
from PIL import Image, ImageDraw, ImageFilter
S, OUT = sys.argv[1], sys.argv[2]
for lang in ("nl", "fr", "en", "de"):
    tv = Image.open(f"{S}/sh-{lang}/00-login.png").convert("RGB").resize((1600, 900), Image.LANCZOS)
    phone = Image.open(f"{S}/phone-{lang}.png").convert("RGB")
    h = 700
    w = round(phone.width * h / phone.height)
    phone = phone.resize((w, h), Image.LANCZOS)
    border, radius = 14, 46
    fw, fh = w + border * 2, h + border * 2
    x, y = 1600 - fw - 70, 900 - fh - 40
    shadow = Image.new("L", (1600, 900), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x + 10, y + 24, x + fw + 10, y + fh + 24), radius, fill=170)
    tv.paste((5, 4, 20), (0, 0), shadow.filter(ImageFilter.GaussianBlur(26)))
    frame = Image.new("RGB", (fw, fh), (18, 16, 40))
    mask = Image.new("L", (fw, fh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw - 1, fh - 1), radius, fill=255)
    inner = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner).rounded_rectangle((0, 0, w - 1, h - 1), radius - border, fill=255)
    frame.paste(phone, (border, border), inner)
    ImageDraw.Draw(frame).rounded_rectangle((0, 0, fw - 1, fh - 1), radius, outline=(70, 66, 120), width=2)
    tv.paste(frame, (x, y), mask)
    tv.save(f"{OUT}/{lang}/login.jpg", quality=84, optimize=True, progressive=True)
    print(lang, "ok")
