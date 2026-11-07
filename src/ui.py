"""Zono visual toolkit: palette, drawn icons, rounded pills, artwork and small custom widgets.

Tkinter cannot draw rounded corners or anti-aliased icons, so everything that needs them is
rendered with Pillow at a higher resolution and scaled down, then shown as an image.
"""
import hashlib
import math
import os
import threading
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageTk

BG, SIDE, PANEL, RAISED, LINE = "#0b0b0f", "#111116", "#18181f", "#23232b", "#2b2b34"
TEXT, SOFT, MUTED, DIM = "#f5f5f7", "#d3d3db", "#9b9ba8", "#64646f"
ACCENT, ACCENT_SOFT, LIVE_RED, WHITE = "#5558f5", "#8f91fb", "#e5243b", "#ffffff"
FONT = "Segoe UI"
SS = 3
SCALE = 1.0  # set by the app from the real screen DPI


def S(value):
    """Logical pixels (designed at 100 %) to physical pixels."""
    return int(round(value * SCALE))
LANCZOS = Image.Resampling.LANCZOS
BICUBIC = Image.Resampling.BICUBIC
TEXT_LOCK = threading.RLock()

PAIRS = (("#4c1d95", "#db2777"), ("#1e3a8a", "#06b6d4"), ("#7c2d12", "#f59e0b"),
         ("#064e3b", "#34d399"), ("#312e81", "#a78bfa"), ("#831843", "#fb7185"),
         ("#0c4a6e", "#38bdf8"), ("#3b0764", "#f97316"))

KINDS = {
    "primary": dict(bg=WHITE, fg="#0b0b0f", hbg="#e2e2e9"),
    "ghost": dict(bg=RAISED, fg=TEXT, hbg="#30303a"),
    "glass": dict(bg=(255, 255, 255, 34), fg=TEXT, hbg=(255, 255, 255, 64), border=(255, 255, 255, 46)),
    "accent": dict(bg=ACCENT, fg=WHITE, hbg="#6a6df7"),
    "chip": dict(bg=PANEL, fg=SOFT, hbg=RAISED, border=LINE, badge=DIM),
    "chip_on": dict(bg=WHITE, fg="#0b0b0f", hbg="#e2e2e9", badge="#6b6b78"),
    "nav": dict(bg=None, fg=MUTED, hbg="#1a1a21", hfg=TEXT, icon=MUTED, hicon=TEXT),
    "nav_on": dict(bg="#23232c", fg=TEXT, hbg="#292933", icon=ACCENT_SOFT),
    "quiet": dict(bg=None, fg=MUTED, hbg=RAISED, hfg=TEXT),
    "bare": dict(bg=None, fg=TEXT, hbg="#24242c", hfg=WHITE, icon=TEXT, hicon=WHITE),
    "danger": dict(bg=RAISED, fg="#fda4af", hbg="#3b1f28"),
    "live": dict(bg=LIVE_RED, fg=WHITE, hbg=LIVE_RED),
    "rec": dict(bg=LIVE_RED, fg=WHITE, hbg="#ff4458"),
    "toast": dict(bg="#2a2a35", fg=TEXT, hbg="#2a2a35", border="#3a3a46", icon=ACCENT_SOFT),
}


def rgba(color, alpha=255):
    if isinstance(color, tuple):
        return color if len(color) == 4 else (*color, alpha)
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


FONT_FILES = {"bold": ("segoeuib.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf"),
              "semibold": ("seguisb.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"),
              "regular": ("segoeui.ttf", "DejaVuSans.ttf")}
FONT_DIRS = (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path("/usr/share/fonts/truetype/dejavu"))


@lru_cache(maxsize=None)
def pil_font(px, weight="semibold"):
    """A Pillow font at `px` logical pixels, already scaled by SS."""
    size = max(1, round(px * SS))
    for name in FONT_FILES[weight]:
        for folder in FONT_DIRS:
            path = folder / name
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size)
                except OSError:
                    pass
    return ImageFont.load_default(size)


@lru_cache(maxsize=None)
def tk_font(size, bold=False):
    return tkfont.Font(family=FONT, size=size, weight="bold" if bold else "normal")


_CHAR_WIDTHS = {}


def text_width(text, size, bold=False):
    """Width of `text` in pixels, from a per-letter table (asking Tk for every title was slow on big lists)."""
    key = (size, bold)
    table = _CHAR_WIDTHS.get(key)
    if table is None:
        table = _CHAR_WIDTHS[key] = {}
    font = None
    total = 0
    for char in text:
        width = table.get(char)
        if width is None:
            font = font or tk_font(size, bold)
            width = table[char] = font.measure(char)
        total += width
    return total


@lru_cache(maxsize=20000)
def elide(text, size, width, bold=False):
    text = str(text)
    room = width * 0.98  # letters side by side are a little wider than measured one by one
    if text_width(text, size, bold) <= room:
        return text
    ellipsis = text_width("…", size, bold)
    total, cut = 0, 0
    for index, char in enumerate(text):
        total += text_width(char, size, bold)
        if total + ellipsis > room:
            break
        cut = index + 1
    return text[:cut].rstrip() + "…"


def label(parent, text, size=11, color=TEXT, bg=BG, bold=False, **kwargs):
    return tk.Label(parent, text=text, fg=color, bg=bg, font=(FONT, size, "bold" if bold else "normal"), **kwargs)


# ---------------------------------------------------------------- icons

def draw_icon(d, name, cx, cy, size, color):
    s = size / 24
    ox, oy = cx - size / 2, cy - size / 2

    def P(x, y):
        return ox + x * s, oy + y * s
    w = max(1, round(2 * s))

    def line(*points, width=w):
        pts = [P(*p) for p in points]
        d.line(pts, fill=color, width=width, joint="curve")
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=color)

    def circle(x, y, r, solid=False):
        box = (*P(x - r, y - r), *P(x + r, y + r))
        if solid:
            d.ellipse(box, fill=color)
        else:
            d.ellipse(box, outline=color, width=w)

    def arc(x, y, r, start, end):
        d.arc((*P(x - r, y - r), *P(x + r, y + r)), start, end, fill=color, width=w)

    def rect(x0, y0, x1, y1, radius=2.0, solid=False):
        d.rounded_rectangle((*P(x0, y0), *P(x1, y1)), radius * s,
                            fill=color if solid else None, outline=None if solid else color,
                            width=0 if solid else w)

    if name == "play":
        d.polygon([P(7.5, 4.5), P(19.5, 12), P(7.5, 19.5)], fill=color)
    elif name == "pause":
        rect(6, 5, 10, 19, 1.2, True)
        rect(14, 5, 18, 19, 1.2, True)
    elif name == "home":
        line((3.5, 11), (12, 4), (20.5, 11))
        line((6, 9.5), (6, 20), (18, 20), (18, 9.5))
        line((10, 20), (10, 15), (14, 15), (14, 20))
    elif name == "live":
        circle(12, 12, 2.2, True)
        arc(12, 12, 6, -45, 45)
        arc(12, 12, 6, 135, 225)
        arc(12, 12, 10, -40, 40)
        arc(12, 12, 10, 140, 220)
    elif name == "film":
        rect(3.5, 4, 20.5, 20, 2.5)
        line((8, 4), (8, 20))
        line((16, 4), (16, 20))
        line((3.5, 12), (8, 12))
        line((16, 12), (20.5, 12))
    elif name == "series":
        rect(3.5, 9, 20.5, 20.5, 2.5)
        line((6, 6), (18, 6))
        line((8.5, 3), (15.5, 3))
    elif name == "search":
        circle(10.5, 10.5, 6.5)
        line((15.5, 15.5), (20, 20))
    elif name in ("heart", "heart_fill"):
        pts = []
        for i in range(56):
            t = 2 * math.pi * i / 56
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append(P(12 + x * 0.52, 11.6 - y * 0.52))
        if name == "heart_fill":
            d.polygon(pts, fill=color)
        else:
            d.line(pts + pts[:2], fill=color, width=w, joint="curve")
    elif name == "download":
        line((12, 3.5), (12, 15))
        line((7, 10.5), (12, 15.5), (17, 10.5))
        line((4.5, 20), (19.5, 20))
    elif name == "wifi":
        arc(12, 19, 13, 228, 312)
        arc(12, 19, 8.5, 225, 315)
        arc(12, 19, 4, 220, 320)
        circle(12, 19, 1.4, True)
    elif name == "gear":
        for i in range(8):
            a = i * math.pi / 4
            line((12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)),
                 (12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)), width=round(w * 1.9))
        circle(12, 12, 6.8)
        circle(12, 12, 2.6)
    elif name == "info":
        circle(12, 12, 9)
        circle(12, 7.8, 1.25, True)
        line((12, 11), (12, 16.5))
    elif name == "back":
        line((15, 5), (8, 12), (15, 19))
    elif name == "next":
        line((9, 5), (16, 12), (9, 19))
    elif name == "plus":
        line((12, 5), (12, 19))
        line((5, 12), (19, 12))
    elif name == "check":
        line((5, 12.5), (10, 17), (19, 7))
    elif name == "guide":
        rect(3.5, 5, 20.5, 20.5, 2.5)
        line((3.5, 10), (20.5, 10))
        line((8, 3), (8, 7))
        line((16, 3), (16, 7))
    elif name == "expand":
        line((4, 9), (4, 4), (9, 4))
        line((15, 4), (20, 4), (20, 9))
        line((20, 15), (20, 20), (15, 20))
        line((9, 20), (4, 20), (4, 15))
    elif name == "skip_back":
        line((12, 6), (6, 12), (12, 18))
        line((18, 6), (12, 12), (18, 18))
    elif name == "skip_fwd":
        line((12, 6), (18, 12), (12, 18))
        line((6, 6), (12, 12), (6, 18))
    elif name == "volume":
        d.polygon([P(3.5, 9.5), P(7.5, 9.5), P(12.5, 5), P(12.5, 19), P(7.5, 14.5), P(3.5, 14.5)], fill=color)
        arc(12.5, 12, 4, -50, 50)
        arc(12.5, 12, 8, -50, 50)
    elif name == "mute":
        d.polygon([P(3.5, 9.5), P(7.5, 9.5), P(12.5, 5), P(12.5, 19), P(7.5, 14.5), P(3.5, 14.5)], fill=color)
        line((16, 9.5), (21, 14.5))
        line((21, 9.5), (16, 14.5))
    elif name == "clock":
        circle(12, 12, 9)
        line((12, 7), (12, 12), (15.5, 14))
    elif name == "lock":
        rect(5, 10.5, 19, 20.5, 2.5)
        arc(12, 10.5, 4.5, 180, 360)
        line((7.5, 10.5), (7.5, 9))
        line((16.5, 10.5), (16.5, 9))
        circle(12, 15.3, 1.3, True)
    elif name == "pencil":
        line((5, 19), (6, 15), (16, 5), (19, 8), (9, 18), (5, 19))
        line((14, 7), (17, 10))
    elif name == "cc":
        rect(3, 5.5, 21, 18.5, 3)
        arc(9, 12, 2.6, 45, 315)
        arc(15.5, 12, 2.6, 45, 315)
    elif name == "refresh":
        arc(12, 12, 7.5, 200, 520)
        line((19.5, 4.5), (19.5, 9), (15, 9))
    elif name == "trash":
        line((4.5, 6.5), (19.5, 6.5))
        line((9.5, 6.5), (9.5, 4), (14.5, 4), (14.5, 6.5))
        line((6.5, 6.5), (7.5, 20), (16.5, 20), (17.5, 6.5))
    elif name == "user":
        circle(12, 8.5, 4)
        arc(12, 21, 8, 200, 340)
    elif name == "swap":
        line((7, 9), (12, 4), (17, 9))
        line((7, 15), (12, 20), (17, 15))
    elif name == "phone":
        rect(7, 2.5, 17, 21.5, 2.5)
        line((10.5, 18.5), (13.5, 18.5))
    elif name == "cast":
        line((3, 8), (3, 6), (21, 6), (21, 19), (14, 19))
        arc(3, 19, 4, 270, 360)
        arc(3, 19, 8, 270, 360)
        circle(3.6, 18.4, 1.3, True)
    elif name == "pip":
        rect(2.5, 5, 21.5, 19, 2.5)
        rect(12, 11.5, 19, 16.5, 1.2, True)
    elif name == "trailer":
        rect(3, 5.5, 21, 18.5, 3)
        d.polygon([P(10, 9), P(15.5, 12), P(10, 15)], fill=color)
    elif name == "close":
        line((6, 6), (18, 18))
        line((18, 6), (6, 18))
    elif name == "folder":
        line((3.5, 18.5), (3.5, 6), (9.5, 6), (11.5, 8.5), (20.5, 8.5), (20.5, 18.5), (3.5, 18.5))
    elif name == "tv":
        rect(3, 5, 21, 17, 2.5)
        line((8, 20.5), (16, 20.5))
    elif name in ("eye", "eye_off"):
        d.ellipse((*P(2.5, 6.5), *P(21.5, 17.5)), outline=color, width=w)
        circle(12, 12, 3.2, solid=True)
        if name == "eye_off":
            line((4, 20), (20, 4))
    elif name == "speed":
        d.arc((*P(3, 5), *P(21, 23)), 180, 360, fill=color, width=w)
        line((12, 14), (16.5, 9))
        circle(12, 14, 1.6, solid=True)
    elif name == "record":
        circle(12, 12, 8.5)
        circle(12, 12, 4.5, solid=True)
    elif name == "grid":
        rect(3.5, 3.5, 11, 11, 2)
        rect(13, 3.5, 20.5, 11, 2)
        rect(3.5, 13, 11, 20.5, 2)
        rect(13, 13, 20.5, 20.5, 2)


# ---------------------------------------------------------------- pills

def render_pill(text="", icon=None, kind="ghost", hover=False, h=36, px=12.5, width=0, badge="",
                align="center", radius=None, weight="semibold", padx=None, disabled=False):
    style = KINDS[kind]
    h, px = S(h), px * SCALE
    width = S(width) if width else 0
    radius = None if radius is None else radius * SCALE
    padx = None if padx is None else padx * SCALE
    bg = style.get("hbg") if hover and style.get("hbg") is not None else style.get("bg")
    fg = style.get("hfg", style["fg"]) if hover else style["fg"]
    icon_color = (style.get("hicon") if hover and style.get("hicon") else style.get("icon")) or fg
    with TEXT_LOCK:
        font = pil_font(px, weight)
        small = pil_font(px * 0.92, "regular")
        icon_size = round(px * 1.35)
        if padx is None:
            padx = h * 0.42 if text else 0
        gap = round(px * 0.6) if icon and text else 0
        text_w = font.getlength(text) / SS if text else 0
        badge_w = small.getlength(badge) / SS + px * 0.55 if badge else 0
        content = (icon_size if icon else 0) + gap + text_w + badge_w
        W = int(width or (round(content + 2 * padx) if text else h))
        image = Image.new("RGBA", (W * SS, h * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(image)
        r = (h / 2 if radius is None else radius) * SS
        if bg is not None:
            border = style.get("border")
            d.rounded_rectangle((0, 0, W * SS - 1, h * SS - 1), r, fill=rgba(bg),
                                outline=rgba(border) if border else None, width=SS if border else 0)
        x = padx if align == "left" else (W - content) / 2
        cy = h / 2 * SS
        if icon:
            draw_icon(d, icon, (x + icon_size / 2) * SS, cy, icon_size * SS, rgba(icon_color))
            x += icon_size + gap
        if text:
            d.text((x * SS, cy), text, font=font, fill=rgba(fg), anchor="lm")
            x += text_w
        if badge:
            d.text(((x + px * 0.55) * SS, cy), badge, font=small, fill=rgba(style.get("badge", MUTED)), anchor="lm")
    image = image.resize((W, h), LANCZOS)
    if disabled:
        image.putalpha(image.getchannel("A").point(lambda v: v * 45 // 100))
    return image


@lru_cache(maxsize=2048)
def pill_photo(**options):
    return ImageTk.PhotoImage(render_pill(**options))


class Pill(tk.Label):
    """A rounded button with optional icon, hover state and keyboard support."""

    def __init__(self, parent, text="", command=None, kind="ghost", icon=None, h=36, px=12.5, width=0,
                 badge="", align="center", radius=None, bg=None, weight="semibold", padx=None):
        super().__init__(parent, bd=0, highlightthickness=0, bg=bg or parent.cget("bg"),
                         cursor="hand2" if command else "", takefocus=1 if command else 0)
        self.command, self.hover, self.enabled = command, False, True
        self.opts = dict(text=text, icon=icon, kind=kind, h=h, px=px, width=width, badge=badge,
                         align=align, radius=radius, weight=weight, padx=padx)
        self.redraw()
        if command:
            self.bind("<Enter>", lambda _: self._hover(True), add="+")
            self.bind("<Leave>", lambda _: self._hover(False), add="+")
            self.bind("<FocusIn>", lambda _: self._hover(True), add="+")
            self.bind("<FocusOut>", lambda _: self._hover(False), add="+")
            self.bind("<ButtonRelease-1>", self._click)
            self.bind("<Return>", lambda _: self.fire())
            self.bind("<space>", lambda _: self.fire())

    def _hover(self, flag):
        if self.winfo_exists():
            self.hover = flag
            self.redraw()

    def _click(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.fire()

    def fire(self):
        if self.enabled and self.command:
            self.command()

    def update_pill(self, **options):
        self.opts.update(options)
        self.redraw()

    def set_enabled(self, flag):
        self.enabled = flag
        self.configure(cursor="hand2" if flag and self.command else "")
        self.redraw()

    def redraw(self):
        self._photo = pill_photo(hover=self.hover and self.enabled, disabled=not self.enabled, **self.opts)
        self.configure(image=self._photo)


class Slider(tk.Canvas):
    """Thin rounded slider (volume, seek bar)."""

    def __init__(self, parent, length=200, value=0, maximum=100, command=None, release=None, bg=None,
                 fill=ACCENT, thumb=WHITE, track=RAISED):
        super().__init__(parent, width=S(length), height=S(20), bg=bg or parent.cget("bg"),
                         highlightthickness=0, cursor="hand2")
        self.maximum, self.value, self.fill, self.thumb, self.track = maximum, value, fill, thumb, track
        self.command, self.release, self.dragging = command, release, False
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._up)
        self.draw()

    def _value_at(self, x):
        length = max(1, self.winfo_width() - S(16))
        return max(0.0, min(1.0, (x - S(8)) / length)) * self.maximum

    def _press(self, event):
        self.dragging = True
        self._move(event)

    def _move(self, event):
        self.value = self._value_at(event.x)
        self.draw()
        if self.command:
            self.command(self.value)

    def _up(self, event):
        self._move(event)
        self.dragging = False
        if self.release:
            self.release(self.value)

    def set(self, value, maximum=None):
        if maximum:
            self.maximum = maximum
        if not self.dragging:
            self.value = value
            self.draw()

    def get(self):
        return self.value

    def draw(self):
        self.delete("all")
        length = max(S(24), self.winfo_width())
        ratio = max(0.0, min(1.0, self.value / self.maximum)) if self.maximum else 0
        m, y, k = S(8), S(10), S(6)
        x = m + (length - 2 * m) * ratio
        self.create_line(m, y, length - m, y, width=S(4), fill=self.track, capstyle="round")
        if ratio > 0:
            self.create_line(m, y, x, y, width=S(4), fill=self.fill, capstyle="round")
        self.create_oval(x - k, y - k, x + k, y + k, fill=self.thumb, outline="")


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def set_bg(widget, color, skip=()):
    for item in (widget, *descendants(widget)):
        if item in skip or isinstance(item, (tk.Entry, tk.Listbox)):
            continue
        try:
            item.configure(bg=color)
        except tk.TclError:
            pass


def bind_hover(widget, enter, leave):
    """Hover for a composite widget, without flicker when the pointer moves between children."""
    state = {"inside": False}
    prefix = str(widget) + "."

    def check(_=None):
        if not widget.winfo_exists():
            return
        try:
            x, y = widget.winfo_pointerxy()
            under = widget.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            under = None
        inside = under is not None and (under is widget or str(under).startswith(prefix))
        if inside != state["inside"]:
            state["inside"] = inside
            (enter if inside else leave)()
    for item in (widget, *descendants(widget)):
        item.bind("<Enter>", check, add="+")
        item.bind("<Leave>", lambda _: widget.after(15, check), add="+")


def bind_click(widget, command):
    for item in (widget, *descendants(widget)):
        if isinstance(item, Pill):
            continue
        item.bind("<ButtonRelease-1>", lambda _: command(), add="+")
        try:
            item.configure(cursor="hand2")
        except tk.TclError:
            pass


# ---------------------------------------------------------------- artwork

def seed_of(text):
    return int(hashlib.md5(str(text).encode("utf-8", "replace")).hexdigest()[:8], 16)


def gradient(size, first, second, angle=35):
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    values = [x / 31 * ca + y / 31 * sa for y in range(32) for x in range(32)]
    low, high = min(values), max(values)
    mask = Image.new("L", (32, 32))
    mask.putdata([int(255 * (v - low) / (high - low or 1)) for v in values])
    mask = mask.resize(size, BICUBIC)
    return Image.composite(Image.new("RGB", size, second), Image.new("RGB", size, first), mask)


def wrap(text, font, width, max_lines):
    words, lines, line = str(text).split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.getlength(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    for index, value in enumerate(lines):
        while value and font.getlength(value) > width:
            value = value[:-2] + "…"
        lines[index] = value
    return lines


def initials(title):
    words = [w for w in str(title).replace("-", " ").split() if w[:1].isalnum()]
    letters = "".join(w[0] for w in words[:2]).upper()
    return letters or str(title)[:2].upper() or "TV"


@lru_cache(maxsize=600)
def poster_art(title, kind, w, h):
    """Colourful generated artwork for titles that have no poster."""
    seed = seed_of(title)
    first, second = PAIRS[seed % len(PAIRS)]
    base = gradient((w, h), first, second, 25 + seed % 50)
    glow = Image.new("L", (w, h), 0)
    gx, gy, r = (seed >> 4) % w, (seed >> 9) % max(1, h // 2), int(max(w, h) * 0.45)
    ImageDraw.Draw(glow).ellipse((gx - r, gy - r, gx + r, gy + r), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(max(w, h) / 5))
    base = Image.composite(Image.new("RGB", (w, h), "#ffffff"), base, glow)
    shade = Image.new("L", (1, 64))
    shade.putdata([int(255 * max(0.0, (y / 63 - 0.3) / 0.7) ** 1.5 * 0.82) for y in range(64)])
    base = Image.composite(Image.new("RGB", (w, h), "#06060a"), base, shade.resize((w, h), BICUBIC))
    big = base.resize((w * SS, h * SS), BICUBIC)
    d = ImageDraw.Draw(big)
    pad = max(10, w // 12)
    with TEXT_LOCK:
        font = pil_font(max(12, min(w, h * 0.75) / 8.5), "bold")
        lines = wrap(title, font, (w - 2 * pad) * SS, 3)
        line_h = font.size * 1.12
        y = h * SS - pad * SS - line_h * len(lines)
        for line in lines:
            d.text((pad * SS, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_h
        tag = {"movie": "FILM", "series": "SERIE", "live": "LIVE"}.get(kind, "")
        if tag:
            d.text((pad * SS, pad * SS), tag, font=pil_font(9 * SCALE, "bold"), fill=(255, 255, 255, 190))
    return big.resize((w, h), LANCZOS)


def logo_badge(title, size, logo=None):
    """Rounded square with the channel logo, or coloured initials."""
    if logo is not None:
        square = Image.new("RGB", (size, size), "#f1f1f5")
        inner = logo.copy()
        inner.thumbnail((int(size * 0.76), int(size * 0.76)), LANCZOS)
        square.paste(inner, ((size - inner.width) // 2, (size - inner.height) // 2),
                     inner if inner.mode == "RGBA" else None)
    else:
        seed = seed_of(title)
        first, second = PAIRS[seed % len(PAIRS)]
        square = gradient((size, size), first, second, 40).resize((size * SS, size * SS), BICUBIC)
        with TEXT_LOCK:
            ImageDraw.Draw(square).text((size * SS / 2, size * SS / 2), initials(title),
                                        font=pil_font(size * 0.36, "bold"), fill=(255, 255, 255, 255), anchor="mm")
        square = square.resize((size, size), LANCZOS)
    return round_corners(square, size * 0.24)


def channel_tile(title, w, h, logo=None):
    base = gradient((w, h), "#202029", "#131318", 90).convert("RGBA")
    side = int(min(w, h) * 0.46)
    badge = logo_badge(title, side, logo)
    base.alpha_composite(badge, ((w - side) // 2, (h - side) // 2 - int(h * 0.02)))
    return base.convert("RGB")


def round_corners(image, radius, ring=None, progress=None):
    w, h = image.size
    big = image.convert("RGBA").resize((w * SS, h * SS), BICUBIC)
    overlay = Image.new("RGBA", big.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    if progress is not None:
        m, bar = S(10) * SS, S(4) * SS
        y = big.height - m - bar
        d.rounded_rectangle((m, y, big.width - m, y + bar), bar / 2, fill=(255, 255, 255, 80))
        end = m + (big.width - 2 * m) * max(0.0, min(1.0, progress))
        if end > m + bar:
            d.rounded_rectangle((m, y, end, y + bar), bar / 2, fill=rgba(ACCENT_SOFT))
    if ring:
        width = S(2) * SS
        d.rounded_rectangle((width / 2, width / 2, big.width - width / 2, big.height - width / 2),
                            radius * SS, outline=rgba(ring), width=width)
    big = Image.alpha_composite(big, overlay)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big.width - 1, big.height - 1), radius * SS, fill=255)
    big.putalpha(ImageChops.multiply(big.getchannel("A"), mask))
    return big.resize((w, h), LANCZOS)


def card_images(base, ratio=None):
    normal = round_corners(base, S(10), progress=ratio)
    hover = round_corners(ImageEnhance.Brightness(base).enhance(1.12), S(10), ring=ACCENT_SOFT, progress=ratio)
    return normal, hover


class LazyPhotos:
    """Tk pictures for a list of PIL images, made on first use: turning an image into a Tk picture has to happen
    on the screen thread, so pictures nobody sees (a hover state) should not cost anything."""

    def __init__(self, images):
        self.images = list(images)
        self.photos = [None] * len(self.images)
        self[0]

    def __getitem__(self, index):
        if self.photos[index] is None:
            self.photos[index] = ImageTk.PhotoImage(self.images[index])
            if all(self.photos):
                self.images = []
        return self.photos[index]

    def __len__(self):
        return len(self.photos)


@lru_cache(maxsize=32)
def placeholder_photo(w, h, color=PANEL, radius=10):
    return ImageTk.PhotoImage(round_corners(Image.new("RGB", (w, h), color), S(radius)))


def hero_fallback(size):
    w, h = size
    glow = Image.new("RGB", (1200, 500), "#120f1c")
    ImageDraw.Draw(glow).ellipse((520, -235, 1440, 760), fill="#4c1d95")
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    draw = ImageDraw.Draw(glow)
    for inset in range(14):
        draw.rounded_rectangle((640 + inset * 18, -92 + inset * 19, 1390 - inset * 18, 615 - inset * 17),
                               radius=max(15, 151 - inset * 7),
                               outline=(100 - inset * 4, 104 - inset * 4, 245 - inset * 8), width=2)
    draw.polygon(((935, 160), (935, 340), (1090, 250)), fill=ACCENT_SOFT)
    return ImageOps.fit(glow, (w, h))


def hero_background(art, item, size):
    w, h = size
    if art is not None:
        base = ImageOps.fit(art, size, centering=(0.5, 0.3))
        if art.height > art.width * 0.9:
            base = base.filter(ImageFilter.GaussianBlur(5))
        base = ImageEnhance.Brightness(base).enhance(0.92)
    elif item is not None:
        seed = seed_of(item.get("title"))
        first, second = PAIRS[seed % len(PAIRS)]
        small = gradient((120, 60), first, second, 20)
        small = ImageEnhance.Brightness(small).enhance(0.75)
        base = small.resize(size, BICUBIC)
    else:
        base = hero_fallback(size)
    mask = Image.new("L", (96, 48))
    data = []
    for y in range(48):
        v = y / 47
        for x in range(96):
            u = x / 95
            left = max(0.0, (0.75 - u) / 0.75) ** 1.15 * 0.97
            bottom = max(0.0, (v - 0.42) / 0.58) ** 1.7
            top = max(0.0, (0.2 - v) / 0.2) ** 2 * 0.45
            data.append(int(255 * max(0.2, left, bottom, top)))
    mask.putdata(data)
    return Image.composite(Image.new("RGB", size, BG), base, mask.resize(size, BICUBIC))


def render_logo(height=34):
    """The Zono wordmark (light version for the dark interface)."""
    h = S(height)
    try:
        image = Image.open(Path(__file__).with_name("zono_logo.png")).convert("RGBA")
    except OSError:
        image = Image.new("RGBA", (int(4.4 * h), h), (0, 0, 0, 0))
        with TEXT_LOCK:
            ImageDraw.Draw(image).text((0, h / 2), "zono", font=pil_font(21 * SCALE, "bold"), fill=rgba(TEXT), anchor="lm")
        return image
    return image.resize((max(1, round(image.width * h / image.height)), h), LANCZOS)


def render_mark(size):
    """The square Zono app icon."""
    try:
        image = Image.open(Path(__file__).with_name("zono_mark.png")).convert("RGBA")
    except OSError:
        image = Image.new("RGBA", (size, size), rgba(ACCENT))
    return image.resize((size, size), LANCZOS)


def render_round_button(base, icon, hover=False):
    """A round floating button drawn onto `base` (what lies underneath), so no square shows around it."""
    w, h = base.size
    layer = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = (58, 58, 70, 235) if hover else (30, 30, 38, 215)
    d.ellipse((SS, SS, w * SS - SS - 1, h * SS - SS - 1), fill=fill, outline=(255, 255, 255, 40 if hover else 26), width=SS)
    draw_icon(d, icon, w / 2 * SS, h / 2 * SS, S(18) * SS, rgba(TEXT))
    out = base.convert("RGBA")
    out.alpha_composite(layer.resize((w, h), LANCZOS))
    return out.convert("RGB")


def render_card(base, radius, fill, outline=None, icon=None, icon_x=None):
    """A rounded card drawn onto `base`, so its corners blend with the page behind it."""
    w, h = base.size
    layer = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius * SS, fill=rgba(fill),
                        outline=rgba(outline) if outline else None, width=SS)
    if icon:
        draw_icon(d, icon, (icon_x or S(20)) * SS, h / 2 * SS, S(16) * SS, rgba(MUTED))
    out = base.convert("RGBA")
    out.alpha_composite(layer.resize((w, h), LANCZOS))
    return out.convert("RGB")


def render_field(w, h, icon=None):
    image = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), S(10) * SS, fill=rgba(PANEL), outline=rgba(LINE), width=SS)
    if icon:
        draw_icon(d, icon, S(20) * SS, h / 2 * SS, S(16) * SS, rgba(MUTED))
    return image.resize((w, h), LANCZOS)


def render_switch(on, hover=False):
    w, h = S(42), S(24)
    image = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    track = ACCENT if on else ("#3a3a45" if hover else RAISED)
    d.rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), h * SS / 2, fill=rgba(track))
    knob = h * SS - 6 * SS * SCALE
    x = (w * SS - h * SS + 3 * SS * SCALE) if on else 3 * SS * SCALE
    d.ellipse((x, 3 * SS * SCALE, x + knob, 3 * SS * SCALE + knob), fill=rgba(WHITE))
    return image.resize((w, h), LANCZOS)


@lru_cache(maxsize=8)
def switch_photo(on, hover=False):
    return ImageTk.PhotoImage(render_switch(on, hover))


class Switch(tk.Label):
    def __init__(self, parent, value=False, command=None):
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("bg"), cursor="hand2", takefocus=1)
        self.value, self.command, self.hover = bool(value), command, False
        self.bind("<Enter>", lambda _: self._set_hover(True))
        self.bind("<Leave>", lambda _: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda _: self.toggle())
        self.bind("<space>", lambda _: self.toggle())
        self.redraw()

    def _set_hover(self, flag):
        self.hover = flag
        self.redraw()

    def toggle(self):
        self.value = not self.value
        self.redraw()
        if self.command:
            self.command(self.value)

    def redraw(self):
        self.configure(image=switch_photo(self.value, self.hover))


def round_rect(canvas, x0, y0, x1, y1, r, **options):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    points = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
              x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
    return canvas.create_polygon(points, smooth=True, splinesteps=10, **options)


def rank_geometry(rank, h):
    """Width of the big outlined number in front of a Top 10 poster, and how far the poster overlaps it."""
    with TEXT_LOCK:
        font = pil_font(h * 0.6, "bold")
        text_w = font.getlength(str(rank)) / SS
    return int(text_w + S(6)), int(text_w * 0.16)


def rank_images(images, rank, h):
    number_w, overlap = rank_geometry(rank, h)
    number = Image.new("RGBA", (number_w * SS, h * SS), (0, 0, 0, 0))
    with TEXT_LOCK:
        ImageDraw.Draw(number).text((S(2) * SS, h * SS * 0.97), str(rank), font=pil_font(h * 0.6, "bold"),
                                    anchor="ls", fill=rgba(BG), stroke_width=max(1, S(3)) * SS,
                                    stroke_fill=rgba("#6a6a78"))
    number = number.resize((number_w, h), LANCZOS)
    result = []
    for image in images:
        canvas = Image.new("RGBA", (number_w - overlap + image.width, h), (0, 0, 0, 0))
        canvas.alpha_composite(number, (0, 0))
        canvas.alpha_composite(image.convert("RGBA"), (number_w - overlap, 0))
        result.append(canvas)
    return result


@lru_cache(maxsize=16)
def rank_placeholder(rank, w, h):
    base = round_corners(Image.new("RGB", (w, h), PANEL), S(10))
    return ImageTk.PhotoImage(rank_images([base], rank, h)[0])


AVATARS = (("#7c3aed", "#db2777"), ("#2563eb", "#06b6d4"), ("#059669", "#a3e635"),
           ("#ea580c", "#facc15"), ("#e11d48", "#fb923c"), ("#0f766e", "#38bdf8"))


def render_avatar(color, size, kids=False, ring=False, dim=False, icon=None):
    """A friendly face on a coloured rounded square, Netflix style."""
    first, second = AVATARS[int(color) % len(AVATARS)]
    big = size * SS
    base = gradient((size, size), first, second, 40).resize((big, big), BICUBIC).convert("RGBA")
    d = ImageDraw.Draw(base)
    white = (255, 255, 255, 235)
    u = big / 24
    d.rounded_rectangle((7.2 * u, 8 * u, 9.2 * u, 11.6 * u), u, fill=white)
    d.rounded_rectangle((14.8 * u, 8 * u, 16.8 * u, 11.6 * u), u, fill=white)
    d.arc((7 * u, 9.5 * u, 17 * u, 17.5 * u), 20, 160, fill=white, width=max(1, int(1.3 * u)))
    if kids:
        star = [(19.5 * u + 2.6 * u * math.cos(math.radians(a)) * (1 if k % 2 == 0 else 0.45),
                 4.5 * u + 2.6 * u * math.sin(math.radians(a)) * (1 if k % 2 == 0 else 0.45))
                for k, a in enumerate(range(-90, 270, 36))]
        d.polygon(star, fill=(255, 236, 140, 255))
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    o = ImageDraw.Draw(overlay)
    if dim:
        o.rectangle((0, 0, big, big), fill=(0, 0, 0, 120))
    if icon:
        draw_icon(o, icon, big / 2, big / 2, big * 0.36, (255, 255, 255, 255))
    base = Image.alpha_composite(base, overlay)
    if ring:
        ImageDraw.Draw(base).rounded_rectangle((SS, SS, big - SS, big - SS), big * 0.12,
                                               outline=(255, 255, 255, 255), width=max(2, int(big * 0.025)))
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), big * 0.12, fill=255)
    base.putalpha(ImageChops.multiply(base.getchannel("A"), mask))
    return base.resize((size, size), LANCZOS)


@lru_cache(maxsize=64)
def avatar_photo(color, size, kids=False, ring=False, dim=False, icon=None):
    return ImageTk.PhotoImage(render_avatar(color, size, kids, ring, dim, icon))


@lru_cache(maxsize=8)
def add_tile_photo(size, hover=False):
    big = size * SS
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((SS, SS, big - SS, big - SS), big * 0.12, fill=rgba("#26262f" if hover else PANEL),
                        outline=rgba("#4a4a56" if hover else LINE), width=max(2, int(big * 0.012)))
    draw_icon(d, "plus", big / 2, big / 2, big * 0.34, rgba(TEXT if hover else MUTED))
    return ImageTk.PhotoImage(image.resize((size, size), LANCZOS))


def render_dots(count, filled, size=None, error=False):
    size = size or S(18)
    gap = S(18)
    w = count * size + (count - 1) * gap
    image = Image.new("RGBA", (w * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    for k in range(count):
        x = k * (size + gap) * SS
        box = (x + SS, SS, x + size * SS - SS, size * SS - SS)
        if k < filled:
            d.ellipse(box, fill=rgba(LIVE_RED if error else WHITE))
        else:
            d.ellipse(box, outline=rgba(LIVE_RED if error else "#6a6a78"), width=max(2, S(2)) * SS)
    return image.resize((w, size), LANCZOS)


def person_avatar(name, size, photo=None):
    """Round portrait for the cast row: a photo when available, otherwise coloured initials."""
    big = size * SS
    if photo is not None:
        base = ImageOps.fit(photo.convert("RGB"), (big, big), centering=(0.5, 0.25)).convert("RGBA")
    else:
        seed = seed_of(name)
        first, second = PAIRS[seed % len(PAIRS)]
        base = gradient((size, size), first, second, 40).resize((big, big), BICUBIC).convert("RGBA")
        with TEXT_LOCK:
            ImageDraw.Draw(base).text((big / 2, big / 2), initials(name), font=pil_font(size * 0.34, "bold"),
                                      fill=(255, 255, 255, 255), anchor="mm")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    base.putalpha(mask)
    return base.resize((size, size), LANCZOS)


def window_style(window, rounded=False, no_activate=False, tool=True):
    """Windows only: rounded corners (Windows 11) and a floating window that never steals the keyboard."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        if no_activate or tool:
            user32 = ctypes.windll.user32
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_long.restype = set_long.restype = ctypes.c_ssize_t
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            extra = get_long(hwnd, -20)
            if no_activate:
                extra |= 0x08000000  # WS_EX_NOACTIVATE
            if tool:
                extra |= 0x00000080  # WS_EX_TOOLWINDOW: no taskbar button
            set_long(hwnd, -20, extra)
        if rounded:
            preference = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(preference),
                                                       ctypes.sizeof(preference))
    except Exception:
        pass

