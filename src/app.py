import ctypes
import os
import re
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from pathlib import Path
from queue import SimpleQueue
from time import monotonic, perf_counter, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit

from PIL import Image, ImageOps, ImageTk
import catalogue as data
import shutil
import sys
import player as engine_module
from player import Player
import cast
import qr
import remote
import countries
import tmdb
import ui
import webview
import webbrowser
import threading
from ui import (BG, SIDE, PANEL, RAISED, LINE, TEXT, SOFT, MUTED, DIM, ACCENT, ACCENT_SOFT, LIVE_RED, FONT,
                Pill, Slider, Switch, S, label, elide)

VERSION = "2.1.2"
TABS = {"home": "Ontdekken", "live": "Live TV", "guide": "TV-gids", "movie": "Films", "series": "Series",
        "favorites": "Favorieten", "downloads": "Downloads", "settings": "Instellingen"}
SAFE_MODE = False
_TRACE_START = monotonic()


def trace(step):
    """Short diary of the first minute after starting (start.log), to find out where a start gets stuck."""
    if monotonic() - _TRACE_START > 90:
        return
    try:
        with (data.ROOT / "start.log").open("a", encoding="utf-8") as out:
            out.write(f"{monotonic() - _TRACE_START:7.2f}s  {step}\n")
    except OSError:
        pass

HOME_SECTIONS = (
    ("welcome", "Begroeting en ‘Kijk verder naar’", "Goedemorgen + wat je net keek, met één klik verder"),
    ("resume", "Verder kijken", "Films en afleveringen die je nog niet uitkeek"),
    ("channels", "Mijn zenders", "Je favoriete zenders, met wat er nu speelt"),
    ("mylist", "Mijn lijst", "Films en series met een hartje"),
    ("groups", "Mijn categorieën", "Een rij per categorie die je volgt"),
    ("because", "Omdat je … keek", "Meer uit het genre van wat je laatst keek"),
    ("country", "Uit jouw landen", "Zenders en titels uit de landen die je koos"),
    ("top", "Top 10 films", "De best beoordeelde films"),
    ("movies", "Beste films", "Meer goed beoordeelde films"),
    ("series", "Series", "De best beoordeelde series"),
    ("live", "Live TV", "Zenders, met je laatste zender vooraan"),
    ("newest", "Nieuw toegevoegd", "Wat je provider onlangs toevoegde"),
    ("genres", "Populaire genres", "Rijen voor de grootste filmcategorieën"),
)
KIND_LABEL = {"movie": "Film", "series": "Serie", "live": "Live TV", "catchup": "Terugkijken"}
HERO_H = 480
SIDEBAR_W = 236
CARD = (156, 234)
WIDE = (232, 130)
GUIDE_TTL = 900
KIDS_WORDS = ("adult", "xxx", "18+", "+18", "porn", "erotic", "erotik", "sex", "playboy", "hustler", "nsfw",
              "brazzers", "redlight", "for adults", "volwassen", "hot girls")


def error_text(error):
    if isinstance(error, HTTPError):
        return f"De IPTV-server geeft HTTP {error.code}. Controleer je bron en inloggegevens."
    if isinstance(error, (URLError, TimeoutError)):
        return "De IPTV-server is niet bereikbaar. Controleer je verbinding en serveradres."
    if type(error) is ValueError:
        return str(error)
    return f"Deze actie is mislukt ({type(error).__name__})."


def number(value):
    return f"{value:,}".replace(",", ".")


def clock(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def minutes_left(seconds):
    return f"nog {max(1, round(max(0, seconds) / 60))} min"


def hhmm(stamp):
    return datetime.fromtimestamp(stamp).strftime("%H:%M") if 0 < stamp < 4102444800 else ""


def download_image(url, limit=5 * 1024 * 1024):
    data.check_url(url)
    with urlopen(Request(url, headers={"User-Agent": "Zono/1.1"}), timeout=6) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        return None
    image = Image.open(BytesIO(raw))
    if image.width * image.height > 30_000_000:
        return None
    image.load()
    return image


def cover(url, size, contain=False):
    image = download_image(url)
    if image is None:
        return None
    if contain:
        image = image.convert("RGBA")
        image.thumbnail(size, ui.LANCZOS)
        return image
    return ImageOps.fit(image.convert("RGB"), size)


def backdrop(url):
    image = download_image(url, 8 * 1024 * 1024)
    if image is None:
        return None
    image = image.convert("RGB")
    image.thumbnail((2200, 1400), ui.LANCZOS)
    return image


def safe(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception:
        return None


def is_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def art_url(item, *keys):
    for key in keys:
        if is_url(item.get(key)):
            return item[key]
    return None


def first_url(value):
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if is_url(v)), None)
    return value if is_url(value) else None


def score(item):
    try:
        return float(item.get("rating") or 0)
    except (TypeError, ValueError):
        return 0.0


def added_of(item):
    try:
        return int(item.get("added") or 0)
    except (TypeError, ValueError):
        return 0


def summarize(info):
    year = str(info.get("releasedate") or info.get("releaseDate") or info.get("year") or "")[:4]
    parts = [year if year.strip("0") else "", info.get("genre"), info.get("duration")]
    rating = str(info.get("rating") or "")
    if rating and rating not in ("0", "0.0", "N/A"):
        parts.append(f"★ {rating}")
    plot = str(info.get("plot") or info.get("description") or "").strip()
    if len(plot) > 330:
        plot = plot[:329].rsplit(" ", 1)[0] + "…"
    genres = [g.strip() for g in re.split(r"[,/|&]", str(info.get("genre") or "")) if g.strip()]
    trailer = str(info.get("youtube_trailer") or "").strip()
    return {"meta": "  ·  ".join(str(p) for p in parts if p), "plot": plot, "genres": genres,
            "trailer": trailer if re.fullmatch(r"[\w-]{6,20}", trailer) else "", "year": year if year.strip("0") else ""}


_FIELD_PHOTOS = {}


def ui_field_photo(width, height):
    key = (width, height)
    if key not in _FIELD_PHOTOS:
        _FIELD_PHOTOS[key] = ImageTk.PhotoImage(ui.render_field(width, height, "search"))
    return _FIELD_PHOTOS[key]


def current_program(rows, moment=None):
    moment = moment or time()
    return next((r for r in rows if r["start"] <= moment < r["end"]), None)


class Zono:
    def __init__(self, root, profiles):
        self.root = root
        self.profiles = profiles
        self.profile = None
        self.state = {}
        self.source = None
        self.preferences = {}
        self.set_library([])
        self.favorites, self.progress, self.downloaded = {}, {}, []
        self.volume = 75
        self.tab, self.limit = "home", 30
        self.category = None
        self.engine = None
        self.recordings, self.recorders = [], {}
        self.refreshed_profiles = set()
        self.watched = {}
        self.buffer_failed = False
        self.session = None
        self.listeners = {}
        self.tick_job = self.place_job = None
        self.stage_mode, self.stage_target = "hidden", None
        self.muted = False
        self.detail_item = None
        self.feature_index = 0
        self.results = SimpleQueue()
        self.workers = ThreadPoolExecutor(max_workers=2)
        self.art_workers = ThreadPoolExecutor(max_workers=5)
        self.guide_workers = ThreadPoolExecutor(max_workers=4)
        self.download_workers = ThreadPoolExecutor(max_workers=1)
        self.art_jobs = []
        self.generation = 0
        self.search_job = self.rotate_job = self.resize_job = self.layout_job = None
        self.hero_canvas = None
        self.hero_art = {}
        self.guide_cache = {}
        self.live_nav = self.live_layout = None
        self.episode_anchor = None
        self.toast_widget = None
        self.player_view = self.player_keys = self.player_close = self.sheet_close = None
        self.player_show = self.player_full_toggle = None
        self.player_full = False
        self.live_slot = None
        self.autoplayed = False
        self.refreshing = False
        self.has_grid = False
        self.last_width = 0
        self.art_cache = OrderedDict()
        self.logo_cache = OrderedDict()
        self.scroll_target = None
        self.scroll_job = self.defer_job = None
        self.deferred = []
        self.overlay_keys = None
        self.picker = None
        self.trailer_view = None
        self.multiview = None
        self.search_open = False
        self.search_rows, self.search_index = [], -1
        self.reconnect_job = None
        self.guide_day = 0
        self.zap_digits, self.zap_job, self.zap_overlay = "", None, None
        self.remote = remote.RemoteServer(lambda: (self.profile.get("name", "") if self.profile else "",
                                                   self.library, self.source), lambda: self.share_token,
                                          lambda: self.root.after(0, self.stop_playback))
        self.share_token = ""
        self.casting = None
        self.genre_cache, self.genre_save_job, self.enriching = {}, None, {}
        self.tmdb_cache = {}
        self.info_workers = ThreadPoolExecutor(max_workers=3)
        self.download_jobs = OrderedDict()
        self.pip_window = None

        root.title(f"Zono  ·  Desktop {VERSION}")
        size_window(root)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use("clam")
        for name, orient in (("Zono.Vertical.TScrollbar", "Vertical"), ("Zono.Horizontal.TScrollbar", "Horizontal")):
            style.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": "nswe", "children": [
                (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            style.configure(name, background="#2a2a33", troughcolor=BG, bordercolor=BG, lightcolor="#2a2a33",
                            darkcolor="#2a2a33", gripcount=0, width=S(9), arrowsize=S(9), relief="flat")
            style.map(name, background=[("active", "#3a3a45")])
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.build_sidebar()
        main = tk.Frame(root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.main = main
        self.canvas = tk.Canvas(main, bg=BG, highlightthickness=0, yscrollincrement=S(24))
        scrollbar = ttk.Scrollbar(main, orient="vertical", command=self.canvas.yview, style="Zono.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=lambda *a: (scrollbar.set(*a), self.queue_place()))
        self.content = tk.Frame(self.canvas, bg=BG)
        self.viewport = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self.content_resized)
        self.canvas.bind("<Configure>", self.canvas_resized)
        main.bind("<Configure>", lambda _: self.queue_place(), add="+")
        self.build_stage()
        self.build_search()
        root.bind("<MouseWheel>", self.wheel)
        root.bind("<Shift-MouseWheel>", self.hwheel)
        root.bind("<Button-4>", lambda e: self.wheel(e, 120))
        root.bind("<Button-5>", lambda e: self.wheel(e, -120))
        root.bind("<Key>", self.route_key)
        root.bind("<Up>", lambda e: self.arrow(e, -1))
        root.bind("<Down>", lambda e: self.arrow(e, 1))
        root.bind("<Escape>", self.escape)
        root.bind("<slash>", self.slash)
        root.bind("<Control-f>", lambda _: self.open_search())
        root.bind("<Button-1>", self.click_outside, add="+")
        root.report_callback_exception = self.report_error
        root.bind("<Unmap>", self.root_state_changed, add="+")
        root.bind("<Map>", self.root_state_changed, add="+")
        root.after(50, self.poll)
        root.after(5000, self.recording_tick)
        everyone = profiles["profiles"]
        last = next((p for p in everyone if p["id"] == profiles.get("last")), everyone[0])
        if len(everyone) == 1 and not last.get("pin"):
            self.enter_profile(last, verified=True)
        else:
            self.show_profiles()

    # ------------------------------------------------------------ profiles

    def profile_by_id(self, profile_id):
        return next((p for p in self.profiles["profiles"] if p["id"] == profile_id), None)

    def enter_profile(self, profile, verified=False):
        if profile.get("pin") and not verified:
            self.ask_pin(profile, lambda: self.enter_profile(profile, True))
            return
        if self.picker is not None and self.picker.winfo_exists():
            # show at once that the click landed; loading a big library can take a moment
            busy = tk.Frame(self.picker, bg=BG)
            busy.place(relx=.5, rely=.86, anchor="center")
            label(busy, f"{profile.get('name', '')} wordt geladen…", 12, SOFT, BG, True).pack()
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            self.root.update()
            self.root.config(cursor="")
        if self.session:
            self.stop_playback()
        if self.player_close:
            self.player_close(minimize=False)
        data.use_profile(profile)
        trace(f"profiel {profile.get('name')} laden")
        try:
            state = data.load()
            trace(f"bibliotheek gelezen: {len(state.get('library', []))} titels")
        except (OSError, ValueError) as error:
            data.log_error(f"Profiel {profile.get('name')} kon niet worden geladen: {error!r}")
            state = {}
        self.profile = profile
        self.state = state
        self.source = state.get("source")
        self.preferences = data.read_json(data.STATE.with_name("preferences.json"), {})
        self.volume = int(self.preferences.get("volume", 75))
        self.favorites = state.get("favorites", {})
        self.progress = state.get("progress", {})
        self.downloaded = data.unseal(data.read_json(data.STATE.with_name("downloads.json"), []), self.source)
        recordings = data.unseal(data.read_json(data.STATE.with_name("recordings.json"), []), self.source)
        running = [r for r in getattr(self, "recordings", []) if r.get("id") in getattr(self, "recorders", {})]
        loaded = [r for r in recordings if isinstance(r, dict)] if isinstance(recordings, list) else []
        self.recordings = loaded + [r for r in running if r["id"] not in {x.get("id") for x in loaded}]
        watched = data.read_json(data.STATE.with_name("watched.json"), {})
        self.watched = watched if isinstance(watched, dict) else {}
        self.genre_cache = data.read_json(data.STATE.with_name("genres.json"), {})
        if not isinstance(self.genre_cache, dict):
            self.genre_cache = {}
        self.tmdb_cache, self.enriching = {}, {}
        self.purge_downloads()
        self.set_library(state.get("library", []))
        trace("bibliotheek klaargezet")
        self.hero_art.clear()
        self.guide_cache.clear()
        self.autoplayed = False
        self.feature_index = 0
        self.profiles["last"] = profile["id"]
        try:
            data.save_profiles(self.profiles)
        except OSError:
            pass
        self.update_profile_chip()
        self.close_profiles()
        self.root.title(f"Zono  ·  {profile.get('name', '')}")
        startup = self.preferences.get("startup")
        trace(f"startpagina {startup or 'home'} tekenen")
        self.select(startup if startup in ("home", "live", "guide", "movie", "series") else "home")
        trace("startpagina getekend")
        if data.NOTICE:
            self.root.after(500, lambda: self.toast(elide(data.NOTICE, 10, S(560), True), "close"))
        if SAFE_MODE and not getattr(self, "safe_told", False):
            self.safe_told = True
            data.log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Zono {VERSION} werd vorige keer niet normaal afgesloten · "
                           "veilige start (geen automatisch afspelen, live pauzeren tijdelijk uit)")
            self.root.after(900, lambda: self.toast("Zono werd vorige keer niet goed afgesloten · veilige start: live pauzeren staat even uit",
                                                    "info"))
        if data.needs_protection(state):
            self.run(lambda: data.save_state(state), lambda _: None, lambda _: None)
        self.share_token = self.preferences.get("share_token") or ""
        if not self.share_token:
            self.share_token = uuid4().hex[:12]
            self.remember_preference("share_token", self.share_token)
        if self.preferences.get("share_enabled") and not self.remote.running:
            try:
                self.remote.start()
            except OSError:
                pass
        # once every time Zono opens: fetch the provider's latest channels, films and series in the background
        if self.source and profile["id"] not in self.refreshed_profiles:
            self.refreshed_profiles.add(profile["id"])
            self.root.after(6000, lambda: self.refresh_library(silent=True, quiet_toast=True))

    def blocked_words(self):
        words = [w.strip().casefold() for w in str(self.preferences.get("hidden_words", "")).split(",") if w.strip()]
        if self.profile and self.profile.get("kids"):
            words += list(KIDS_WORDS)
        return tuple(words)

    def update_profile_chip(self):
        profile = self.profile
        if not profile:
            return
        self.chip_avatar.configure(image=ui.avatar_photo(profile.get("color", 0), S(34), profile.get("kids", False)))
        self.chip_name.configure(text=elide(profile.get("name", ""), 11, S(110), True))
        self.chip_sub.configure(text="Kinderprofiel" if profile.get("kids") else "Profiel wisselen")
        kids = bool(profile.get("kids"))
        source = self.nav.get("source")
        if source is not None:
            if kids:
                source.pack_forget()
            elif not source.winfo_ismapped():
                source.pack(anchor="w", padx=S(16), pady=1, before=self.nav["settings"])

    def close_profiles(self):
        if self.picker is not None and self.picker.winfo_exists():
            self.picker.destroy()
        self.picker = None
        self.overlay_keys = None
        self.queue_place()

    def show_profiles(self, manage=False):
        """Full-window "Wie kijkt er?" screen."""
        if self.sheet_close:
            self.sheet_close()
        self.close_search()
        if self.picker is not None and self.picker.winfo_exists():
            self.picker.destroy()
        picker = tk.Frame(self.root, bg=BG)
        picker.place(x=0, y=0, relwidth=1, relheight=1)
        picker.lift()
        self.picker = picker
        self.stage.place_forget()
        self.mini.place_forget()
        center = tk.Frame(picker, bg=BG)
        center.place(relx=.5, rely=.46, anchor="center")
        logo = tk.Label(picker, image=self.logo_photo, bg=BG)
        logo.place(x=S(40), y=S(32))
        label(center, "Profielen beheren" if manage else "Wie kijkt er?", 30, TEXT, BG, True).pack(pady=(0, S(36)))
        tiles = tk.Frame(center, bg=BG)
        tiles.pack()
        size = S(132)

        def tile(profile=None):
            box = tk.Frame(tiles, bg=BG, padx=S(14))
            box.pack(side="left", anchor="n")
            if profile is None:
                normal, hover = ui.add_tile_photo(size), ui.add_tile_photo(size, True)
                name, sub = "Toevoegen", ""
                action = lambda: self.edit_profile(None)
            else:
                color, kids = profile.get("color", 0), profile.get("kids", False)
                icon = "pencil" if manage else None
                normal = ui.avatar_photo(color, size, kids, False, manage, icon)
                hover = ui.avatar_photo(color, size, kids, True, manage, icon)
                name = profile.get("name", "")
                sub = "Kinderprofiel" if kids else ""
                if manage:
                    action = (lambda p=profile: self.ask_pin(p, lambda: self.edit_profile(p))
                              if p.get("pin") else self.edit_profile(p))
                else:
                    action = lambda p=profile: self.enter_profile(p)
            art = tk.Label(box, image=normal, bg=BG, bd=0, cursor="hand2")
            art.pack()
            caption = tk.Frame(box, bg=BG)
            caption.pack(pady=(S(12), 0))
            title = label(caption, elide(name, 12, size, False), 12, MUTED, BG)
            title.pack(side="left")
            if profile is not None and profile.get("pin"):
                tk.Label(caption, image=ui.pill_photo(icon="lock", kind="quiet", h=22, hover=False, disabled=False),
                         bg=BG).pack(side="left", padx=(S(4), 0))
            if sub:
                label(box, sub, 9, ACCENT_SOFT, BG).pack()

            def enter(_=None):
                art.configure(image=hover)
                title.configure(fg=TEXT)

            def leave(_=None):
                art.configure(image=normal)
                title.configure(fg=MUTED)
            for widget in (art, title):
                widget.bind("<Enter>", enter)
                widget.bind("<Leave>", leave)
                widget.bind("<ButtonRelease-1>", lambda _: action())
                widget.configure(cursor="hand2")
        for profile in self.profiles["profiles"]:
            tile(profile)
        if len(self.profiles["profiles"]) < 6:
            tile(None)
        actions = tk.Frame(center, bg=BG)
        actions.pack(pady=(S(44), 0))
        if manage:
            Pill(actions, "Klaar", lambda: self.show_profiles(False), kind="primary", h=44, padx=30).pack(side="left")
        else:
            Pill(actions, "Profielen beheren", lambda: self.show_profiles(True), kind="ghost", icon="pencil",
                 h=44, padx=22).pack(side="left")
            if self.profile is not None:
                Pill(actions, "Terug", self.close_profiles, kind="quiet", h=44, padx=20).pack(side="left", padx=S(10))

        def keys(event):
            if event.keysym == "Escape":
                if manage:
                    self.show_profiles(False)
                elif self.profile is not None:
                    self.close_profiles()
            return "break"
        self.overlay_keys = keys

    def ask_pin(self, profile, success):
        """Four-digit PIN pad shown on top of the profile screen."""
        if self.picker is None or not self.picker.winfo_exists():
            self.show_profiles()
        layer = tk.Frame(self.picker, bg=BG)
        layer.place(x=0, y=0, relwidth=1, relheight=1)
        layer.lift()
        center = tk.Frame(layer, bg=BG)
        center.place(relx=.5, rely=.47, anchor="center")
        tk.Label(center, image=ui.avatar_photo(profile.get("color", 0), S(88), profile.get("kids", False)),
                 bg=BG).pack()
        label(center, profile.get("name", ""), 14, TEXT, BG, True).pack(pady=(S(12), S(2)))
        hint = label(center, "Voer je pincode in", 11, MUTED, BG)
        hint.pack(pady=(0, S(22)))
        dots = tk.Label(center, bg=BG, bd=0)
        dots.pack(pady=(0, S(26)))
        entered = []
        previous_keys = self.overlay_keys

        def draw(error=False):
            dots.photo = ImageTk.PhotoImage(ui.render_dots(4, len(entered), error=error))
            dots.configure(image=dots.photo)

        def close():
            layer.destroy()
            self.overlay_keys = previous_keys

        def shake(step=0):
            offsets = (14, -12, 10, -8, 6, -4, 2, 0)
            if not dots.winfo_exists():
                return
            dots.pack_configure(padx=(max(0, offsets[step]) * 2, max(0, -offsets[step]) * 2))
            if step < len(offsets) - 1:
                dots.after(28, lambda: shake(step + 1))
            else:
                entered.clear()
                draw()

        def press(digit):
            if len(entered) >= 4:
                return
            entered.append(digit)
            draw()
            if len(entered) == 4:
                if data.check_pin(profile.get("pin"), "".join(entered)):
                    layer.after(120, lambda: (close(), success()))
                else:
                    hint.configure(text="Onjuiste pincode, probeer opnieuw", fg="#fda4af")
                    draw(error=True)
                    layer.after(260, shake)

        def erase():
            if entered:
                entered.pop()
                draw()
        pad = tk.Frame(center, bg=BG)
        pad.pack()
        layout = (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"), (None, "0", "back"))
        for r, row in enumerate(layout):
            for c, key in enumerate(row):
                if key is None:
                    continue
                if key == "back":
                    button = Pill(pad, "", erase, kind="quiet", icon="back", h=60)
                else:
                    button = Pill(pad, key, lambda k=key: press(k), kind="ghost", h=60, px=17, weight="bold")
                button.grid(row=r, column=c, padx=S(8), pady=S(6))
        Pill(center, "Annuleren", close, kind="quiet", h=40, padx=18).pack(pady=(S(18), 0))
        draw()

        def keys(event):
            if event.char and event.char.isdigit():
                press(event.char)
            elif event.keysym == "BackSpace":
                erase()
            elif event.keysym == "Escape":
                close()
            return "break"
        self.overlay_keys = keys

    def edit_profile(self, profile):
        creating = profile is None
        layer = tk.Frame(self.picker, bg=BG)
        layer.place(x=0, y=0, relwidth=1, relheight=1)
        layer.lift()
        card = tk.Frame(layer, bg=SIDE, padx=S(34), pady=S(28), highlightthickness=1, highlightbackground=LINE)
        card.place(relx=.5, rely=.5, anchor="center")
        tk.Frame(card, bg=SIDE, width=S(500), height=0).pack()
        label(card, "Profiel toevoegen" if creating else "Profiel bewerken", 20, TEXT, SIDE, True).pack(anchor="w")
        previous_keys = self.overlay_keys
        values = dict(profile or {"name": "", "color": len(self.profiles["profiles"]) % len(ui.AVATARS), "kids": False})
        top = tk.Frame(card, bg=SIDE)
        top.pack(fill="x", pady=(S(18), 0))
        preview = tk.Label(top, bg=SIDE, bd=0)
        preview.pack(side="left", anchor="n")
        fields = tk.Frame(top, bg=SIDE)
        fields.pack(side="left", fill="x", expand=True, padx=(S(22), 0))
        name = tk.StringVar(value=values.get("name", ""))
        entry = self.field(fields, "Naam", name)
        label(fields, "Kleur", 10, SOFT, SIDE).pack(anchor="w", pady=(S(12), S(6)))
        swatches = tk.Frame(fields, bg=SIDE)
        swatches.pack(anchor="w")

        def refresh_preview():
            preview.configure(image=ui.avatar_photo(values["color"], S(96), values.get("kids", False)))
            for index, swatch in enumerate(swatch_widgets):
                swatch.configure(image=ui.avatar_photo(index, S(34), False, index == values["color"]))
        swatch_widgets = []
        for index in range(len(ui.AVATARS)):
            swatch = tk.Label(swatches, bg=SIDE, bd=0, cursor="hand2")
            swatch.pack(side="left", padx=(0, S(8)))
            swatch.bind("<Button-1>", lambda _, i=index: (values.update(color=i), refresh_preview()))
            swatch_widgets.append(swatch)
        refresh_preview()

        kids_row = tk.Frame(card, bg=SIDE)
        kids_row.pack(fill="x", pady=(S(22), 0))
        Switch(kids_row, values.get("kids", False),
               lambda v: (values.update(kids=v), refresh_preview())).pack(side="left", anchor="n")
        texts = tk.Frame(kids_row, bg=SIDE)
        texts.pack(side="left", padx=S(14))
        label(texts, "Kinderprofiel", 11, TEXT, SIDE, True).pack(anchor="w")
        label(texts, "Verbergt zenders en titels voor volwassenen. Provider en instellingen zijn afgeschermd.",
              9, MUTED, SIDE, wraplength=S(400), justify="left").pack(anchor="w")

        pin = tk.StringVar()
        has_pin = bool(profile and profile.get("pin"))
        pin_box = tk.Frame(card, bg=SIDE)
        pin_box.pack(fill="x", pady=(S(8), 0))
        self.field(pin_box, "Nieuwe pincode (4 cijfers)" if has_pin else "Pincode (4 cijfers, optioneel)", pin, True)
        remove_pin = {"value": False}
        if has_pin:
            row = tk.Frame(pin_box, bg=SIDE)
            row.pack(anchor="w", pady=(S(10), 0))
            Switch(row, False, lambda v: remove_pin.update(value=v)).pack(side="left")
            label(row, "Pincode verwijderen", 10, SOFT, SIDE).pack(side="left", padx=S(12))
        copy = {"value": bool(creating and self.profile and self.source)}
        if creating and self.profile and self.source:
            row = tk.Frame(card, bg=SIDE)
            row.pack(anchor="w", pady=(S(14), 0))
            Switch(row, True, lambda v: copy.update(value=v)).pack(side="left")
            label(row, f"Zelfde provider als {self.profile.get('name', '')}", 10, SOFT, SIDE).pack(side="left", padx=S(12))
        status = label(card, "", 10, "#fda4af", SIDE)
        status.pack(anchor="w", pady=(S(12), 0))
        buttons = tk.Frame(card, bg=SIDE)
        buttons.pack(fill="x", pady=(S(8), 0))

        def close():
            layer.destroy()
            self.overlay_keys = previous_keys

        def save():
            text = name.get().strip()
            code = pin.get().strip()
            if not text:
                status.configure(text="Geef het profiel een naam.")
                return
            if code and (len(code) != 4 or not code.isdigit()):
                status.configure(text="Een pincode bestaat uit precies 4 cijfers.")
                return
            target = profile if profile is not None else {"id": uuid4().hex[:8]}
            if creating:
                target["folder"] = target["id"]
                self.profiles["profiles"].append(target)
            target.update(name=text[:24], color=values["color"], kids=bool(values.get("kids")))
            if code:
                target["pin"] = data.hash_pin(code)
            elif remove_pin["value"]:
                target.pop("pin", None)
            try:
                if creating and copy["value"]:
                    data.copy_provider(self.profile, target)
                data.save_profiles(self.profiles)
            except OSError as error:
                status.configure(text=error_text(error))
                return
            if target is self.profile:
                self.update_profile_chip()
                self.set_library(self.state.get("library", []))
            self.show_profiles(True)
            self.toast("Profiel aangemaakt" if creating else "Profiel opgeslagen")

        def delete():
            if delete_button.opts["text"] != "Zeker? Klik nogmaals":
                delete_button.update_pill(text="Zeker? Klik nogmaals")
                return
            self.profiles["profiles"] = [p for p in self.profiles["profiles"] if p is not profile]
            data.delete_profile(profile)
            try:
                data.save_profiles(self.profiles)
            except OSError:
                pass
            if profile is self.profile:
                self.stop_playback()
                self.profile = None
            self.show_profiles(True)
            self.toast("Profiel verwijderd", "trash")
        Pill(buttons, "Opslaan", save, kind="primary", h=42, padx=24).pack(side="left")
        Pill(buttons, "Annuleren", close, kind="ghost", h=42, padx=18).pack(side="left", padx=S(10))
        if not creating and len(self.profiles["profiles"]) > 1:
            delete_button = Pill(buttons, "Verwijderen", delete, kind="danger", icon="trash", h=42, padx=18)
            delete_button.pack(side="right")

        def keys(event):
            if event.keysym == "Escape":
                close()
                return "break"
            if event.keysym == "Return":
                save()
                return "break"
            return None
        self.overlay_keys = keys
        entry.focus_set()

    def report_error(self, kind, value, trace):
        text = "".join(traceback.format_exception(kind, value, trace))
        data.log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Zono {VERSION}\n{text}")
        try:
            self.toast("Er ging iets mis · opgeslagen in het logboek", "close")
        except tk.TclError:
            pass

    def preferred_countries(self):
        chosen = self.preferences.get("countries") or []
        return [c for c in chosen if c in countries.COUNTRIES] if isinstance(chosen, list) else []

    def country_rank(self, item):
        chosen = self.preferred_countries()
        code = countries.detect(item)
        return chosen.index(code) if code in chosen else len(chosen)

    def apply_countries(self, library):
        """Put the viewer's countries first (and optionally hide channels and titles of other countries)."""
        chosen = self.preferred_countries()
        if not chosen:
            return library
        hide = self.preferences.get("other_countries") == "hide"
        result = []
        for item in library:
            code = countries.detect(item)
            if hide and code and code not in chosen:
                continue
            result.append(item)
        live = sorted((i for i in result if i.get("kind") == "live"), key=self.country_rank)
        return live + [i for i in result if i.get("kind") != "live"]

    def present_channels(self, library):
        """Hidden channels out, own names in, and (optionally) tidy names: "4K | VRT 1 HD" becomes "VRT 1"."""
        hidden = set(self.preferences.get("hidden_channels") or [])
        names = self.preferences.get("channel_names") or {}
        names = names if isinstance(names, dict) else {}
        clean = self.preferences.get("clean_names", True)
        result = []
        for item in library:
            if item.get("kind") == "live":
                if item.get("id") in hidden:
                    continue
                raw = str(item.get("title", ""))
                if clean and countries.is_separator(raw):
                    continue
                title = names.get(item.get("id")) or (countries.clean_name(raw) if clean else raw)
                item = dict(item, title=title, raw_title=raw, cc=countries.detect(item))
            elif clean and item.get("kind") in ("movie", "series"):
                raw = str(item.get("title", ""))
                title = countries.clean_title(raw)
                if title != raw:
                    item = dict(item, title=title, raw_title=raw, cc=countries.detect(item))
            result.append(item)
        shown = {i["id"]: i for i in result}
        for key, favorite in list(getattr(self, "favorites", {}).items()):
            if key in shown and favorite.get("title") != shown[key]["title"]:
                self.favorites[key] = dict(favorite, title=shown[key]["title"])
        for key, entry in list(getattr(self, "progress", {}).items()):
            item = entry.get("item") if isinstance(entry, dict) else None
            if item and key in shown and item.get("title") != shown[key]["title"]:
                self.progress[key] = dict(entry, item=dict(item, title=shown[key]["title"]))
            elif item and clean and item.get("kind") in ("movie", "series"):
                title = (countries.clean_episode(str(item.get("title", ""))) if item.get("series")
                         else countries.clean_title(str(item.get("title", ""))))
                if title != item.get("title"):
                    self.progress[key] = dict(entry, item=dict(item, title=title))
        return result

    def set_library(self, library):
        self.raw_library = library
        library = self.present_channels(self.apply_countries(library))
        words = self.blocked_words() if self.profile else ()
        if words:
            library = [i for i in library
                       if not any(w in f"{i.get('group', '')} {i.get('title', '')}".casefold() for w in words)]
        self.library = library
        self.search_pool = [(str(i.get("title", "")).casefold(), i) for i in library]
        self.search_cache = ("", None)
        self.by_kind = {"live": [], "movie": [], "series": []}
        for item in library:
            self.by_kind.setdefault(item.get("kind"), []).append(item)
        self.best, self.rated, self.newest = {}, {}, {}
        for kind in ("movie", "series"):
            pool = self.by_kind.get(kind, [])
            self.rated[kind] = any(score(i) > 0 for i in pool)
            self.best[kind] = sorted(pool, key=lambda i: (-score(i), not art_url(i, "image")))
            self.newest[kind] = sorted((i for i in pool if added_of(i)), key=lambda i: -added_of(i))

    def refresh_library(self, silent=False, quiet_toast=False):
        if not self.source or self.refreshing:
            return
        self.refreshing = True
        source = self.source
        if not silent:
            self.toast("Bibliotheek vernieuwen…", "wifi")

        def failed(error):
            self.refreshing = False
            if not silent:
                self.toast(elide(error_text(error), 10, S(520), True), "close")

        def loaded(entries):
            if not entries or source != self.source:
                self.refreshing = False
                return
            new_state = {"revision": uuid4().hex, "library": entries, "source": source,
                         "favorites": self.favorites, "progress": self.progress}

            def saved(_):
                self.refreshing = False
                self.state = new_state
                self.set_library(entries)
                self.hero_art.clear()
                try:
                    self.save_activity()
                except OSError:
                    pass
                self.remember_preference("last_refresh", int(time()))
                if not silent and self.tab == "home" and not self.detail_item and not self.query.get() and not self.player_view:
                    self.render()  # a background refresh does not rebuild the page you are looking at
                if not silent or quiet_toast:
                    self.toast(f"Bibliotheek bijgewerkt  ·  {number(len(entries))} titels", "refresh")
            self.run(lambda: data.save_state(new_state), saved, failed)
        self.run(lambda: data.catalog(source), loaded, failed)

    # ------------------------------------------------------------ chrome

    def build_sidebar(self):
        side = tk.Frame(self.root, bg=SIDE, width=S(SIDEBAR_W))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self.root, bg=LINE, width=1).pack(side="left", fill="y")
        self.logo_photo = ImageTk.PhotoImage(ui.render_logo())
        logo = tk.Label(side, image=self.logo_photo, bg=SIDE, cursor="hand2")
        logo.pack(anchor="w", padx=S(22), pady=(S(26), S(22)))
        logo.bind("<Button-1>", lambda _: self.select("home"))

        self.query = tk.StringVar()
        self.query.trace_add("write", self.schedule_search)
        self.nav = {}

        def item(parent, key, icon, text=None, command=None):
            pill = Pill(parent, text or TABS[key], command or (lambda: self.select(key)), kind="nav", icon=icon,
                        h=40, width=SIDEBAR_W - 32, align="left", radius=10, px=12.5, padx=14)
            pill.pack(anchor="w", padx=S(16), pady=1)
            self.nav[key] = pill

        def separator(parent):
            tk.Frame(parent, bg=LINE, height=1).pack(fill="x", padx=S(26), pady=S(10))

        item(side, "home", "home")
        item(side, "live", "live")
        item(side, "guide", "guide")
        separator(side)
        item(side, "movie", "film")
        item(side, "series", "series")
        separator(side)
        item(side, "favorites", "heart")
        item(side, "downloads", "download")
        item(side, "phone", "phone", "Op je telefoon", lambda: self.open_share())

        bottom = tk.Frame(side, bg=SIDE)
        bottom.pack(side="bottom", fill="x", pady=(0, S(14)))
        separator(bottom)
        item(bottom, "source", "wifi", "Provider koppelen", self.configure_source)
        item(bottom, "settings", "gear")
        separator(bottom)
        chip = tk.Frame(bottom, bg=SIDE, padx=S(12), pady=S(6), cursor="hand2")
        chip.pack(fill="x", padx=S(16))
        self.chip_avatar = tk.Label(chip, bg=SIDE, bd=0)
        self.chip_avatar.pack(side="left")
        names = tk.Frame(chip, bg=SIDE)
        names.pack(side="left", padx=S(12))
        self.chip_name = label(names, "", 11, TEXT, SIDE, True, anchor="w")
        self.chip_name.pack(anchor="w")
        self.chip_sub = label(names, "Profiel wisselen", 8, DIM, SIDE, anchor="w")
        self.chip_sub.pack(anchor="w")
        tk.Label(chip, image=ui.pill_photo(icon="swap", kind="quiet", h=28, hover=False, disabled=False),
                 bg=SIDE).pack(side="right")
        ui.bind_hover(chip, lambda: ui.set_bg(chip, "#1a1a21"), lambda: ui.set_bg(chip, SIDE))
        ui.bind_click(chip, lambda: self.show_profiles())
        self.sidebar = side

    def wheel(self, event, delta=None):
        delta = event.delta if delta is None else delta
        scroller = getattr(self, "panel_scroller", None)
        if scroller is not None and scroller.winfo_exists() and scroller.winfo_ismapped():
            x, y = self.root.winfo_pointerxy()
            if scroller.winfo_rootx() <= x < scroller.winfo_rootx() + scroller.winfo_width() and \
                    scroller.winfo_rooty() <= y < scroller.winfo_rooty() + scroller.winfo_height():
                scroller.yview_scroll(int(-delta / 120 * 3) or (-1 if delta > 0 else 1), "units")
                return
        if self.player_view or self.sheet_close or self.picker is not None or isinstance(event.widget, (tk.Listbox, str)):
            return
        if self.search_open:
            widget = event.widget
            while widget is not None and widget is not self.results_panel:
                widget = getattr(widget, "master", None)
            if widget is not None:
                return
        self.smooth_scroll(-delta / 120 * S(120))

    def hwheel(self, event):
        if self.player_view or self.picker is not None:
            return
        widget = event.widget
        while widget is not None and not getattr(widget, "hscroll", False):
            widget = getattr(widget, "master", None)
        if widget is not None:
            self.glide(widget, -event.delta / 120 * S(220))
        else:
            self.wheel(event)

    def route_key(self, event):
        if self.overlay_keys:
            return self.overlay_keys(event)
        if self.player_keys:
            return self.player_keys(event)
        char = getattr(event, "char", "")
        if char and char.isdigit() and not isinstance(event.widget, tk.Entry) and not self.sheet_close \
                and self.tab == "live" and getattr(self, "live_jump", None) and not self.search_open:
            self.zap_input(char, self.live_items, self.live_jump)
            return "break"
        return None

    def slash(self, event):
        if self.overlay_keys or self.player_keys or self.sheet_close or isinstance(event.widget, tk.Entry):
            return None
        self.open_search()
        return "break"

    def arrow(self, event, delta):
        if self.overlay_keys:
            return self.overlay_keys(event)
        if self.player_keys:
            return self.player_keys(event)
        if self.search_open:
            self.search_move(delta)
            return "break"
        if self.sheet_close:
            return None
        try:
            focused = self.root.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if self.live_nav and not isinstance(focused, (tk.Entry, tk.Listbox)):
            self.live_nav(delta)
            return "break"
        return None

    def escape(self, event):
        if self.trailer_view is not None:
            self.close_trailer()
            return "break"
        if self.overlay_keys:
            return self.overlay_keys(event)
        if self.search_open:
            self.close_search()
            return "break"
        if self.player_keys:
            return self.player_keys(event)
        if self.sheet_close:
            self.sheet_close()
            return "break"
        if isinstance(event.widget, tk.Entry):
            return None
        if self.detail_item:
            self.back()
        return None

    def sheet(self, w, h):
        """A panel that opens inside the app, on top of the current page."""
        if self.sheet_close:
            self.sheet_close()
        if self.stage_mode == "slot":
            self.set_stage("mini")
        overlay = tk.Frame(self.main, bg="#060609")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        card = tk.Frame(overlay, bg=SIDE, highlightthickness=1, highlightbackground=LINE)
        card.place(relx=.5, rely=.5, anchor="center")
        tk.Frame(card, bg=SIDE, width=S(w), height=0).pack()
        card.closable = True

        def close():
            if overlay.winfo_exists():
                overlay.destroy()
            if self.sheet_close is request:
                self.sheet_close = None
            self.queue_place()

        def request():
            if card.closable:
                close()
        card.close = close
        closer = Pill(card, "", request, kind="ghost", icon="close", h=34)
        closer.place(relx=1, x=-S(16), y=S(16), anchor="ne")
        self.root.after_idle(lambda: closer.winfo_exists() and closer.lift())
        overlay.bind("<Button-1>", lambda e: request() if e.widget is overlay else None)
        self.sheet_close = request
        self.queue_place()
        return card

    def show_log(self):
        """The error log, inside the app."""
        try:
            text = data.LOG.read_text(encoding="utf-8", errors="replace") if data.LOG.exists() else ""
        except OSError as error:
            text = f"Het logboek kon niet worden gelezen: {error_text(error)}"
        text = text.strip()
        try:
            started = (data.ROOT / "start.log").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            started = ""
        if started:
            text = (text + "\n\n" if text else "") + "--- Laatste start ---\n" + started
        lines = text.splitlines()
        if len(lines) > 600:
            text = "…\n" + "\n".join(lines[-600:])
        card = self.sheet(760, 0)
        body = tk.Frame(card, bg=SIDE, padx=S(30), pady=S(26))
        body.pack(fill="both", expand=True)
        label(body, "Logboek", 18, TEXT, SIDE, True).pack(anchor="w")
        if not text:
            box = tk.Frame(body, bg=SIDE)
            box.pack(fill="x", pady=(S(30), S(20)))
            Pill(box, "", None, kind="ghost", icon="check", h=64).pack()
            label(box, "Alles werkt naar behoren", 15, TEXT, SIDE, True).pack(pady=(S(14), S(4)))
            label(box, "Er staan geen fouten in het logboek. Gaat er ooit iets mis, dan zie je het hier.", 10, MUTED,
                  SIDE).pack()
            return
        label(body, "Wat Zono onlangs niet lukte. Stuur dit mee als je hulp vraagt.", 10, MUTED, SIDE).pack(
            anchor="w", pady=(S(4), S(14)))
        holder = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        holder.pack(fill="both", expand=True)
        view = tk.Text(holder, bg=PANEL, fg=SOFT, insertbackground=TEXT, relief="flat", bd=0, wrap="word",
                       font=("Consolas", 9), padx=S(14), pady=S(12), height=22, width=96, highlightthickness=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=view.yview, style="Zono.Vertical.TScrollbar")
        view.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        view.pack(side="left", fill="both", expand=True)
        view.insert("1.0", text)
        view.configure(state="disabled")
        view.see("end")
        view.bind("<MouseWheel>", lambda e: (view.yview_scroll(-int(e.delta / 120) * 3, "units"), "break")[1])
        tools = tk.Frame(body, bg=SIDE)
        tools.pack(fill="x", pady=(S(16), 0))

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.toast("Logboek gekopieerd")

        def clear():
            try:
                data.LOG.unlink(missing_ok=True)
            except OSError as error:
                self.toast(elide(error_text(error), 10, S(420), True), "close")
                return
            if self.sheet_close:
                self.sheet_close()
            self.toast("Logboek gewist", "trash")
        Pill(tools, "Kopiëren", copy, kind="primary", icon="check", h=40, padx=16).pack(side="left")
        Pill(tools, "Wissen", clear, kind="ghost", icon="trash", h=40, padx=16).pack(side="left", padx=S(10))

    def content_resized(self, _=None):
        if _ is not None and getattr(_, "widget", None) is not self.content:
            return
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def canvas_resized(self, event):
        self.canvas.itemconfigure(self.viewport, width=event.width)
        if self.live_layout:
            if self.layout_job:
                self.root.after_cancel(self.layout_job)
            self.layout_job = self.root.after(120, lambda w=event.width: self.live_layout and self.live_layout(w))
        if self.last_width and abs(event.width - self.last_width) > S(90) and self.has_grid:
            if self.resize_job:
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(350, self.render)
        if not self.last_width or abs(event.width - self.last_width) > S(90):
            self.last_width = event.width

    def page_width(self):
        width = self.canvas.winfo_width()
        return width if width > 1 else self.root.winfo_width() - S(SIDEBAR_W) - S(12)

    def toast(self, text, icon="check"):
        if self.toast_widget is not None and self.toast_widget.winfo_exists():
            self.toast_widget.destroy()
        photo = ui.pill_photo(text=text, icon=icon, kind="toast", h=46, px=12.5, padx=22, hover=False, disabled=False)
        key = "#010102"
        widget = None
        if os.name == "nt":
            # A tiny see-through window, so the rounded corners show the page instead of dark squares.
            try:
                widget = tk.Toplevel(self.root, bg=key)
                widget.overrideredirect(True)
                widget.attributes("-transparentcolor", key)
                inner = tk.Label(widget, image=photo, bg=key, bd=0)
                inner.pack()
                widget.update_idletasks()
                width, height = photo.width(), photo.height()
                left = self.root.winfo_rootx() + S(SIDEBAR_W) + (self.root.winfo_width() - S(SIDEBAR_W) - width) // 2
                if self.player_view is not None:
                    left = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
                top = self.root.winfo_rooty() + self.root.winfo_height() - height - S(30)
                widget.geometry(f"{width}x{height}+{left}+{top}")
                ui.window_style(widget, no_activate=True)
                widget.lift()
            except tk.TclError:
                if widget is not None:
                    widget.destroy()
                widget = None
        if widget is None:
            widget = tk.Label(self.root, image=photo, bg=BG, bd=0)
            widget.place(relx=.5, x=S(SIDEBAR_W) // 2, rely=1, y=-S(30), anchor="s")
            widget.lift()
        widget.photo = photo
        self.toast_widget = widget
        widget.after(2600, lambda: widget.winfo_exists() and widget.destroy())

    # ------------------------------------------------------------ jobs

    def run(self, action, done, failed, artwork=False, executor=None):
        executor = executor or (self.art_workers if artwork else self.workers)
        job = executor.submit(action)
        job.add_done_callback(lambda future: self.results.put((future, done, failed)))
        return job

    def poll(self):
        """Hand finished background work to the screen. Always keeps itself going, whatever a handler does."""
        try:
            # a time budget instead of a count: pictures arrive in bursts and each one costs the screen thread a
            # little, so hand over what fits in ~12 ms and keep the rest for the next round (smooth scrolling)
            budget = perf_counter() + 0.012
            for _ in range(32):
                if self.results.empty() or perf_counter() > budget:
                    break
                future, done, failed = self.results.get()
                if future.cancelled():
                    continue
                try:
                    value = future.result()
                except Exception as error:
                    handler, argument = failed, error
                else:
                    handler, argument = done, value
                try:
                    handler(argument)
                except tk.TclError:
                    pass
                except Exception:
                    self.report_error(*sys.exc_info())
        finally:
            self.root.after(40 if self.results.empty() else 15, self.poll)

    # ------------------------------------------------------------ navigation

    def select(self, tab):
        if tab != self.tab:
            self.guide_day = 0
        self.tab = tab
        self.detail_item = None
        self.category = None
        if self.query.get():
            self.query.set("")
        for key, widget in self.nav.items():
            if key in TABS:
                widget.update_pill(kind="nav_on" if key == tab else "nav")
        self.reset_view()

    def schedule_search(self, *_):
        if self.search_job:
            self.root.after_cancel(self.search_job)
        self.search_job = self.root.after(220, self.reset_view)

    def reset_view(self):
        if self.search_job:
            self.root.after_cancel(self.search_job)
            self.search_job = None
        self.limit = 30
        self.render()
        self.canvas.yview_moveto(0)

    def in_category(self, item):
        return self.category is None or str(item.get("group") or "Overige") == self.category

    def render(self):
        if self.sheet_close:
            self.sheet_close()
        if self.search_open and not self.search_var.get():
            self.close_search()
        self.generation += 1
        self.deferred.clear()
        if self.scroll_job:
            self.root.after_cancel(self.scroll_job)
            self.scroll_job, self.scroll_target = None, None
        self.listeners.pop("slot", None)
        if self.stage_mode == "slot":
            self.stage_mode, self.stage_target = "mini", None
        for job in self.art_jobs:
            job.cancel()
        self.art_jobs.clear()
        for job in (self.rotate_job, self.resize_job, self.layout_job):
            if job:
                self.root.after_cancel(job)
        self.rotate_job = self.resize_job = self.layout_job = None
        self.live_nav = self.live_layout = self.hero_canvas = self.episode_anchor = None
        self.live_jump, self.live_items = None, []
        self.has_grid = False
        old = self.content
        fresh = tk.Frame(self.canvas, bg=BG)
        fresh.bind("<Configure>", self.content_resized)
        self.canvas.itemconfigure(self.viewport, window=fresh, width=max(1, self.canvas.winfo_width()))
        self.content = fresh
        # removing hundreds of posters takes a moment: do it after the new page is on screen
        self.root.after(120, lambda: old.destroy() if old.winfo_exists() else None)
        self.queue_place()
        query = self.query.get().strip().casefold()
        if self.detail_item and not query:
            self.detail(self.detail_item)
            return
        if self.tab == "downloads" and not query:
            self.downloads_view()
            return
        if self.tab == "settings" and not query:
            self.settings_view()
            return
        if self.tab in ("live", "guide"):
            pool = self.by_kind.get("live", [])
            entries = [i for i in pool if self.in_category(i) and (not query or query in str(i["title"]).casefold())]
            if self.tab == "live":
                head = self.page_header("Live TV", f"{number(len(pool))} zenders" if pool else "Nog geen zenders")
                if len(pool) > 1:
                    Pill(head, "Multiview", lambda: self.open_multiview(), kind="ghost", icon="grid", h=38,
                         padx=14).place(relx=1, x=-S(64), rely=0, anchor="ne")
                    Pill(head, "Zenders beheren", self.manage_channels, kind="ghost", icon="pencil", h=38,
                         padx=14).place(relx=1, x=-S(210), rely=0, anchor="ne")
                self.live_view(pool, entries)
            else:
                self.guide_view(pool, entries)
            return
        if query:
            results = [i for i in self.library if query in str(i["title"]).casefold()]
            self.page_header("Zoekresultaten", f"{number(len(results))} titels voor “{self.query.get().strip()}”")
            self.section(None, results, grid=True)
            return
        if self.tab == "home":
            self.home_view()
            return
        if self.tab == "favorites":
            entries = list(self.favorites.values())
            self.page_header("Favorieten", f"{number(len(entries))} bewaarde titels en zenders")
            self.section(None, entries, grid=True,
                         empty="Klik op het hartje bij een titel of zender om hem hier te bewaren.")
            return
        pool = self.by_kind.get(self.tab, [])
        noun = "films" if self.tab == "movie" else "series"
        self.page_header(TABS[self.tab], f"{number(len(pool))} {noun} in je bibliotheek")
        self.category_chips(pool)
        self.section(None, [i for i in pool if self.in_category(i)], grid=True)

    def page_header(self, title, subtitle=None, parent=None):
        head = tk.Frame(parent or self.content, bg=BG)
        head.pack(fill="x", padx=S(44), pady=(S(36), S(16)))
        label(head, title, 26, TEXT, BG, True).pack(anchor="w")
        if subtitle:
            label(head, subtitle, 11, MUTED).pack(anchor="w", pady=(2, 0))
        return head

    def chip_strip(self, parent, options, active, pick, padx=44, pady=(0, 20), extra=None, heart=None, loved=()):
        holder = tk.Frame(parent, bg=BG)
        holder.pack(fill="x", padx=S(padx), pady=(S(pady[0]), S(pady[1])))
        arrows = tk.Frame(holder, bg=BG)
        if heart:
            Pill(holder, heart[0], heart[2], kind="chip_on" if heart[1] == "heart_fill" else "ghost", icon=heart[1],
                 h=34, px=11.5).pack(side="right", padx=(S(10), 0))
        if extra:
            Pill(holder, extra[0], extra[2], kind="ghost", icon="search", h=34, px=11.5,
                 badge=number(extra[1])).pack(side="right", padx=(S(10), 0))
        strip = tk.Canvas(holder, bg=BG, height=S(34), highlightthickness=0, xscrollincrement=S(40))
        strip.hscroll = True
        strip.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(strip, bg=BG)
        strip.create_window(0, 0, window=inner, anchor="nw")
        pills = {}
        for value, text, count in options:
            pill = Pill(inner, elide(text, 10, S(220), True), lambda v=value: pick(v),
                        kind="chip_on" if value == active else "chip", h=34, px=11.5,
                        badge=number(count) if count is not None else "",
                        icon="heart_fill" if value in loved and value is not None else None)
            pill.pack(side="left", padx=(0, S(8)))
            pills[value] = pill
        Pill(arrows, "", lambda: self.glide(strip, -strip.winfo_width() * 0.7), kind="ghost", icon="back", h=32).pack(side="left", padx=(S(8), S(4)))
        Pill(arrows, "", lambda: self.glide(strip, strip.winfo_width() * 0.7), kind="ghost", icon="next", h=32).pack(side="left")

        def sync(_=None):
            strip.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), S(34)))
            if inner.winfo_reqwidth() > strip.winfo_width() > 1:
                if not arrows.winfo_ismapped():
                    arrows.pack(side="right", before=strip)
            else:
                arrows.pack_forget()
        inner.bind("<Configure>", sync)
        strip.bind("<Configure>", sync)
        return pills

    def category_chips(self, pool, pady=(0, 22)):
        counts = {}
        for item in pool:
            group = str(item.get("group") or "Overige")
            counts[group] = counts.get(group, 0) + 1
        if len(counts) < 2:
            return

        def pick(value):
            self.category = value
            self.reset_view()
        kind = next((str(i.get("kind")) for i in pool if i.get("kind")), "movie")
        followed = {g for k, g in self.favorite_groups() if k == kind}
        extra = None
        if len(counts) <= 16:
            groups = sorted(counts, key=str.casefold)
        else:
            groups = sorted(counts, key=lambda g: (-counts[g], g.casefold()))[:10]
            if self.category in counts and self.category not in groups:
                groups.insert(0, self.category)
            extra = ("Alle categorieën", len(counts), lambda: self.category_picker(counts, pick))
        chosen = self.preferred_countries()
        if chosen:
            rank = lambda g: (chosen.index(c) if (c := countries.detect_text(g)) in chosen else len(chosen))
            groups = sorted(groups, key=rank)
        groups = [g for g in groups if g in followed] + [g for g in groups if g not in followed]
        for g in followed:
            if g in counts and g not in groups:
                groups.insert(0, g)
        options = [(None, "Alle", len(pool))] + [(g, g, counts[g]) for g in groups]
        heart = None
        if self.category is not None and self.category in counts:
            on = self.category in followed
            heart = ("Bij Ontdekken" if on else "Volgen", "heart_fill" if on else "heart",
                     lambda: self.toggle_favorite_group(kind, self.category))
        self.chip_strip(self.content, options, self.category, pick, pady=pady, extra=extra, heart=heart,
                        loved=followed)

    def category_picker(self, counts, pick):
        window = self.sheet(480, 600)
        frame = tk.Frame(window, bg=SIDE, padx=S(28), pady=S(24))
        frame.pack(fill="both", expand=True)
        label(frame, "Categorieën", 18, TEXT, SIDE, True).pack(anchor="w")
        label(frame, f"{number(len(counts))} categorieën", 10, MUTED, SIDE).pack(anchor="w", pady=(2, S(10)))
        query = tk.StringVar()
        entry = self.field(frame, "Zoek een categorie", query)
        holder, listing = self.styled_list(frame)
        listing.configure(height=14)
        holder.pack(fill="both", expand=True, pady=(S(14), 0))
        shown = []

        def refresh(*_):
            text = query.get().strip().casefold()
            shown[:] = [g for g in sorted(counts, key=str.casefold) if text in g.casefold()]
            listing.delete(0, "end")
            for group in shown:
                listing.insert("end", f"  {group}   ·   {number(counts[group])}")
            if shown:
                listing.selection_set(0)

        def choose(_=None):
            selection = listing.curselection()
            if selection:
                value = shown[selection[0]]
                window.close()
                pick(value)
        query.trace_add("write", refresh)
        listing.bind("<Double-Button-1>", choose)
        listing.bind("<Return>", choose)
        entry.bind("<Return>", choose)
        entry.bind("<Down>", lambda _: listing.focus_set())
        refresh()
        entry.focus_set()

    # ------------------------------------------------------------ home + hero

    def home_view(self):
        real_section = self.section
        count = {"n": 0}

        def section(*args, **kwargs):
            count["n"] += 1
            if count["n"] <= 1:
                real_section(*args, **kwargs)
            else:
                self.defer(lambda: real_section(*args, **kwargs))
        self.section = section
        try:
            self.build_home()
        finally:
            del self.section

    def home_layout(self):
        """[(key, shown)] in the order the viewer chose; new sections are added at the end."""
        saved = self.preferences.get("home_layout")
        known = {key for key, _, _ in HOME_SECTIONS}
        layout = []
        if isinstance(saved, list):
            for entry in saved:
                if isinstance(entry, (list, tuple)) and len(entry) == 2 and entry[0] in known \
                        and entry[0] not in {k for k, _ in layout}:
                    layout.append((entry[0], bool(entry[1])))
        for key, _, _ in HOME_SECTIONS:
            if key not in {k for k, _ in layout}:
                layout.append((key, True))
        return layout

    def build_home(self):
        movies, series = self.best.get("movie", []), self.best.get("series", [])
        with_art = lambda items: [i for i in items if art_url(i, "backdrop", "image")]
        size = int(self.preferences.get("home_row_size", 20) or 20)
        hero_mode = self.preferences.get("home_hero", "mix")
        if hero_mode == "movie":
            featured = with_art(movies[:20])[:8] or movies[:8]
        elif hero_mode == "series":
            featured = with_art(series[:20])[:8] or series[:8]
        elif hero_mode == "mine":
            featured = [i for i in self.favorites.values() if i["kind"] != "live"][:8] or with_art(movies[:14])[:5]
        else:
            featured = (with_art(movies[:14])[:5] + with_art(series[:10])[:3]) or (movies[:5] + series[:3])
        featured = featured or self.library[:1]
        if hero_mode != "off" or not self.library:
            visible = self.canvas.winfo_height() if self.canvas.winfo_height() > 1 else S(800)
            canvas = self.hero(featured, height=max(S(460), min(S(700), int(visible * .74))))
            for kind, noun in (("movie", "films"), ("series", "series")):
                if self.rated.get(kind):
                    for rank, item in enumerate(self.best[kind][:10], 1):
                        canvas.ranks[item["id"]] = (rank, noun)
        else:
            tk.Frame(self.content, bg=BG, height=S(40)).pack(fill="x")
        if not self.library:
            self.welcome_rows()
            return
        resume = sorted(self.progress.values(), key=lambda p: p.get("updated", 0), reverse=True)
        my_channels = [i for i in self.favorites.values() if i["kind"] == "live"]
        shown = {key for key, on in self.home_layout() if on}

        def now_playing(tile, item):
            if item.get("sid") and self.source:
                self.fetch_guide(item, lambda rows, t=tile: t.set_now(rows) if t.winfo_exists() else None)

        def welcome():
            self.welcome_block()

        def resume_row():
            if resume:
                self.section("Verder kijken", [p["item"] for p in resume][:size])

        def channels_row():
            if my_channels:
                self.section("Mijn zenders", my_channels[:size], more="favorites", on_card=now_playing)

        def mylist_row():
            mine = [i for i in self.favorites.values() if i["kind"] != "live"]
            if mine:
                self.section("Mijn lijst", mine[:size], more="favorites")

        def groups_rows():
            for kind, group in self.favorite_groups():
                pool = [i for i in self.by_kind.get(kind, []) if str(i.get("group") or "Overige") == group]
                if pool:
                    if kind != "live":
                        pool.sort(key=lambda i: -score(i))
                    self.section(group, pool[:size], more=kind, on_card=now_playing if kind == "live" else None)

        def because_row():
            because = next((p["item"] for p in resume if p["item"].get("kind") in ("movie", "series")), None)
            if because:
                group = str(because.get("group") or "")
                similar = [i for i in self.by_kind.get(because["kind"], []) if str(i.get("group") or "") == group
                           and i["id"] != because["id"] and i["id"] not in self.progress]
                similar.sort(key=lambda i: -score(i))
                if group and group != "Overige" and len(similar) >= 4:
                    self.section(f"Omdat je {elide(str(because['title']), 16, S(420), True)} keek", similar[:size])

        def by_country(name, source):
            def build():
                found = {}
                for item in source:
                    code = countries.detect(item)
                    if code:
                        found.setdefault(code, []).append(item)
                return found
            return self.memo(name, source, build)

        def country_rows():
            live_by_country = by_country("live_countries", self.by_kind.get("live", []))
            for code in self.preferred_countries()[:3]:
                lives = live_by_country.get(code, [])
                if lives:
                    self.section(f"Zenders · {countries.name(code)}", lives[:size], more="live", on_card=now_playing)
                titles = by_country("movie_countries", movies).get(code, []) + by_country("series_countries", series).get(code, [])
                titles.sort(key=lambda i: -score(i))
                if len(titles) >= 4:
                    self.section(f"Films en series · {countries.name(code)}", titles[:size])

        def top_row():
            if self.rated.get("movie") and len(movies) >= 3:
                self.section("Top 10 films vandaag", movies[:10], more="movie", ranked=True)

        def movies_row():
            if movies:
                rest = movies[10:10 + size] if self.rated.get("movie") and len(movies) > 16 else movies[:size]
                self.section("Beste films" if self.rated.get("movie") else "Films", rest, more="movie")

        def series_row():
            if series:
                if self.rated.get("series") and len(series) >= 3:
                    self.section("Beste series", series[:10], more="series", ranked=True)
                    if len(series) > 14:
                        self.section("Meer series", series[10:10 + size], more="series")
                else:
                    self.section("Series", series[:size], more="series")

        def live_row():
            lives = self.by_kind.get("live", [])
            if lives:
                last = self.preferences.get("last_channel")
                first = [i for i in lives if i["id"] == last]
                seen = {i["id"] for i in my_channels} if "channels" in shown else set()
                row = []
                for item in first + lives:
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        row.append(item)
                    if len(row) == size:
                        break
                self.section("Meer zenders" if my_channels and "channels" in shown else "Live TV", row, more="live",
                             on_card=now_playing)

        def newest_row():
            newest = sorted(self.newest.get("movie", []) + self.newest.get("series", []), key=lambda i: -added_of(i))[:size]
            if len(newest) >= 4:
                self.section("Nieuw toegevoegd", newest)

        def genre_rows():
            def build():
                counts, members = {}, {}
                for item in movies:
                    group = str(item.get("group") or "Overige")
                    if group != "Overige":
                        counts[group] = counts.get(group, 0) + 1
                        if len(members.setdefault(group, [])) < 40:
                            members[group].append(item)
                return counts, members
            counts, members = self.memo("genres", movies, build)
            followed = {g for k, g in self.favorite_groups() if k == "movie"}
            for group in [g for g in sorted(counts, key=lambda g: -counts[g]) if g not in followed][:4]:
                if counts[group] >= 4:
                    self.section(group, members[group][:size], more="movie")
        builders = {"welcome": welcome, "resume": resume_row, "channels": channels_row, "mylist": mylist_row,
                    "groups": groups_rows, "because": because_row, "country": country_rows, "top": top_row,
                    "movies": movies_row, "series": series_row, "live": live_row, "newest": newest_row,
                    "genres": genre_rows}
        for key, on in self.home_layout():
            if on:
                builders[key]()
        tools = tk.Frame(self.content, bg=BG)
        Pill(tools, "Ontdekken aanpassen", self.edit_home, kind="ghost", icon="pencil", h=40, padx=16).pack(side="left")
        self.defer(lambda: tools.pack(anchor="w", padx=S(44), pady=(S(10), S(40))) if tools.winfo_exists() else None)

    def edit_home(self):
        """Choose which rows Ontdekken shows, in which order, and what the big banner shows."""
        card = self.sheet(620, 0)
        body = tk.Frame(card, bg=SIDE, padx=S(30), pady=S(24))
        body.pack(fill="both", expand=True)
        label(body, "Ontdekken aanpassen", 18, TEXT, SIDE, True).pack(anchor="w")
        label(body, "Zet rijen aan of uit en verschuif ze met de pijltjes. Wijzigingen worden meteen bewaard.", 10,
              MUTED, SIDE).pack(anchor="w", pady=(S(2), S(10)))
        options = tk.Frame(body, bg=SIDE)
        options.pack(fill="x")
        self.choice_row(options, "Grote banner bovenaan", [("mix", "Films en series"), ("movie", "Films"),
                        ("series", "Series"), ("mine", "Mijn lijst"), ("off", "Uit")],
                        self.preferences.get("home_hero", "mix"), "home_hero", bg=SIDE, note=None)
        self.choice_row(options, "Titels per rij", [(10, "10"), (20, "20"), (40, "40")],
                        int(self.preferences.get("home_row_size", 20) or 20), "home_row_size", bg=SIDE, note=None)
        label(body, "RIJEN", 8, DIM, SIDE, True).pack(anchor="w", pady=(S(18), S(6)))
        visible = max(S(220), min(S(470), self.root.winfo_height() - S(470)))
        scroller = tk.Canvas(body, bg=SIDE, highlightthickness=0, bd=0, height=visible, yscrollincrement=S(12))
        scroller.pack(fill="x")
        holder = tk.Frame(scroller, bg=SIDE)
        holder_id = scroller.create_window(0, 0, window=holder, anchor="nw")
        holder.bind("<Configure>", lambda _: scroller.configure(scrollregion=(0, 0, holder.winfo_reqwidth(), holder.winfo_reqheight())))
        scroller.bind("<Configure>", lambda e: scroller.itemconfigure(holder_id, width=e.width))
        self.panel_scroller = scroller
        names = {key: (title, text) for key, title, text in HOME_SECTIONS}

        def save(layout):
            self.remember_preference("home_layout", [[k, on] for k, on in layout])

        def draw():
            for child in holder.winfo_children():
                child.destroy()
            layout = self.home_layout()
            for index, (key, on) in enumerate(layout):
                row = tk.Frame(holder, bg=PANEL if on else SIDE, padx=S(12), pady=S(7))
                row.pack(fill="x", pady=1)

                def toggle(value, k=key):
                    current = self.home_layout()
                    save([(x, value if x == k else v) for x, v in current])
                    draw()
                Switch(row, on, toggle).pack(side="left")
                texts = tk.Frame(row, bg=row.cget("bg"))
                texts.pack(side="left", padx=S(12))
                title, text = names[key]
                label(texts, title, 10, TEXT if on else MUTED, row.cget("bg"), True).pack(anchor="w")
                label(texts, text, 8, MUTED if on else DIM, row.cget("bg")).pack(anchor="w")

                def move(delta, i=index):
                    current = self.home_layout()
                    j = i + delta
                    if 0 <= j < len(current):
                        current[i], current[j] = current[j], current[i]
                        save(current)
                        draw()
                Pill(row, "", lambda: move(1), kind="quiet", icon="next", h=30, bg=row.cget("bg")).pack(side="right")
                Pill(row, "", lambda: move(-1), kind="quiet", icon="back", h=30, bg=row.cget("bg")).pack(side="right")
        draw()
        bottom = tk.Frame(body, bg=SIDE)
        bottom.pack(fill="x", pady=(S(16), 0))

        def finish():
            if self.sheet_close:
                self.sheet_close()
            self.render()

        def reset():
            for key, value in (("home_layout", None), ("home_hero", "mix"), ("home_row_size", 20)):
                self.remember_preference(key, value)
            draw()
        Pill(bottom, "Klaar", finish, kind="primary", icon="check", h=40, padx=18).pack(side="left")
        Pill(bottom, "Standaard herstellen", reset, kind="ghost", icon="refresh", h=40, padx=16).pack(side="left", padx=S(10))
        Pill(bottom, "Landen kiezen", lambda: (self.sheet_close and self.sheet_close(), self.edit_countries()),
             kind="ghost", icon="live", h=40, padx=16).pack(side="right")

    def manage_channels(self):
        """Hide channels you never watch and give channels your own name."""
        card = self.sheet(700, 0)
        body = tk.Frame(card, bg=SIDE, padx=S(30), pady=S(24))
        body.pack(fill="both", expand=True)
        label(body, "Zenders beheren", 18, TEXT, SIDE, True).pack(anchor="w")
        label(body, "Verberg zenders die je nooit kijkt, of geef een zender je eigen naam. Verborgen zenders verdwijnen uit "
                    "Live TV, de gids, zoeken en Ontdekken.", 10, MUTED, SIDE, wraplength=S(620), justify="left").pack(
            anchor="w", pady=(S(2), S(10)))
        top = tk.Frame(body, bg=SIDE)
        top.pack(fill="x")
        query = tk.StringVar()
        entry = tk.Entry(top, textvariable=query, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat", font=(FONT, 11),
                         highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.pack(side="left", fill="x", expand=True, ipady=S(6))
        mode = {"value": "all"}
        chips = {}

        def set_mode(value):
            mode["value"] = value
            for key, pill in chips.items():
                pill.update_pill(kind="chip_on" if key == value else "chip")
            draw()
        for value, text in (("all", "Alle"), ("hidden", "Verborgen"), ("renamed", "Eigen naam")):
            chips[value] = Pill(top, text, lambda v=value: set_mode(v), kind="chip_on" if value == "all" else "chip",
                                h=34, px=11.5, bg=SIDE)
            chips[value].pack(side="left", padx=(S(8), 0))
        visible = max(S(240), min(S(460), self.root.winfo_height() - S(420)))
        scroller = tk.Canvas(body, bg=SIDE, highlightthickness=0, bd=0, height=visible, yscrollincrement=S(12))
        scroller.pack(fill="x", pady=(S(12), 0))
        holder = tk.Frame(scroller, bg=SIDE)
        holder_id = scroller.create_window(0, 0, window=holder, anchor="nw")
        holder.bind("<Configure>", lambda _: scroller.configure(scrollregion=(0, 0, holder.winfo_reqwidth(), holder.winfo_reqheight())))
        scroller.bind("<Configure>", lambda e: scroller.itemconfigure(holder_id, width=e.width))
        self.panel_scroller = scroller
        status = label(body, "", 9, MUTED, SIDE)
        status.pack(anchor="w", pady=(S(8), 0))
        changed = {"any": False}

        def prefs():
            hidden = list(self.preferences.get("hidden_channels") or [])
            names = dict(self.preferences.get("channel_names") or {})
            return hidden, names

        def save(hidden, names):
            self.remember_preference("hidden_channels", hidden)
            self.remember_preference("channel_names", names)
            changed["any"] = True

        def draw(*_):
            for child in holder.winfo_children():
                child.destroy()
            hidden, names = prefs()
            clean = self.preferences.get("clean_names", True)
            text = query.get().strip().casefold()
            pool = [i for i in getattr(self, "raw_library", self.library) if i.get("kind") == "live"]
            rows = []
            for item in pool:
                raw = str(item.get("title", ""))
                shown = names.get(item["id"]) or (countries.clean_name(raw) if clean else raw)
                if text and text not in raw.casefold() and text not in shown.casefold():
                    continue
                if mode["value"] == "hidden" and item["id"] not in hidden:
                    continue
                if mode["value"] == "renamed" and item["id"] not in names:
                    continue
                rows.append((item, raw, shown))
            status.configure(text=f"{number(len(rows))} zenders" + ("  ·  de eerste 150 worden getoond, zoek om te verfijnen"
                                                                    if len(rows) > 150 else "")
                             + (f"  ·  {number(len(hidden))} verborgen" if hidden else ""))
            for item, raw, shown in rows[:150]:
                off = item["id"] in hidden
                row = tk.Frame(holder, bg=SIDE, padx=S(10), pady=S(6))
                row.pack(fill="x", pady=1)
                texts = tk.Frame(row, bg=SIDE)
                texts.pack(side="left", fill="x", expand=True)
                name = label(texts, elide(shown, 11, S(420), True), 11, DIM if off else TEXT, SIDE, True)
                name.pack(anchor="w")
                if clean and countries.is_separator(raw):
                    label(texts, "Scheidingslijn van je provider  ·  wordt automatisch verborgen", 8, DIM, SIDE).pack(anchor="w")
                elif shown != raw:
                    label(texts, elide(raw, 8, S(420)), 8, DIM, SIDE).pack(anchor="w")

                def toggle(i=item):
                    h, n = prefs()
                    if i["id"] in h:
                        h.remove(i["id"])
                    else:
                        h.append(i["id"])
                    save(h, n)
                    draw()

                def rename(i=item, r=row, t=texts, current=shown):
                    for child in t.winfo_children():
                        child.destroy()
                    value = tk.StringVar(value=current)
                    field = tk.Entry(t, textvariable=value, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                                     font=(FONT, 11), highlightthickness=1, highlightbackground=ACCENT)
                    field.pack(fill="x", ipady=S(4))
                    field.focus_set()
                    field.select_range(0, "end")

                    saved = {"done": False}

                    def store(_=None):
                        if saved["done"]:
                            return "break"
                        saved["done"] = True
                        h, n = prefs()
                        new = value.get().strip()
                        if new and new != str(i.get("title", "")):
                            n[i["id"]] = new
                        else:
                            n.pop(i["id"], None)
                        save(h, n)
                        draw()
                        return "break"
                    field.bind("<Return>", store)
                    field.bind("<Escape>", lambda _: (draw(), "break")[1])
                    field.bind("<FocusOut>", store)
                Pill(row, "", toggle, kind="ghost", icon="eye_off" if off else "eye", h=32, bg=SIDE).pack(side="right")
                Pill(row, "", rename, kind="quiet", icon="pencil", h=32, bg=SIDE).pack(side="right", padx=(0, S(6)))
                if item["id"] in names:
                    def reset(i=item):
                        h, n = prefs()
                        n.pop(i["id"], None)
                        save(h, n)
                        draw()
                    Pill(row, "Oorspronkelijk", reset, kind="quiet", h=30, bg=SIDE, padx=10).pack(side="right", padx=(0, S(6)))
            scroller.yview_moveto(0)
        query.trace_add("write", lambda *_: draw())
        draw()
        bottom = tk.Frame(body, bg=SIDE)
        bottom.pack(fill="x", pady=(S(16), 0))

        def finish():
            if self.sheet_close:
                self.sheet_close()
            if changed["any"]:
                self.set_library(self.raw_library)
                self.render()
        Pill(bottom, "Klaar", finish, kind="primary", icon="check", h=40, padx=18).pack(side="left")
        switch = tk.Frame(bottom, bg=SIDE)
        switch.pack(side="left", padx=S(18))

        def set_clean(value):
            self.remember_preference("clean_names", value)
            changed["any"] = True
            draw()
        Switch(switch, self.preferences.get("clean_names", True), set_clean).pack(side="left")
        label(switch, "Namen opschonen (“4K | VRT 1 HD” → “VRT 1”)", 10, SOFT, SIDE).pack(side="left", padx=S(10))
        entry.focus_set()

    def memo(self, name, source, build):
        """Cache a value computed from a list; refreshing the library replaces the list, which resets it."""
        cache = self.__dict__.setdefault("memo_cache", {})
        key = (name, id(source), len(source))
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[key] = build()
        return cache[key]

    def detected_countries(self):
        source = getattr(self, "raw_library", self.library)

        def build():
            counts = {}
            for item in source:
                code = countries.detect(item)
                if code:
                    counts[code] = counts.get(code, 0) + 1
            return counts
        return dict(self.memo("countries", source, build))

    def country_picker(self, parent, bg, after=None):
        """Chips for the countries in this library: click in the order you want them."""
        holder = tk.Frame(parent, bg=bg)
        holder.pack(fill="x")

        def draw():
            for child in holder.winfo_children():
                child.destroy()
            counts = self.detected_countries()
            chosen = self.preferred_countries()
            if not counts:
                label(holder, "Zono herkent nog geen landen in je zenders. Koppel eerst je provider.", 10, MUTED, bg).pack(anchor="w")
                return
            codes = chosen + sorted((c for c in counts if c not in chosen), key=lambda c: -counts[c])
            row = None
            for index, code in enumerate(codes):
                if index % 4 == 0:
                    row = tk.Frame(holder, bg=bg)
                    row.pack(anchor="w", pady=(0, S(8)))
                on = code in chosen
                text = (f"{chosen.index(code) + 1}.  " if on else "") + countries.name(code)

                def flip(c=code):
                    current = self.preferred_countries()
                    if c in current:
                        current.remove(c)
                    else:
                        current.append(c)
                    self.remember_preference("countries", current)
                    self.set_library(self.raw_library)
                    draw()
                    if after:
                        after()
                Pill(row, text, flip, kind="chip_on" if on else "chip", h=34, px=11.5,
                     badge=number(counts.get(code, 0))).pack(side="left", padx=(0, S(8)))
        draw()
        return holder

    def edit_countries(self):
        card = self.sheet(640, 0)
        body = tk.Frame(card, bg=SIDE, padx=S(30), pady=S(24))
        body.pack(fill="both", expand=True)
        label(body, "Landen en talen", 18, TEXT, SIDE, True).pack(anchor="w")
        label(body, "Klik je landen aan in de volgorde die je wilt. Hun zenders komen vooraan in Live TV en de gids, "
                    "hun categorieën eerst, en Ontdekken krijgt rijen ‘Uit jouw landen’.", 10, MUTED, SIDE,
              wraplength=S(560), justify="left").pack(anchor="w", pady=(S(2), S(16)))
        self.country_picker(body, SIDE)
        self.choice_row(body, "Zenders en titels van andere landen",
                        [("last", "Achteraan tonen"), ("hide", "Verbergen")],
                        self.preferences.get("other_countries", "last"), "other_countries", bg=SIDE, note=None,
                        after=lambda _: self.set_library(self.raw_library))

        def finish():
            if self.sheet_close:
                self.sheet_close()
            self.render()
        Pill(body, "Klaar", finish, kind="primary", icon="check", h=40, padx=18).pack(anchor="w", pady=(S(20), 0))

    def favorite_groups(self):
        """Categories the profile follows, as (kind, group) pairs."""
        groups = self.preferences.get("fav_groups") or []
        return [(str(k), str(g)) for k, g in groups if isinstance(g, str)] if isinstance(groups, list) else []

    def toggle_favorite_group(self, kind, group):
        groups = self.favorite_groups()
        if (kind, group) in groups:
            groups.remove((kind, group))
            self.toast(f"{group} niet meer bij Ontdekken", "heart")
        else:
            groups.append((kind, group))
            self.toast(f"{group} staat nu bij Ontdekken", "heart_fill")
        self.remember_preference("fav_groups", [list(g) for g in groups])
        self.render()

    def welcome_block(self):
        """A personal start: a greeting and whatever you were watching, one click away."""
        name = str((self.profile or {}).get("name") or "").strip()
        hour = datetime.now().hour
        hello = "Goedemorgen" if 5 <= hour < 12 else "Goedemiddag" if hour < 18 else "Goedenavond" if hour < 23 else "Hallo nachtuil"
        block = tk.Frame(self.content, bg=BG)
        block.pack(fill="x", padx=S(44), pady=(S(26), S(4)))
        label(block, f"{hello}{', ' + name if name else ''}", 20, TEXT, BG, True).pack(anchor="w")
        count = len(self.favorites) + len(self.favorite_groups())
        tip = f"Jouw Ontdekken · {count} favoriet{'en' if count != 1 else ''} staan hier bovenaan" if count else \
            "Tik op het hartje bij een zender, film, serie of categorie: dan komt hij hier bovenaan."
        label(block, tip, 10, MUTED, BG).pack(anchor="w", pady=(S(2), 0))
        if not self.preferred_countries() and len(self.detected_countries()) >= 2 \
                and not self.preferences.get("countries_asked"):
            ask = tk.Frame(block, bg=PANEL, padx=S(16), pady=S(12))
            ask.pack(anchor="w", pady=(S(14), 0))
            label(ask, "Welke landen wil je eerst zien?", 11, TEXT, PANEL, True).pack(side="left")
            Pill(ask, "Landen kiezen", lambda: (self.remember_preference("countries_asked", True), self.edit_countries()),
                 kind="primary", icon="live", h=36, padx=14).pack(side="left", padx=(S(16), S(8)))
            Pill(ask, "Later", lambda: (self.remember_preference("countries_asked", True), self.render()),
                 kind="ghost", h=36, padx=14).pack(side="left")
        current = self.session["item"] if self.session else None
        playing = bool(current)
        if not current:
            last = self.preferences.get("last_channel")
            current = next((i for i in self.by_kind.get("live", []) if i["id"] == last), None)
        if not current:
            return
        card = tk.Frame(block, bg=PANEL, padx=S(16), pady=S(14), cursor="hand2")
        card.pack(anchor="w", pady=(S(16), S(6)))
        live = current.get("kind") == "live"
        thumb = tk.Label(card, bg=PANEL, bd=0, image=ui.placeholder_photo(S(56) if live else S(46), S(56) if live else S(66), RAISED, 10))
        thumb.pack(side="left")
        if live:
            self.load_logo(thumb, current, S(56))
        else:
            self.load_thumb(thumb, current, (S(46), S(66)))
        texts = tk.Frame(card, bg=PANEL)
        texts.pack(side="left", padx=(S(16), S(28)))
        label(texts, "NU AAN HET KIJKEN" if playing else "KIJK VERDER NAAR", 8, ACCENT_SOFT, PANEL, True).pack(anchor="w")
        label(texts, elide(str(current.get("title", "")), 15, S(420), True), 15, TEXT, PANEL, True).pack(anchor="w")
        detail = label(texts, "Live TV" if live else KIND_LABEL.get(current.get("kind"), ""), 10, MUTED, PANEL)
        detail.pack(anchor="w")
        if live and current.get("sid") and self.source:
            def show_now(rows, widget=detail):
                program = current_program(rows)
                if program and widget.winfo_exists():
                    widget.configure(text=f"Nu: {elide(program['title'], 10, S(380))}")
            self.fetch_guide(current, show_now)
        elif current["id"] in self.progress:
            entry = self.progress[current["id"]]
            left = max(1, round((entry.get("duration", 0) - entry.get("time", 0)) / 60))
            detail.configure(text=f"Nog {left} min")

        def go():
            if playing and self.session:
                self.expand_player()
            else:
                self.open_item(current)
        Pill(card, "Verder kijken" if not playing else "Openen", go, kind="primary", icon="play", h=42, padx=18).pack(side="left")
        ui.bind_hover(card, lambda: ui.set_bg(card, RAISED), lambda: ui.set_bg(card, PANEL))
        ui.bind_click(card, go)

    def hero(self, items, detail=False, height=None):
        height = height or S(HERO_H)
        canvas = tk.Canvas(self.content, bg=BG, height=height, highlightthickness=0)
        canvas.pack(fill="x")
        canvas.items = items
        canvas.index = self.feature_index % len(items) if items else 0
        canvas.detail = detail
        canvas.info = {}
        canvas.keep = []
        canvas.ranks = {}
        canvas.hero_h = height
        canvas.button_id = 0
        canvas.elapsed = 0
        self.hero_canvas = canvas
        canvas.bind("<Configure>", lambda _: self.draw_hero(canvas))
        for item in items:
            self.load_hero_art(canvas, item)
        if not detail and len(items) > 1 and self.slide_ms():
            self.schedule_rotate(canvas)
        return canvas

    def slide_ms(self):
        try:
            return max(0, int(self.preferences.get("slide_seconds", 7))) * 1000
        except (TypeError, ValueError):
            return 7000

    def load_hero_art(self, canvas, item):
        if item["id"] in self.hero_art:
            return
        self.hero_art[item["id"]] = None
        source = self.source
        wants_info = bool(item.get("sid") and source and item["kind"] in ("movie", "series") and "plot" not in item)
        if not wants_info and not art_url(item, "backdrop", "image"):
            return

        def fetch():
            info = {}
            if wants_info:
                result = safe(data.details, source, item)
                info = result[0] if result else {}
            wide = art_url(item, "backdrop") or first_url(info.get("backdrop_path")) or first_url(info.get("backdrop"))
            url = wide or art_url(item, "image")
            return info, wide, (safe(backdrop, url) if url else None), wants_info

        def done(result):
            info, wide, image, asked = result
            if asked:
                item.update(summarize(info))
            if wide:
                item["backdrop"] = wide
            if image is not None:
                self.hero_art[item["id"]] = image
                while len(self.hero_art) > 24:
                    self.hero_art.pop(next(iter(self.hero_art)))
            if canvas.winfo_exists() and canvas.items and canvas.items[canvas.index] is item:
                self.draw_hero(canvas)
        self.art_jobs.append(self.run(fetch, done, lambda _: None, artwork=True))

    def schedule_rotate(self, canvas):
        if self.rotate_job:
            self.root.after_cancel(self.rotate_job)

        def tick():
            self.rotate_job = None
            if not canvas.winfo_exists() or self.hero_canvas is not canvas:
                return
            try:
                x, y = canvas.winfo_pointerxy()
                hovered = canvas.winfo_containing(x, y) is canvas
            except (tk.TclError, KeyError):
                hovered = False
            if not hovered and not self.player_view and not self.sheet_close:
                canvas.elapsed += 100
            if canvas.elapsed >= self.slide_ms():
                canvas.elapsed = 0
                canvas.index = (canvas.index + 1) % len(canvas.items)
                self.feature_index = canvas.index
                self.draw_hero(canvas, fade=True)
            elif getattr(canvas, "dot", None):
                x0, x1, y = canvas.dot
                canvas.coords("dotfill", x0, y, x0 + (x1 - x0) * canvas.elapsed / max(1, self.slide_ms()), y)
            self.rotate_job = self.root.after(100, tick)
        self.rotate_job = self.root.after(100, tick)

    def feature(self, canvas, index):
        canvas.index = index
        canvas.elapsed = 0
        self.feature_index = index
        self.draw_hero(canvas, fade=True)

    def canvas_button(self, canvas, x, y, command, anchor="nw", group="content", **options):
        options.setdefault("kind", "glass")
        normal = ui.pill_photo(hover=False, disabled=False, **options)
        hover = ui.pill_photo(hover=True, disabled=False, **options)
        canvas.button_id += 1
        tag = f"button{canvas.button_id}"
        item = canvas.create_image(x, y, image=normal, anchor=anchor, tags=(group, tag))
        canvas.tag_bind(tag, "<Enter>", lambda _: (canvas.itemconfigure(item, image=hover), canvas.configure(cursor="hand2")))
        canvas.tag_bind(tag, "<Leave>", lambda _: (canvas.itemconfigure(item, image=normal), canvas.configure(cursor="")))
        canvas.tag_bind(tag, "<ButtonRelease-1>", lambda _: command())
        canvas.keep.extend((normal, hover))
        return canvas.bbox(item)

    def hero_favorite(self, canvas, item):
        self.toggle(item)
        self.draw_hero(canvas)

    def draw_hero(self, canvas, fade=False):
        if not canvas.winfo_exists():
            return
        width = max(1, canvas.winfo_width())
        height = canvas.hero_h
        item = canvas.items[canvas.index] if canvas.items else None
        canvas.delete("all")
        canvas.keep = []
        canvas.dot = None
        canvas.configure(cursor="")
        art = self.hero_art.get(item["id"]) if item else None
        background = ui.hero_background(art, item, (width, height))
        canvas.token = getattr(canvas, "token", 0) + 1
        token = canvas.token
        old = getattr(canvas, "bg_pil", None)
        start = old if fade and old is not None and old.size == background.size else background
        canvas.bg_pil = background
        self.queue_search_look()
        canvas.photo = ImageTk.PhotoImage(start)
        canvas.create_image(0, 0, image=canvas.photo, anchor="nw")
        if start is not background:
            def frame(step=1):
                if not canvas.winfo_exists() or canvas.token != token:
                    return
                amount = step / 7
                # paint into the same image instead of swapping images: no flash between frames
                canvas.photo.paste(background if amount >= 1 else Image.blend(old, background, amount))
                if amount < 1:
                    canvas.after(30, lambda: frame(step + 1))
            canvas.after(10, frame)
        x = S(56)
        if canvas.detail:
            self.canvas_button(canvas, S(32), S(28), self.back, group="fixed", icon="back", h=42, kind="glass")
        rank = canvas.ranks.get(item["id"]) if item else None
        if item:
            eyebrow = KIND_LABEL.get(item["kind"], "").upper()
            group = str(item.get("group") or "")
            if group and group != "Overige":
                eyebrow += "  ·  " + group.upper()
            title = str(item["title"])
            caption = canvas.info.get("meta") or item.get("meta", "")
            description = canvas.info.get("desc") or item.get("plot", "")
            if not canvas.detail and len(description) > 210:
                description = description[:209].rsplit(" ", 1)[0] + "…"
        else:
            eyebrow = "ZONO  ·  JOUW IPTV"
            title = "Al je tv op één plek."
            caption = ""
            description = "Koppel je IPTV-provider en ontdek live tv, films en series in één rustige, overzichtelijke app."
        if len(title) > 90:
            title = title[:89] + "…"
        text_width = min(S(700), max(S(320), int(width * 0.55)))
        y = 0
        if rank:
            badge = self.canvas_button(canvas, x, y, lambda: None, text="TOP 10", kind="accent", h=24, px=10,
                                       radius=6, weight="bold", padx=9)
            canvas.create_text(badge[2] + S(10), (badge[1] + badge[3]) / 2, text=f"Nr. {rank[0]} in {rank[1]}",
                               fill=TEXT, anchor="w", font=(FONT, 12, "bold"), tags="content")
            y = badge[3] + S(12)
        else:
            mark = canvas.create_text(x + S(2), y, text=eyebrow[:80], fill=MUTED, anchor="nw", font=(FONT, 9, "bold"), tags="content")
            y = canvas.bbox(mark)[3] + S(8)
        size = 44 if len(title) < 26 else 34 if len(title) < 48 else 28
        mark = canvas.create_text(x, y, text=title, fill=TEXT, anchor="nw", font=(FONT, size, "bold"),
                                  width=text_width, tags="content")
        y = canvas.bbox(mark)[3] + S(8)
        if caption:
            mark = canvas.create_text(x + S(2), y, text=caption, fill=SOFT, anchor="nw", font=(FONT, 11, "bold"), tags="content")
            y = canvas.bbox(mark)[3] + S(8)
        if description:
            mark = canvas.create_text(x + S(2), y + S(4), text=description, fill="#c6c6d0", anchor="nw", font=(FONT, 11),
                                      width=min(S(600), text_width), tags="content")
            y = canvas.bbox(mark)[3] + S(6)
        y += S(20)
        if item:
            if canvas.detail and item["kind"] == "series":
                primary = ("Afleveringen", "series", self.scroll_to_episodes)
            elif item["kind"] == "series":
                primary = ("Bekijken", "play", lambda: self.show_detail(item))
            else:
                primary = ("Hervatten" if item["id"] in self.progress else "Afspelen", "play", lambda: self.open_item(item))
            box = self.canvas_button(canvas, x, y, primary[2], text=primary[0], icon=primary[1], kind="primary",
                                     h=48, px=13.5, padx=24)
            bx = box[2] + S(28)
            favorite = item["id"] in self.favorites
            actions = []
            if not canvas.detail:
                actions.append(("info", "Meer info", lambda: self.show_detail(item)))
            actions.append(("heart_fill" if favorite else "heart", "Favoriet", lambda: self.hero_favorite(canvas, item)))
            if canvas.detail and item.get("trailer"):
                actions.append(("trailer", "Trailer", lambda: self.open_trailer(item)))
            if canvas.detail and item["kind"] == "movie":
                if self.downloaded_file(item["id"]):
                    actions.append(("check", "Gedownload", lambda: self.select("downloads")))
                else:
                    actions.append(("download", "Download", lambda: (self.download(item), self.draw_hero(canvas))))
            for icon, text, command in actions:
                self.canvas_button(canvas, bx, y + S(1), command, icon=icon, h=46)
                canvas.create_text(bx + S(23), y + S(56), text=text, fill=SOFT, anchor="n", font=(FONT, 9), tags="content")
                bx += S(46 + 34)
            y += S(48 + (32 if actions else 0))
            watched = self.progress.get(item["id"], {})
            if watched.get("duration"):
                ratio = max(0, min(1, watched["time"] / watched["duration"]))
                y += S(22)
                bar = S(300)
                canvas.create_line(x + S(2), y, x + S(2) + bar, y, width=S(4), fill="#4a4a55", capstyle="round", tags="content")
                canvas.create_line(x + S(2), y, x + S(2) + bar * ratio, y, width=S(4), fill=TEXT, capstyle="round", tags="content")
                canvas.create_text(x + bar + S(18), y, text=minutes_left(watched["duration"] - watched["time"]), fill=SOFT,
                                   anchor="w", font=(FONT, 10), tags="content")
        else:
            self.canvas_button(canvas, x, y, self.configure_source, text="Provider koppelen", icon="wifi",
                               kind="primary", h=48, px=13.5, padx=24)
        box = canvas.bbox("content")
        if box:
            shift = (height - S(70 if not canvas.detail else 58)) - box[3]
            shift = max(shift, S(96 if canvas.detail else 60) - box[1])
            canvas.move("content", 0, shift)
        if not canvas.detail and len(canvas.items) > 1 and self.slide_ms():
            dx = width - S(56)
            y = height - S(52)
            half = S(3)
            for index in reversed(range(len(canvas.items))):
                active = index == canvas.index
                w = S(34 if active else 6)
                tag = f"dot{index}"
                canvas.create_line(dx - w + half, y, dx - half, y, width=S(6), capstyle="round",
                                   fill="#4d4d58" if active else "#3a3a44", tags=tag)
                if active:
                    canvas.dot = (dx - w + half, dx - half, y)
                    canvas.create_line(dx - w + half, y, dx - w + half, y, width=S(6), capstyle="round",
                                       fill=TEXT, tags=(tag, "dotfill"))
                canvas.tag_bind(tag, "<ButtonRelease-1>", lambda _, i=index: self.feature(canvas, i))
                canvas.tag_bind(tag, "<Enter>", lambda _: canvas.configure(cursor="hand2"))
                canvas.tag_bind(tag, "<Leave>", lambda _: canvas.configure(cursor=""))
                dx -= w + S(8)
            if canvas.dot:
                x0, x1, yy = canvas.dot
                canvas.coords("dotfill", x0, yy, x0 + (x1 - x0) * canvas.elapsed / max(1, self.slide_ms()), yy)

    def welcome_rows(self):
        block = tk.Frame(self.content, bg=BG)
        block.pack(fill="x", padx=S(44), pady=(S(14), S(30)))
        label(block, "Zo begin je", 16, TEXT, BG, True).pack(anchor="w", pady=(0, S(14)))
        tiles = tk.Frame(block, bg=BG)
        tiles.pack(fill="x")
        for column, (icon, title, caption, command) in enumerate((
                ("wifi", "Provider koppelen", "Voeg je Xtream Codes-gegevens of een M3U-afspeellijst toe.", self.configure_source),
                ("live", "Live TV", "Zap door je zenders, met programmagids erbij.", lambda: self.select("live")),
                ("film", "Films en series", "Blader door je hele catalogus, per categorie.", lambda: self.select("movie")))):
            tiles.columnconfigure(column, weight=1, uniform="tile")
            box = tk.Frame(tiles, bg=PANEL, padx=S(22), pady=S(20))
            box.grid(row=0, column=column, sticky="nsew", padx=(0, S(14)))
            Pill(box, "", None, kind="accent", icon=icon, h=44).pack(anchor="w")
            label(box, title, 13, TEXT, PANEL, True).pack(anchor="w", pady=(S(14), 2))
            label(box, caption, 10, MUTED, PANEL, wraplength=S(230), justify="left").pack(anchor="w")
            ui.bind_hover(box, lambda b=box: ui.set_bg(b, RAISED), lambda b=box: ui.set_bg(b, PANEL))
            ui.bind_click(box, command)

    # ------------------------------------------------------------ detail

    def show_detail(self, item):
        self.detail_item = item
        if self.query.get():
            self.query.set("")
        self.reset_view()

    def back(self):
        self.detail_item = None
        self.reset_view()

    def scroll_to_episodes(self):
        if self.episode_anchor and self.episode_anchor.winfo_exists():
            self.root.update_idletasks()
            top = self.episode_anchor.winfo_rooty() - self.content.winfo_rooty()
            self.canvas.yview_moveto(max(0, top - S(20)) / max(1, self.content.winfo_height()))

    def detail(self, item):
        canvas = self.hero([item], detail=True)
        block = tk.Frame(self.content, bg=BG)
        block.pack(fill="x", padx=S(56), pady=(S(4), 0))
        status = label(block, "", 10, MUTED, wraplength=S(760), justify="left")
        status.pack(anchor="w")
        facts = tk.Frame(block, bg=BG)
        facts.pack(fill="x")
        episodes = tk.Frame(block, bg=BG)
        episodes.pack(fill="x")
        cast_holder = tk.Frame(self.content, bg=BG)
        cast_holder.pack(fill="x")
        similar_holder = tk.Frame(self.content, bg=BG)
        similar_holder.pack(fill="x")
        details_holder = tk.Frame(self.content, bg=BG)
        details_holder.pack(fill="x", padx=S(56), pady=(0, S(30)))
        state = {"info": {}, "extra": self.tmdb_cache.get(item["id"], {}),
                 "genres": list(self.genre_cache.get(item["id"], []))}

        def draw_similar():
            if not similar_holder.winfo_exists():
                return
            for child in similar_holder.winfo_children():
                child.destroy()
            entries = self.similar_items(item, state["genres"], state["extra"].get("similar", []))
            title = "Meer zoals dit"
            if not entries:
                group = item.get("group")
                entries = [i for i in self.by_kind.get(item["kind"], [])
                           if i["id"] != item["id"] and i.get("group") == group][:20]
                title = f"Meer uit {group}" if group and group != "Overige" else title
            if entries:
                self.section(title, entries, padx=56, parent=similar_holder)

        def draw_cast():
            if not cast_holder.winfo_exists():
                return
            for child in cast_holder.winfo_children():
                child.destroy()
            people = state["extra"].get("cast") or [
                {"name": name.strip(), "role": "", "photo": ""}
                for name in str(state["info"].get("cast") or "").split(",") if name.strip()][:12]
            if not people:
                return
            box = tk.Frame(cast_holder, bg=BG)
            box.pack(fill="x", padx=S(56), pady=(S(14), S(18)))
            label(box, "Cast", 16, TEXT, BG, True).pack(anchor="w", pady=(0, S(12)))
            rail = tk.Canvas(box, bg=BG, highlightthickness=0, height=S(150), xscrollincrement=S(40))
            rail.hscroll = True
            rail.pack(fill="x")
            strip = tk.Frame(rail, bg=BG)
            rail.create_window(0, 0, window=strip, anchor="nw")
            strip.bind("<Configure>", lambda _: rail.configure(
                scrollregion=(0, 0, strip.winfo_reqwidth(), strip.winfo_reqheight()), height=strip.winfo_reqheight()))
            size = S(92)
            for person in people:
                cell = tk.Frame(strip, bg=BG)
                cell.pack(side="left", anchor="n", padx=(0, S(14)))
                face = tk.Label(cell, bg=BG, bd=0, image=self.person_photo(person["name"], size))
                face.pack()
                label(cell, elide(person["name"], 10, S(110), True), 10, TEXT, BG, True).pack(pady=(S(8), 0))
                if person.get("role"):
                    label(cell, elide(person["role"], 9, S(110)), 9, MUTED, BG).pack()
                if person.get("photo"):
                    self.load_person(face, person, size)

        def draw_facts():
            if not facts.winfo_exists():
                return
            for child in facts.winfo_children():
                child.destroy()
            genres = state["genres"]
            if genres:
                row = tk.Frame(facts, bg=BG)
                row.pack(anchor="w", pady=(S(6), S(4)))
                for genre in genres[:6]:
                    Pill(row, genre, None, kind="chip", h=30, px=10.5).pack(side="left", padx=(0, S(8)))
            info = state["info"]
            for child in details_holder.winfo_children():
                child.destroy()
            rating = info.get("rating")
            rows = [("Regie", info.get("director")), ("Cast", info.get("cast")), ("Genres", ", ".join(genres)),
                    ("Uitgebracht", info.get("releasedate") or info.get("releaseDate")), ("Duur", info.get("duration")),
                    ("Land", info.get("country")),
                    ("Beoordeling", f"★ {rating}" if rating not in (None, "", "0", 0, "0.0") else "")]
            rows = [(name, str(value).strip()) for name, value in rows if value and str(value).strip()]
            if rows:
                label(details_holder, "Details", 16, TEXT, BG, True).pack(anchor="w", pady=(S(12), S(10)))
                table = tk.Frame(details_holder, bg=BG)
                table.pack(anchor="w")
                for index, (name, value) in enumerate(rows):
                    label(table, name, 10, MUTED, BG, anchor="w").grid(row=index, column=0, sticky="nw", pady=S(3))
                    label(table, value[:300], 10, SOFT, BG, anchor="w", wraplength=S(760), justify="left").grid(
                        row=index, column=1, sticky="w", padx=(S(24), 0), pady=S(3))

        def apply_extra(extra):
            if not extra or not similar_holder.winfo_exists():
                return
            self.tmdb_cache[item["id"]] = extra
            state["extra"] = extra
            if extra.get("genres") and not state["genres"]:
                state["genres"] = extra["genres"]
                self.remember_genres(item, extra["genres"])
            if extra.get("trailer") and not item.get("trailer"):
                item["trailer"] = extra["trailer"]
                self.draw_hero(canvas)
            if extra.get("backdrop") and not item.get("backdrop"):
                item["backdrop"] = extra["backdrop"]
                self.hero_art.pop(item["id"], None)
                self.load_hero_art(canvas, item)
            draw_cast()
            draw_similar()
            draw_facts()

        draw_similar()
        if not item.get("sid") or not self.source:
            return
        status.configure(text="Details laden…")
        source = self.source

        def done(result):
            if not block.winfo_exists():
                return
            info, entries = result
            status.configure(text="")
            status.pack_forget()
            summary = summarize(info)
            item.update(summary)
            state["info"] = info
            if summary["genres"]:
                state["genres"] = summary["genres"]
                self.remember_genres(item, summary["genres"])
            canvas.info = {"meta": summary["meta"], "desc": summary["plot"]}
            wide = first_url(info.get("backdrop_path")) or first_url(info.get("backdrop"))
            if wide and wide != item.get("backdrop"):
                item["backdrop"] = wide
                self.hero_art.pop(item["id"], None)
                self.load_hero_art(canvas, item)
            self.draw_hero(canvas)
            draw_facts()
            draw_cast()
            draw_similar()
            if item["kind"] == "series":
                self.episodes_block(episodes, entries, item)
            key = str(self.preferences.get("tmdb_key") or "").strip()
            if key and item["id"] not in self.tmdb_cache:
                original = item.get("raw_title") or item["title"]
                year = tmdb.year_of(original, summary["year"])
                self.run(lambda: tmdb.extras(key, original, item["kind"], year, info.get("tmdb_id") or info.get("tmdb")),
                         apply_extra, lambda _: None, executor=self.info_workers)
            elif item["id"] in self.tmdb_cache:
                apply_extra(self.tmdb_cache[item["id"]])
            self.enrich_genres(item["kind"], lambda: draw_similar() if state["genres"] else None)
        self.run(lambda: data.details(source, item), done,
                 lambda error: status.configure(text=error_text(error)) if status.winfo_exists() else None)

    def person_photo(self, name, size):
        key = ("person", name, size)
        if key not in self.logo_cache:
            self.remember_photo(self.logo_cache, key, ImageTk.PhotoImage(ui.person_avatar(name, size)), 600)
        return self.logo_cache[key]

    def load_person(self, widget, person, size):
        key = ("person-photo", person["photo"], size)
        if key in self.logo_cache:
            widget.configure(image=self.logo_cache[key])
            return

        def done(image):
            if image is None:
                return
            photo = ImageTk.PhotoImage(image)
            self.remember_photo(self.logo_cache, key, photo, 600)
            if widget.winfo_exists():
                widget.configure(image=photo)
        name = person["name"]
        self.art_jobs.append(self.run(
            lambda: (lambda picture: ui.person_avatar(name, size, picture) if picture is not None else None)(
                safe(download_image, person["photo"])), done, lambda _: None, artwork=True))

    def remember_genres(self, item, genres):
        if not genres or self.genre_cache.get(item["id"]) == genres:
            return
        self.genre_cache[item["id"]] = list(genres)
        if not self.genre_save_job:
            self.genre_save_job = self.root.after(3000, self.save_genres)

    def save_genres(self):
        self.genre_save_job = None
        try:
            data.write_json(data.STATE.with_name("genres.json"), self.genre_cache)
        except OSError:
            pass

    def similar_items(self, item, genres, titles=()):
        pool = [i for i in self.by_kind.get(item["kind"], []) if i["id"] != item["id"]]
        picked, seen = [], set()
        if titles:
            wanted = {tmdb.clean_title(t).casefold() for t in titles if t}
            for candidate in pool:
                if tmdb.clean_title(candidate["title"]).casefold() in wanted and candidate["id"] not in seen:
                    picked.append(candidate)
                    seen.add(candidate["id"])
        if genres:
            wanted = {g.casefold() for g in genres}
            scored = []
            for candidate in pool:
                theirs = {g.casefold() for g in self.genre_cache.get(candidate["id"], [])}
                overlap = len(wanted & theirs)
                if overlap and candidate["id"] not in seen:
                    scored.append((-overlap, -score(candidate), candidate))
            scored.sort(key=lambda entry: entry[:2])
            picked += [entry[2] for entry in scored]
        return picked[:20] if len(picked) >= 3 else []

    def enrich_genres(self, kind, update):
        """Fetch genres of the best titles in the background, so "Meer zoals dit" can match on genre."""
        if not self.source or self.enriching.get(kind):
            return
        candidates = [i for i in self.best.get(kind, [])[:160] if i.get("sid") and i["id"] not in self.genre_cache][:40]
        if not candidates:
            return
        self.enriching[kind] = True
        source = self.source
        remaining = {"count": len(candidates)}

        def finished(item, result):
            remaining["count"] -= 1
            if result:
                genres = summarize(result[0])["genres"]
                if genres:
                    self.remember_genres(item, genres)
            if remaining["count"] % 8 == 0 or remaining["count"] <= 0:
                try:
                    update()
                except tk.TclError:
                    pass
            if remaining["count"] <= 0:
                self.enriching[kind] = False
        for candidate in candidates:
            self.run(lambda c=candidate: safe(data.details, source, c), lambda result, c=candidate: finished(c, result),
                     lambda _, c=candidate: finished(c, None), executor=self.info_workers)

    def episodes_block(self, block, entries, series=None):
        self.episode_anchor = label(block, "Afleveringen", 16, TEXT, BG, True)
        self.episode_anchor.pack(anchor="w", pady=(S(18), S(12)))
        seasons = list(dict.fromkeys(entry["group"] for entry in entries))
        if not seasons:
            label(block, "Geen afleveringen gevonden.", 10, MUTED).pack(anchor="w")
            return
        name = (series or {}).get("title", "")
        for entry in entries:
            entry.setdefault("series", name)
            entry.setdefault("series_sid", (series or {}).get("sid", ""))
            entry.setdefault("image", (series or {}).get("image", ""))
        counts = {s: sum(1 for e in entries if e["group"] == s) for s in seasons}
        tools = tk.Frame(block, bg=BG)
        rows = tk.Frame(block, bg=BG)
        ids = {e["id"] for e in entries}
        latest = max((p for p in self.progress.values() if p["item"].get("id") in ids),
                     key=lambda p: p.get("updated", 0), default=None)
        start = latest["item"].get("group") if latest and latest["item"].get("group") in seasons else seasons[0]
        current = {"season": start}

        def show(season):
            current["season"] = season
            for value, pill in pills.items():
                pill.update_pill(kind="chip_on" if value == season else "chip")
            for child in rows.winfo_children():
                child.destroy()
            for index, entry in enumerate([e for e in entries if e["group"] == season], 1):
                watched = self.progress.get(entry["id"], {})
                seen = entry["id"] in self.watched
                saved = self.downloaded_file(entry["id"])
                job = self.download_jobs.get(entry["id"])
                if seen and not job:
                    subtitle = "✓ Gezien" + ("  ·  gedownload" if saved else "")
                elif saved:
                    subtitle = "✓ Gedownload, ook offline te bekijken"
                elif job:
                    subtitle = "Downloaden…"
                elif watched.get("duration"):
                    subtitle = minutes_left(watched["duration"] - watched["time"])
                else:
                    subtitle = season
                actions = [] if saved or job else [
                    ("download", lambda e=entry: (self.download(e, quiet=True), show(current["season"])))]
                actions.insert(0, ("check", lambda e=entry, v=seen: (self.set_watched(e["id"], not v), show(current["season"])),
                                   "accent" if seen else "ghost"))
                actions.append(("play", lambda e=entry: self.open_player(e, entries)))
                self.list_row(rows, "✓" if seen else str(index), entry["title"], subtitle,
                              lambda e=entry: self.open_player(e, entries), actions,
                              highlight=bool(watched) or bool(saved) or seen, dim=seen)

        def download_season():
            chosen = [e for e in entries if e["group"] == current["season"]
                      and not self.downloaded_file(e["id"]) and e["id"] not in self.download_jobs]
            for entry in chosen:
                self.download(entry, quiet=True)
            self.toast(f"{len(chosen)} afleveringen toegevoegd aan Downloads" if chosen else "Dit seizoen staat al op je pc",
                       "download")
            show(current["season"])
        pills = self.chip_strip(block, [(s, s, counts[s]) for s in seasons], start, show, padx=0, pady=(0, 10))
        tools.pack(fill="x", pady=(0, S(8)))
        Pill(tools, "Seizoen downloaden", download_season, kind="ghost", icon="download", h=36, padx=16).pack(side="left")
        label(tools, "Voor onderweg of op het vliegtuig", 9, DIM, BG).pack(side="left", padx=S(12))
        rows.pack(fill="x")
        show(start)

    def list_row(self, parent, index, title, subtitle, command, actions=(), highlight=False, dim=False):
        row = tk.Frame(parent, bg=BG, padx=S(14), pady=S(10))
        row.pack(fill="x", pady=1)
        label(row, index, 12, ACCENT_SOFT if highlight else DIM, BG, True, width=3, anchor="w").pack(side="left")
        texts = tk.Frame(row, bg=BG)
        texts.pack(side="left", fill="x", expand=True, padx=(S(8), 0))
        label(texts, elide(title, 11, S(640), True), 11, MUTED if dim else TEXT, BG, True).pack(anchor="w")
        if subtitle:
            label(texts, elide(subtitle, 9, S(640)), 9, ACCENT_SOFT if highlight else MUTED).pack(anchor="w")
        for action_item in reversed(actions):
            icon, action = action_item[0], action_item[1]
            kind = action_item[2] if len(action_item) > 2 else ("primary" if icon == "play" else "ghost")
            Pill(row, "", action, kind=kind, icon=icon, h=36).pack(side="right", padx=(S(8), 0))
        ui.bind_hover(row, lambda: ui.set_bg(row, PANEL), lambda: ui.set_bg(row, BG))
        ui.bind_click(row, command)
        return row

    # ------------------------------------------------------------ rows of cards

    def section(self, title, entries, grid=False, more=None, padx=44, empty=None, ranked=False, on_card=None, parent=None):
        if not entries and not grid:
            return
        block = tk.Frame(parent or self.content, bg=BG)
        block.pack(fill="x", padx=S(padx), pady=(S(10) if title else 0, S(24)))
        bar = None
        if title:
            bar = tk.Frame(block, bg=BG)
            bar.pack(fill="x", pady=(0, S(12)))
            head = label(bar, title, 16, TEXT, BG, True)
            head.pack(side="left")
            if more:
                head.configure(cursor="hand2")
                head.bind("<Button-1>", lambda _: self.select(more))
                Pill(bar, "", lambda: self.select(more), kind="quiet", icon="next", h=30).pack(side="left", padx=S(4))
        if not entries:
            box = tk.Frame(block, bg=BG)
            box.pack(fill="x", pady=S(40))
            icon = "search" if self.query.get() else "heart" if self.tab == "favorites" else "film"
            Pill(box, "", None, kind="ghost", icon=icon, h=64).pack()
            label(box, "Niets gevonden", 15, TEXT, BG, True).pack(pady=(S(14), S(4)))
            label(box, empty or "Probeer een andere zoekterm of categorie.", 10, MUTED).pack()
            return
        if grid:
            self.has_grid = True
            landscape = all(i["kind"] == "live" for i in entries)
            card_w, gap = S(WIDE[0] if landscape else CARD[0]), S(20)
            columns = max(2, (self.page_width() - 2 * S(padx) + gap) // (card_w + gap))
            cards = tk.Frame(block, bg=BG)
            cards.pack(anchor="w")
            visible = entries[:self.limit]
            chunk = columns * 2

            def build(start):
                if not cards.winfo_exists():
                    return
                for index in range(start, min(start + chunk, len(visible))):
                    self.card(cards, visible[index], landscape, entries).grid(
                        row=index // columns, column=index % columns, padx=(0, gap), pady=(0, S(26)), sticky="nw")
                if start + chunk < len(visible):
                    self.defer(lambda: build(start + chunk))
            build(0)
            if len(entries) > self.limit:
                Pill(block, f"Meer tonen  ·  nog {number(len(entries) - self.limit)}", self.more, kind="ghost").pack(
                    side="bottom", anchor="w")
            return
        rail = tk.Canvas(block, bg=BG, highlightthickness=0, height=S(40), xscrollincrement=S(44))
        rail.hscroll = True
        rail.pack(fill="x")
        strip = tk.Frame(rail, bg=BG)
        rail.create_window(0, 0, window=strip, anchor="nw")
        strip.bind("<Configure>", lambda _: rail.configure(scrollregion=(0, 0, strip.winfo_reqwidth(), strip.winfo_reqheight()),
                                                             height=strip.winfo_reqheight()))
        shown = list(enumerate(entries[:20], 1))

        def add(start):
            if not strip.winfo_exists():
                return
            for position, item in shown[start:start + 6]:
                tile = self.card(strip, item, None, entries, rank=position if ranked else None)
                tile.pack(side="left", padx=(0, S(18)), anchor="n")
                if on_card:
                    on_card(tile, item)
            if start + 6 < len(shown):
                self.defer(lambda: add(start + 6))
        add(0)
        if bar is not None and len(entries) > 4:
            Pill(bar, "", lambda: self.glide(rail, rail.winfo_width() * 0.8), kind="ghost", icon="next", h=32).pack(side="right")
            Pill(bar, "", lambda: self.glide(rail, -rail.winfo_width() * 0.8), kind="ghost", icon="back", h=32).pack(side="right", padx=S(8))

    def more(self):
        self.limit += 30
        self.render()

    def card(self, parent, item, landscape=None, playlist=None, rank=None):
        live = item["kind"] == "live"
        landscape = live if landscape is None else landscape
        w, h = (S(WIDE[0]), S(WIDE[1])) if landscape else (S(CARD[0]), S(CARD[1]))
        watched = self.progress.get(item["id"], {})
        ratio = max(0, min(1, watched["time"] / watched["duration"])) if watched.get("duration") else None
        tile = tk.Frame(parent, bg=BG)
        offset = 0
        if rank:
            number_w, overlap = ui.rank_geometry(rank, h)
            offset = number_w - overlap
            first = ui.rank_placeholder(rank, w, h)
        else:
            first = ui.placeholder_photo(w, h)
        art = tk.Label(tile, bg=BG, bd=0, cursor="hand2", image=first)
        art.photos = (first, first)
        art.hovered = False
        art.pack(anchor="w")
        title = label(tile, elide(item["title"], 10, w, True), 10, TEXT, BG, True, cursor="hand2")
        title.pack(anchor="w", pady=(S(9), 0), padx=(offset, 0))
        if item["id"] in self.watched and ratio is None:
            subtitle = "✓ Gezien  ·  " + KIND_LABEL.get(item["kind"], "")
        elif ratio is not None:
            subtitle = minutes_left(watched["duration"] - watched["time"])
        elif live:
            cached = self.guide_cache.get(item.get("sid"))
            now = current_program(cached[1]) if cached else None
            subtitle = f"Nu: {now['title']}" if now and now["title"] else str(item.get("group") or "Live TV")
        else:
            group = str(item.get("group") or "")
            subtitle = KIND_LABEL.get(item["kind"], "") + (f"  ·  {group}" if group and group != "Overige" else "")
            if score(item) > 0:
                subtitle = f"★ {score(item):.1f}  ·  " + subtitle
        sub = label(tile, elide(subtitle, 9, w), 9, MUTED)
        sub.pack(anchor="w", pady=(1, 0), padx=(offset, 0))

        def set_now(rows):
            current = current_program(rows)
            if current and current["title"] and sub.winfo_exists():
                sub.configure(text=elide(f"Nu: {current['title']}", 9, w), fg=SOFT)
        tile.set_now = set_now

        def hover(flag):
            art.hovered = flag
            if art.winfo_exists():
                art.configure(image=art.photos[1 if flag else 0])
                title.configure(fg=ACCENT_SOFT if flag else TEXT)
        lives = [i for i in (playlist or []) if i["kind"] == "live"]
        action = (lambda: self.open_player(item, lives)) if live else (lambda: self.show_detail(item))
        for widget in (art, title):
            widget.bind("<Enter>", lambda _: hover(True))
            widget.bind("<Leave>", lambda _: hover(False))
            widget.bind("<ButtonRelease-1>", lambda _: action())
        self.load_art(art, item, (w, h), ratio, rank)
        return tile

    def load_art(self, widget, item, size, ratio=None, rank=None):
        url = art_url(item, "image")
        title, kind = str(item["title"]), item["kind"]
        w, h = size
        key = (url or title, kind, w, h, None if ratio is None else round(ratio, 2), rank)
        if key in self.art_cache:
            self.art_cache.move_to_end(key)
            widget.photos = self.art_cache[key]
            widget.configure(image=widget.photos[1 if widget.hovered else 0])
            return

        def build():
            if kind == "live":
                logo = safe(cover, url, (S(240), S(240)), True) if url else None
                base = ui.channel_tile(title, w, h, logo)
            else:
                base = (safe(cover, url, size) if url else None) or ui.poster_art(title, kind, w, h)
            images = ui.card_images(base, ratio)
            return ui.rank_images(images, rank, h) if rank else images
        generation = self.generation

        def done(images):
            photos = ui.LazyPhotos(images)  # the hover picture is only made when the mouse comes by
            self.remember_photo(self.art_cache, key, photos, 260)
            if generation != self.generation or not widget.winfo_exists():
                return
            widget.photos = photos
            widget.configure(image=widget.photos[1 if widget.hovered else 0])
        self.art_jobs.append(self.run(build, done, lambda _: None, artwork=True))

    def load_logo(self, widget, item, size):
        url = art_url(item, "image")
        title = str(item["title"])
        key = ("logo", url or title, title, size)
        if key in self.logo_cache:
            widget.photo = self.logo_cache[key]
            widget.configure(image=widget.photo)
            return

        def done(image):
            photo = ImageTk.PhotoImage(image)
            self.remember_photo(self.logo_cache, key, photo, 600)
            if widget.winfo_exists():
                widget.photo = photo
                widget.configure(image=photo)
        self.art_jobs.append(self.run(lambda: ui.logo_badge(title, size, safe(cover, url, (S(160), S(160)), True) if url else None),
                                      done, lambda _: None, artwork=True))

    # ------------------------------------------------------------ programme guide data

    def fetch_guide(self, item, done, failed=lambda _: None, full=False):
        sid = item.get("sid")
        if not sid or not self.source:
            done([])
            return
        key = ("full", sid) if full else sid
        cached = self.guide_cache.get(key)
        if cached and monotonic() - cached[0] < GUIDE_TTL:
            done(cached[1])
            return
        source = self.source
        shift = int(float(self.preferences.get("epg_offset", 0) or 0) * 3600)
        loader = data.full_guide if full else data.guide

        def store(rows):
            rows = sorted((dict(r, start=r["start"] + shift, end=r["end"] + shift)
                           for r in rows if r.get("start") and r.get("end")), key=lambda r: r["start"])
            self.guide_cache[key] = (monotonic(), rows)
            if full:
                self.guide_cache[sid] = (monotonic(), rows)
            done(rows)
        self.art_jobs.append(self.run(lambda: loader(source, sid), store, failed, executor=self.guide_workers))

    def archivable(self, channel, program):
        if not channel.get("archive") or not self.source:
            return False
        moment = time()
        if program["start"] >= moment:
            return False
        if program.get("archive") is not None:
            return bool(program["archive"])
        days = int(channel.get("archive_days") or 0)
        return days <= 0 or moment - program["start"] <= days * 86400

    def play_catchup(self, channel, program):
        if not self.source or not program.get("label"):
            self.toast("Dit programma kan niet worden teruggekeken", "close")
            return
        minutes = max(1, round((program["end"] - program["start"]) / 60))
        item = {"id": f"{channel['id']}|catchup|{program['label']}", "kind": "catchup",
                "title": program.get("title") or "Programma", "group": channel.get("title", ""),
                "image": channel.get("image", ""), "channel": channel.get("title", ""),
                "url": data.timeshift_url(self.source, channel["sid"], program["label"], minutes),
                "when": f"{hhmm(program['start'])} – {hhmm(program['end'])}"}
        self.open_player(item)

    # ------------------------------------------------------------ recordings

    def save_recordings(self):
        try:
            data.write_json(data.STATE.with_name("recordings.json"), data.seal(self.recordings, self.source))
        except OSError as error:
            self.toast(elide(error_text(error), 10, S(480), True), "close")

    def recording_for(self, channel, program):
        return next((r for r in self.recordings if r.get("channel_id") == channel["id"]
                     and int(r.get("start", 0)) == int(program["start"]) and r.get("status") in ("planned", "recording")), None)

    def plan_recording(self, channel, program):
        if self.recording_for(channel, program):
            return
        title = program.get("title") or "Programma"
        self.recordings.append({
            "id": uuid4().hex[:12], "channel_id": channel["id"], "channel": channel.get("title", ""),
            "image": channel.get("image", ""), "url": channel.get("url", ""), "title": title,
            "start": int(program["start"]), "end": int(program["end"]), "status": "planned",
            "store": str(data.STATE.with_name("downloads.json"))})
        self.save_recordings()
        when = "nu" if program["start"] <= time() else f"om {hhmm(program['start'])}"
        self.toast(f"Opname gepland: {elide(title, 10, S(260), True)} · start {when}", "record")
        self.recording_tick(reschedule=False)

    def cancel_recording(self, entry):
        recorder = self.recorders.pop(entry["id"], None)
        if recorder:
            finish = lambda _=None: self.finish_recording(entry, stopped=True)
            self.run(recorder.close, finish, finish)  # VLC may need a moment to stop: not on the screen
        else:
            self.recordings = [r for r in self.recordings if r is not entry]
            self.save_recordings()
            self.toast("Opname geannuleerd", "close")
        if self.tab == "downloads":
            self.render()

    def finish_recording(self, entry, stopped=False):
        path = Path(entry.get("file", ""))
        for extra in entry.get("extra", []):  # parts recorded after switching channel: glue them on
            try:
                with path.open("ab") as output, open(extra, "rb") as piece:
                    shutil.copyfileobj(piece, output, 1024 * 1024)
                Path(extra).unlink(missing_ok=True)
            except OSError:
                pass
        size = path.stat().st_size if path.is_file() else 0
        self.recordings = [r for r in self.recordings if r is not entry]
        self.save_recordings()
        if size < 256 * 1024:
            path.unlink(missing_ok=True)
            self.toast(f"Opname mislukt: {elide(entry['title'], 10, S(260), True)}", "close")
            return
        day = datetime.fromtimestamp(entry["start"]).strftime("%d/%m")
        done = {"id": f"rec|{entry['id']}", "kind": "movie", "title": f"{entry['title']}  ·  {entry['channel']} {day}",
                "group": "Opname", "image": entry.get("image", ""), "file": str(path), "saved": time(), "size": size,
                "url": ""}
        if entry.get("store") == str(data.STATE.with_name("downloads.json")):
            self.downloaded = [e for e in self.downloaded if e.get("id") != done["id"]] + [done]
            self.save_downloads()
        else:  # recorded for another profile
            store = Path(entry["store"])
            try:
                existing = data.read_json(store, [])
                data.write_json(store, (existing if isinstance(existing, list) else []) + [done])
            except OSError:
                pass
        self.toast(f"Opname {'gestopt' if stopped else 'klaar'}: {elide(entry['title'], 10, S(260), True)} · bij Downloads",
                   "check")
        if self.tab == "downloads":
            self.render()

    def recording_path(self, title, channel, start):
        folder = Path(self.preferences.get("download_folder", data.STATE.parent / "Downloads")) / "Opnames"
        name = re.sub(r'[^\w -]', "_", f"{title} - {channel}")[:80].strip() or "Opname"
        stamp = datetime.fromtimestamp(start).strftime("%Y-%m-%d %H.%M")
        return folder / f"{name} {stamp}.ts"

    def active_recording(self, channel_id):
        return next((r for r in self.recordings if r.get("channel_id") == channel_id and r.get("status") == "recording"
                     and r.get("id") in self.recorders), None)

    def record_now(self, channel, end, title=None):
        """Start recording the channel right away (the red R in the player). While you watch that channel, the
        recording is taken from what Zono already receives: no extra connection to your provider."""
        if self.active_recording(channel["id"]):
            return
        start = int(time())
        title = title or channel.get("title", "Opname")
        path = self.recording_path(title, channel.get("title", ""), start)
        session = self.session
        buffer = session.get("buffer") if session and session["live"] and session["item"].get("id") == channel["id"] else None
        try:
            recorder = engine_module.BufferTap(buffer, path) if buffer is not None else \
                engine_module.Recorder(data.check_url(channel["url"]), path)
        except (OSError, ValueError, AttributeError) as error:
            self.toast(f"Opnemen lukt niet: {elide(error_text(error), 10, S(320), True)}", "close")
            return
        entry = {"id": uuid4().hex[:12], "channel_id": channel["id"], "channel": channel.get("title", ""),
                 "image": channel.get("image", ""), "url": channel.get("url", ""), "title": title, "start": start,
                 "end": int(end), "status": "recording", "file": str(path), "mode": "buffer" if buffer is not None else "direct",
                 "store": str(data.STATE.with_name("downloads.json"))}
        self.recordings.append(entry)
        self.recorders[entry["id"]] = recorder
        self.save_recordings()
        self.toast(f"Opname gestart · tot {hhmm(end)}", "record")

    def hand_over_recordings(self, buffer):
        """You switch channel while recording from the live buffer: continue with a direct recording."""
        for entry in self.recordings:
            recorder = self.recorders.get(entry.get("id"))
            if isinstance(recorder, engine_module.BufferTap) and recorder.buffer is buffer:
                recorder.close()
                extra = Path(entry["file"]).with_name(Path(entry["file"]).stem + f" deel {len(entry.get('extra', [])) + 2}.ts")
                try:
                    self.recorders[entry["id"]] = engine_module.Recorder(data.check_url(entry["url"]), extra)
                    entry.setdefault("extra", []).append(str(extra))
                    entry["mode"] = "direct"
                except (OSError, ValueError, AttributeError):
                    self.recorders.pop(entry["id"], None)
                    self.finish_recording(entry, stopped=True)
        self.save_recordings()

    def recording_tick(self, reschedule=True):
        """Start and stop planned recordings. Zono has to be open (it may be minimised)."""
        try:
            self._recording_tick()
        except Exception:
            self.report_error(*sys.exc_info())
        if reschedule:
            self.root.after(10000, self.recording_tick)

    def _recording_tick(self):
        now = time()
        changed = False
        for entry in list(self.recordings):
            status = entry.get("status")
            if status == "planned" and now >= entry["end"]:
                entry["status"] = "missed"
                changed = True
            elif status == "planned" and now >= entry["start"] - 60:
                folder = Path(self.preferences.get("download_folder", data.STATE.parent / "Downloads")) / "Opnames"
                name = re.sub(r'[^\w -]', "_", f"{entry['title']} - {entry['channel']}")[:80].strip() or "Opname"
                stamp = datetime.fromtimestamp(entry["start"]).strftime("%Y-%m-%d %H.%M")
                path = folder / f"{name} {stamp}.ts"
                session = self.session
                buffer = session.get("buffer") if session and session["live"] and \
                    session["item"].get("id") == entry["channel_id"] else None
                try:
                    self.recorders[entry["id"]] = engine_module.BufferTap(buffer, path) if buffer is not None else \
                        engine_module.Recorder(data.check_url(entry["url"]), path)
                except (OSError, ValueError, AttributeError) as error:
                    entry["status"] = "failed"
                    entry["error"] = error_text(error)
                    self.toast(f"Opname kon niet starten: {elide(entry['title'], 10, S(240), True)}", "close")
                else:
                    entry.update(status="recording", file=str(path))
                    self.toast(f"Opname gestart: {elide(entry['title'], 10, S(260), True)}", "record")
                changed = True
            elif status == "recording":
                recorder = self.recorders.get(entry["id"])
                if recorder is None:  # Zono was closed during the recording
                    entry["status"] = "failed"
                    changed = True
                elif now >= entry["end"] + 120 or recorder.state() in (6, 7):
                    self.recorders.pop(entry["id"], None)
                    finish = lambda _=None, e=entry: self.finish_recording(e)
                    self.run(recorder.close, finish, finish)
        if changed:
            self.save_recordings()
            if self.tab == "downloads":
                self.render()

    def program_sheet(self, channel, program, playlist=None):
        """What you can do with one programme from the guide: watch, watch again, record."""
        card = self.sheet(520, 0)
        body = tk.Frame(card, bg=SIDE, padx=S(30), pady=S(26))
        body.pack(fill="both", expand=True)
        moment = time()
        current = program["start"] <= moment < program["end"]
        past = program["end"] <= moment
        label(body, ("NU OP " if current else "") + str(channel.get("title", "")).upper(), 8, ACCENT_SOFT, SIDE, True).pack(anchor="w")
        label(body, program.get("title") or "Programma", 18, TEXT, SIDE, True, wraplength=S(440), justify="left").pack(
            anchor="w", pady=(S(4), S(2)))
        day = datetime.fromtimestamp(program["start"])
        when = ("Vandaag" if day.date() == datetime.now().date() else day.strftime("%A %d/%m").capitalize())
        label(body, f"{when}  ·  {hhmm(program['start'])} – {hhmm(program['end'])}", 10, MUTED, SIDE).pack(anchor="w")
        if program.get("description"):
            label(body, str(program["description"])[:420], 10, SOFT, SIDE, wraplength=S(440), justify="left").pack(
                anchor="w", pady=(S(12), 0))
        buttons = tk.Frame(body, bg=SIDE)
        buttons.pack(anchor="w", pady=(S(20), 0))

        def done(action):
            if self.sheet_close:
                self.sheet_close()
            action()
        if current:
            Pill(buttons, "Kijken", lambda: done(lambda: self.open_player(channel, playlist or [channel])),
                 kind="primary", icon="play", h=42, padx=18).pack(side="left", padx=(0, S(8)))
        if past and self.archivable(channel, program):
            Pill(buttons, "Terugkijken", lambda: done(lambda: self.play_catchup(channel, program)),
                 kind="primary", icon="refresh", h=42, padx=18).pack(side="left", padx=(0, S(8)))
        if not past and channel.get("url"):
            planned = self.recording_for(channel, program)
            if planned:
                Pill(buttons, "Opname annuleren", lambda: done(lambda: (self.cancel_recording(planned), self.render())),
                     kind="ghost", icon="close", h=42, padx=18).pack(side="left")
            else:
                Pill(buttons, "Opnemen", lambda: done(lambda: (self.plan_recording(channel, program), self.render())),
                     kind="ghost", icon="record", h=42, padx=18).pack(side="left")
        if not past:
            label(body, "Opnames lopen zolang Zono open staat (geminimaliseerd mag). Ze verschijnen daarna bij Downloads. "
                        "Kijk je tegelijk naar iets anders, dan gebruikt dat een tweede verbinding met je provider.",
                  9, MUTED, SIDE, wraplength=S(440), justify="left").pack(anchor="w", pady=(S(16), 0))
        elif not self.archivable(channel, program):
            label(body, "Deze zender biedt dit programma niet aan om terug te kijken.", 9, MUTED, SIDE).pack(
                anchor="w", pady=(S(16), 0))

    def zap_input(self, digit, items, jump):
        """Type a channel number like on a remote control."""
        if not items:
            return
        self.zap_digits = (getattr(self, "zap_digits", "") + digit)[-4:]
        if getattr(self, "zap_job", None):
            self.root.after_cancel(self.zap_job)
        overlay = getattr(self, "zap_overlay", None)
        if overlay is None or not overlay.winfo_exists():
            overlay = tk.Frame(self.root, bg="#0b0b0f", padx=S(26), pady=S(14), highlightthickness=1,
                               highlightbackground=LINE)
            overlay.number = label(overlay, "", 40, TEXT, "#0b0b0f", True)
            overlay.number.pack(anchor="e")
            overlay.name = label(overlay, "", 11, SOFT, "#0b0b0f")
            overlay.name.pack(anchor="e")
            self.zap_overlay = overlay
        overlay.place(relx=1, x=-S(40), y=S(40), anchor="ne")
        overlay.lift()
        index = int(self.zap_digits) - 1
        overlay.number.configure(text=self.zap_digits)
        overlay.name.configure(text=elide(items[index]["title"], 11, S(260)) if 0 <= index < len(items) else "Geen zender")

        def commit():
            self.zap_job = None
            digits, self.zap_digits = self.zap_digits, ""
            target = int(digits) - 1
            if 0 <= target < len(items):
                jump(target)
            if overlay.winfo_exists():
                overlay.after(900, lambda: overlay.winfo_exists() and overlay.place_forget())
        self.zap_job = self.root.after(1300, commit)

    # ------------------------------------------------------------ live tv

    def live_view(self, pool, entries):
        top = tk.Frame(self.content, bg=BG)
        top.pack(fill="x", padx=S(44))
        frame = tk.Frame(top, bg="#000000")
        frame.pack(side="left", anchor="n")
        frame.pack_propagate(False)
        bar = tk.Frame(frame, bg=SIDE, height=S(50), padx=S(12))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        surface = tk.Frame(frame, bg="#000000")
        surface.pack(fill="both", expand=True)
        self.live_slot = surface
        idle = tk.Frame(surface, bg="#000000")
        idle.place(relx=.5, rely=.5, anchor="center")
        Pill(idle, "", None, kind="ghost", icon="tv", h=56, bg="#000000").pack()
        idle_text = label(idle, "Kies een zender om te kijken" if entries else "Geen zenders gevonden", 12, MUTED, "#000000")
        idle_text.pack(pady=(S(12), 0))

        info = tk.Frame(top, bg=BG)
        info.pack(side="left", fill="both", expand=True, padx=(S(34), 0))
        label(info, "NU LIVE", 9, MUTED, BG, True).pack(anchor="w")
        badge_row = tk.Frame(info, bg=BG)
        badge_row.pack(anchor="w", pady=(S(10), 0))
        badge = Pill(badge_row, "LIVE", None, kind="live", h=22, px=9.5, radius=5, weight="bold")
        channel = label(badge_row, "", 11, SOFT)
        now = label(info, "Kies een zender", 24, TEXT, BG, True, justify="left")
        now.pack(anchor="w", pady=(S(8), 0))
        when = label(info, "Klik op een zender hieronder, of zap met ↑ en ↓.", 10, MUTED, BG, justify="left")
        when.pack(anchor="w", pady=(S(4), 0))
        meter = tk.Canvas(info, bg=BG, height=S(14), width=S(340), highlightthickness=0)
        meter.pack(anchor="w", pady=(S(14), 0))
        upcoming = label(info, "", 10, MUTED, BG, justify="left")
        upcoming.pack(anchor="w", pady=(S(4), 0))
        actions = tk.Frame(info, bg=BG)
        actions.pack(anchor="w", pady=(S(18), 0))
        selected = {"item": None, "index": -1}
        shown = entries[:self.limit * 2]

        def fullscreen(_=None):
            if selected["item"] and self.session:
                self.open_player(self.session["item"], self.session["playlist"], fullscreen=True)

        def set_volume(value):
            self.set_volume(value)
            mute.update_pill(icon="volume")

        def toggle_mute():
            self.toggle_mute()
            mute.update_pill(icon="mute" if self.muted else "volume")
        mute = Pill(bar, "", toggle_mute, kind="quiet", icon="mute" if self.muted else "volume", h=34)
        mute.pack(side="left")
        Slider(bar, 110, self.volume, 100, command=set_volume, bg=SIDE).pack(side="left", padx=(S(4), 0))
        big = Pill(bar, "", fullscreen, kind="quiet", icon="expand", h=34)
        big.pack(side="right")
        idle.bind("<Double-Button-1>", fullscreen)
        surface.bind("<Configure>", lambda _: self.queue_place())

        def favorite():
            if selected["item"]:
                on = self.toggle(selected["item"])
                fav.update_pill(icon="heart_fill" if on else "heart")
        fav = Pill(actions, "Favoriet", favorite, kind="ghost", icon="heart", h=42, padx=18)
        fav.pack(side="left", padx=(0, S(10)))
        Pill(actions, "TV-gids", lambda: self.select("guide"), kind="ghost", icon="guide", h=42, padx=18).pack(side="left")
        big.set_enabled(False)
        fav.set_enabled(False)

        def layout(width=None):
            if not frame.winfo_exists():
                return
            width = width or self.page_width()
            video_w = max(S(420), min(S(820), int((width - S(88)) * 0.56)))
            frame.configure(width=video_w, height=int(video_w * 9 / 16) + S(50))
            wrap = max(S(240), width - S(88) - video_w - S(40))
            for widget in (now, when, upcoming):
                widget.configure(wraplength=wrap)
            meter.configure(width=min(S(340), wrap))
        layout()
        self.live_layout = layout

        self.category_chips(pool, pady=(28, 16))
        lower = tk.Frame(self.content, bg=BG)
        lower.pack(fill="x", padx=S(44), pady=(0, S(34)))
        listing = tk.Frame(lower, bg=BG)
        listing.pack(side="left", fill="both", expand=True, anchor="n")
        guide = tk.Frame(lower, bg=PANEL, padx=S(20), pady=S(18))
        guide.pack(side="left", anchor="n", padx=(S(24), 0))
        label(guide, "Nu en straks", 13, TEXT, PANEL, True).pack(anchor="w")
        programs = tk.Frame(guide, bg=PANEL)
        programs.pack(fill="x", pady=(S(10), 0))
        label(programs, "Kies een zender om de\nprogrammagids te zien.", 10, MUTED, PANEL, justify="left").pack(anchor="w")
        tk.Frame(guide, bg=PANEL, width=S(300), height=1).pack()

        rows = []
        first = tk.Frame(listing, bg=BG)
        first.pack(fill="x")
        later_rows = tk.Frame(listing, bg=BG)
        later_rows.pack(fill="x")

        def build_rows(upto):
            """Build channel rows up to `upto`: the first screenful at once, the rest in small deferred batches."""
            while len(rows) < min(upto, len(shown)) and later_rows.winfo_exists():
                index = len(rows)
                rows.append(self.channel_row(first if index < 14 else later_rows, index, shown[index],
                                             lambda i=index: choose(i)))
            if len(rows) < len(shown):
                self.defer(lambda: build_rows(len(rows) + 8))
        build_rows(14)
        if len(entries) > len(shown):
            Pill(listing, f"Meer zenders  ·  nog {number(len(entries) - len(shown))}", self.more, kind="ghost").pack(anchor="w", pady=S(12))
        if not entries:
            label(listing, "Geen zenders in deze selectie.", 11, MUTED).pack(anchor="w", pady=S(20))
        for index, item in enumerate(shown[:14]):
            if item.get("sid") and self.source:
                self.fetch_guide(item, lambda r, i=index: rows[i].set_now(r) if rows[i].winfo_exists() else None)

        def draw_meter(current, moment):
            meter.delete("all")
            length = int(meter.cget("width")) - S(90)
            ratio = (moment - current["start"]) / max(1, current["end"] - current["start"])
            y = S(7)
            meter.create_line(S(2), y, length, y, width=S(4), fill=RAISED, capstyle="round")
            meter.create_line(S(2), y, S(2) + (length - S(2)) * ratio, y, width=S(4), fill=TEXT, capstyle="round")
            meter.create_text(length + S(12), y, text=minutes_left(current["end"] - moment), fill=SOFT, anchor="w", font=(FONT, 9))

        def fill_programs(rows_data):
            for child in programs.winfo_children():
                child.destroy()
            moment = time()
            current = current_program(rows_data, moment)
            later = [r for r in rows_data if r["start"] >= (current["end"] if current else moment)]
            if current:
                now.configure(text=current["title"] or "Programma")
                when.configure(text=f'{hhmm(current["start"])} – {hhmm(current["end"])}')
                draw_meter(current, moment)
            if later:
                upcoming.configure(text=f'Straks  {hhmm(later[0]["start"])}  {later[0]["title"] or "Programma"}')
            for row in [r for r in rows_data if r["end"] > moment][:10]:
                active = row is current
                line = tk.Frame(programs, bg=PANEL)
                line.pack(fill="x", pady=S(4))
                label(line, hhmm(row["start"]) or "--:--", 10, ACCENT_SOFT if active else MUTED, PANEL, active,
                      width=6, anchor="w").pack(side="left", anchor="n")
                label(line, elide(row["title"] or "Programma", 10, S(230), active), 10, TEXT if active else SOFT,
                      PANEL, active).pack(side="left", anchor="n")
            if not programs.winfo_children():
                label(programs, "Geen programma’s beschikbaar.", 10, MUTED, PANEL).pack(anchor="w")

        def choose(index):
            if not shown or not 0 <= index < len(shown):
                return
            item = shown[index]
            playing = bool(self.session and self.session["item"].get("id") == item["id"])
            if item is selected["item"] and playing:
                return
            build_rows(index + 1)
            if 0 <= selected["index"] < len(rows):
                rows[selected["index"]].mark(False)
            rows[index].mark(True)
            selected.update(item=item, index=index)
            badge.pack(side="left")
            channel.pack(side="left", padx=S(10))
            channel.configure(text=f"{index + 1}  ·  {elide(item['title'], 11, S(300))}")
            now.configure(text=str(item["title"]))
            when.configure(text=str(item.get("group") or "Live TV"))
            meter.delete("all")
            upcoming.configure(text="")
            big.set_enabled(True)
            fav.set_enabled(True)
            fav.update_pill(icon="heart_fill" if item["id"] in self.favorites else "heart")
            if playing or self.play(item, shown):
                self.set_stage("slot", surface)
                idle_text.configure(text="Zender laden…")
            else:
                idle_text.configure(text="Deze zender kan niet worden geopend.")

            def watch(session):
                if not idle_text.winfo_exists():
                    return False
                if session and session["item"] is item and session.get("failed") and not session.get("reconnecting"):
                    idle_text.configure(text="Deze zender kan niet worden afgespeeld.")
                    self.stop_playback()
                return True
            self.listeners["slot"] = watch
            for child in programs.winfo_children():
                child.destroy()
            if not item.get("sid") or not self.source:
                label(programs, "Geen programmagegevens\nvoor deze bron.", 10, MUTED, PANEL, justify="left").pack(anchor="w")
                return
            label(programs, "Programma’s laden…", 10, MUTED, PANEL).pack(anchor="w")

            def show(rows_data):
                if rows[index].winfo_exists():
                    rows[index].set_now(rows_data)
                if selected["item"] is item and programs.winfo_exists():
                    fill_programs(rows_data)

            def failed(error):
                if selected["item"] is item and programs.winfo_exists():
                    for child in programs.winfo_children():
                        child.destroy()
                    label(programs, error_text(error), 10, MUTED, PANEL, wraplength=S(280), justify="left").pack(anchor="w")
            self.fetch_guide(item, show, failed)

        self.live_nav = lambda delta: choose(max(0, min(len(shown) - 1, selected["index"] + delta)) if selected["index"] >= 0 else 0)
        self.live_jump, self.live_items = choose, shown
        generation = self.generation
        if self.session and self.session["live"]:
            index = next((i for i, e in enumerate(shown) if e["id"] == self.session["item"].get("id")), None)
            if index is not None:
                self.root.after(60, lambda: generation == self.generation and choose(index))
            return
        last = self.preferences.get("last_channel")
        if not self.session and not self.autoplayed and self.preferences.get("autoplay_live", True) and last \
                and not SAFE_MODE:
            index = next((i for i, e in enumerate(shown) if e["id"] == last), None)
            if index is not None:
                self.root.after(300, lambda: generation == self.generation and choose(index))

    def channel_row(self, parent, index, item, command):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        bar = tk.Frame(row, bg=BG, width=S(3))
        bar.pack(side="left", fill="y")
        inner = tk.Frame(row, bg=BG, padx=S(12), pady=S(7))
        inner.pack(side="left", fill="x", expand=True)
        label(inner, str(index + 1), 10, DIM, BG, True, width=3, anchor="e").pack(side="left")
        logo = tk.Label(inner, bg=BG, bd=0, image=ui.placeholder_photo(S(40), S(40), RAISED, 10))
        logo.pack(side="left", padx=(S(12), S(14)))
        texts = tk.Frame(inner, bg=BG)
        texts.pack(side="left", fill="x", expand=True)
        label(texts, elide(item["title"], 11, S(420), True), 11, TEXT, BG, True).pack(anchor="w")
        group = str(item.get("group") or "Live TV")
        sub = label(texts, elide(group, 9, S(420)), 9, MUTED)
        sub.pack(anchor="w")
        if item["id"] in self.favorites:
            label(inner, "♥", 12, ACCENT_SOFT, BG).pack(side="right", padx=S(6))
        state = {"selected": False, "hover": False}

        def paint():
            ui.set_bg(inner, RAISED if state["selected"] else PANEL if state["hover"] else BG)
            bar.configure(bg=ACCENT if state["selected"] else row.cget("bg"))

        def hover(flag):
            state["hover"] = flag
            paint()

        def set_now(rows_data):
            current = current_program(rows_data)
            if current and current["title"] and sub.winfo_exists():
                sub.configure(text=elide(f"Nu: {current['title']}", 9, S(420)), fg=SOFT)
        row.mark = lambda flag: (state.update(selected=flag), paint())
        row.set_now = set_now
        cached = self.guide_cache.get(item.get("sid"))
        if cached:
            set_now(cached[1])
        ui.bind_hover(row, lambda: hover(True), lambda: hover(False))
        ui.bind_click(row, command)
        self.load_logo(logo, item, S(40))
        return row

    # ------------------------------------------------------------ tv guide

    def guide_view(self, pool, entries):
        archive = any(i.get("archive") for i in pool)
        self.page_header("TV-gids", "Wat er speelt, wat er komt en wat je kunt terugkijken." if archive
                         else "Wat er nu en straks op je zenders speelt.")
        if not pool or not self.source:
            box = tk.Frame(self.content, bg=BG)
            box.pack(fill="x", pady=S(50))
            Pill(box, "", None, kind="ghost", icon="guide", h=72).pack()
            label(box, "Nog geen programmagids", 17, TEXT, BG, True).pack(pady=(S(16), S(4)))
            label(box, "De gids werkt met een Xtream Codes-provider. M3U-lijsten bevatten meestal geen gids.",
                  10, MUTED).pack()
            Pill(box, "Provider koppelen", self.configure_source, kind="primary", icon="wifi", h=42).pack(pady=S(18))
            return
        self.category_chips(pool, pady=(0, 16))
        with_guide = [i for i in entries if i.get("sid")]
        shown = with_guide[:self.limit]
        moment = time()
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        start = int(midnight + self.guide_day * 86400)
        end = start + 86400
        pps = 4.6 * ui.SCALE / 60
        row_h, head_h, left_w = S(62), S(42), S(250)
        total_w = int((end - start) * pps)
        height = head_h + row_h * len(shown)

        tools = tk.Frame(self.content, bg=BG)
        tools.pack(fill="x", padx=S(44), pady=(0, S(12)))
        days = [(-2, "Eergisteren"), (-1, "Gisteren")] if archive else []
        days += [(0, "Vandaag"), (1, "Morgen")]
        for offset, text in days:
            Pill(tools, text, lambda o=offset: (setattr(self, "guide_day", o), self.render()),
                 kind="chip_on" if offset == self.guide_day else "chip", h=34, px=11.5,
                 icon="refresh" if offset < 0 else None).pack(side="left", padx=(0, S(8)))
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="x", padx=S(44), pady=(0, S(30)))
        left = tk.Frame(wrap, bg=BG, width=left_w)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        timeline = tk.Canvas(wrap, bg=BG, height=height, highlightthickness=0, xscrollincrement=S(30))
        timeline.hscroll = True
        timeline.pack(side="left", fill="x", expand=True)
        timeline.configure(scrollregion=(0, 0, total_w, height))
        now_x = (moment - start) * pps

        def scroll_to(x):
            timeline.xview_moveto(max(0, x) / total_w)
        Pill(tools, "", lambda: timeline.xview_scroll(10, "units"), kind="ghost", icon="next", h=34).pack(side="right")
        Pill(tools, "", lambda: timeline.xview_scroll(-10, "units"), kind="ghost", icon="back", h=34).pack(side="right", padx=S(8))
        if self.guide_day == 0:
            Pill(tools, "Nu", lambda: scroll_to(now_x - S(160)), kind="chip", icon="clock", h=34, px=11.5).pack(side="right")
        if archive:
            label(tools, "↺  = terugkijken", 9, DIM, BG).pack(side="right", padx=S(14))

        tk.Frame(left, bg=BG, height=head_h).pack(fill="x")
        for t in range(start, end + 1, 1800):
            x = (t - start) * pps
            timeline.create_line(x, head_h - S(10), x, height, fill="#1c1c24")
            if self.guide_day != 0 or abs(x + S(24) - now_x) > S(44):
                timeline.create_text(x + S(8), head_h / 2, text=hhmm(t), fill=MUTED, anchor="w", font=(FONT, 9, "bold"))
        for index in range(len(shown) + 1):
            y = head_h + index * row_h
            timeline.create_line(0, y, total_w, y, fill="#1c1c24")

        def open_program(channel, program):
            self.program_sheet(channel, program, shown)

        def draw_row(index, channel, rows_data):
            if not timeline.winfo_exists():
                return
            timeline.delete(f"row{index}")
            y0 = head_h + index * row_h + S(5)
            y1 = y0 + row_h - S(10)
            drawn = 0
            for position, program in enumerate(rows_data):
                if program["end"] <= start or program["start"] >= end:
                    continue
                x0 = max(0, (program["start"] - start) * pps) + S(2)
                x1 = min(total_w, (program["end"] - start) * pps) - S(2)
                if x1 - x0 < S(10):
                    continue
                current = program["start"] <= moment < program["end"]
                past = program["end"] <= moment
                replay = past and self.archivable(channel, program)
                tag = f"p{index}_{position}"
                fill = "#2b2342" if current else ("#1b1a26" if replay else PANEL)
                ui.round_rect(timeline, x0, y0, x1, y1, S(10), fill=fill,
                              outline=ACCENT if current else ("#3a3354" if replay else ""),
                              width=S(1.5) if current else (1 if replay else 0), tags=(f"row{index}", tag, tag + "box"))
                room = int(x1 - x0 - S(22))
                recorded = self.recording_for(channel, program) is not None
                if recorded:
                    timeline.create_oval(x1 - S(16), y0 + S(9), x1 - S(8), y0 + S(17), fill=LIVE_RED, outline="",
                                         tags=(f"row{index}", tag))
                    room -= S(14)
                if room > S(24):
                    timeline.create_text(x0 + S(11), y0 + S(9), text=elide(program["title"] or "Programma", 10, room, current),
                                         fill=(SOFT if replay else MUTED) if past else TEXT, anchor="nw",
                                         font=(FONT, 10, "bold" if current else "normal"), tags=(f"row{index}", tag))
                    when = f'{hhmm(program["start"])} – {hhmm(program["end"])}'
                    timeline.create_text(x0 + S(11), y1 - S(8), text=("↺  " + when) if replay else when,
                                         fill=ACCENT_SOFT if current or replay else DIM, anchor="sw", font=(FONT, 8),
                                         tags=(f"row{index}", tag))
                hover_fill = "#352c52" if current else ("#272338" if replay else RAISED)
                clickable = True
                timeline.tag_bind(tag, "<Enter>", lambda _, t=tag, h=hover_fill, c=clickable: (
                    timeline.itemconfigure(t + "box", fill=h), timeline.configure(cursor="hand2" if c else "")))
                timeline.tag_bind(tag, "<Leave>", lambda _, t=tag, f=fill: (
                    timeline.itemconfigure(t + "box", fill=f), timeline.configure(cursor="")))
                timeline.tag_bind(tag, "<ButtonRelease-1>", lambda _, c=channel, p=program: open_program(c, p))
                drawn += 1
            if not drawn:
                timeline.create_text(S(12), (y0 + y1) / 2, text="Geen programma’s op deze dag", fill=DIM, anchor="w",
                                     font=(FONT, 9), tags=f"row{index}")
            timeline.tag_raise("now")

        def no_guide(index):
            if timeline.winfo_exists():
                timeline.itemconfigure(f"row{index}", text="Geen gidsgegevens")

        for index, item in enumerate(shown):
            row = tk.Frame(left, bg=BG, height=row_h)
            row.pack(fill="x")
            row.pack_propagate(False)
            inner = tk.Frame(row, bg=BG)
            inner.place(x=0, rely=.5, anchor="w")
            label(inner, str(index + 1), 9, DIM, BG, True, width=3, anchor="e").pack(side="left")
            logo = tk.Label(inner, bg=BG, bd=0, image=ui.placeholder_photo(S(36), S(36), RAISED, 9))
            logo.pack(side="left", padx=(S(10), S(10)))
            names = tk.Frame(inner, bg=BG)
            names.pack(side="left")
            label(names, elide(item["title"], 10, left_w - S(100), True), 10, TEXT, BG, True).pack(anchor="w")
            if item.get("archive"):
                label(names, "↺ terugkijken", 8, ACCENT_SOFT, BG).pack(anchor="w")
            ui.bind_hover(row, lambda r=row: ui.set_bg(r, PANEL), lambda r=row: ui.set_bg(r, BG))
            ui.bind_click(row, lambda i=item: self.open_player(i, shown))
            self.load_logo(logo, item, S(36))
            y0 = head_h + index * row_h + S(5)
            timeline.create_text(S(12), y0 + row_h / 2 - S(5), text="Gids laden…", fill=DIM, anchor="w",
                                 font=(FONT, 9), tags=f"row{index}")
            self.fetch_guide(item, lambda rows_data, i=index, it=item: draw_row(i, it, rows_data),
                             lambda _, i=index: no_guide(i), full=bool(item.get("archive")) or self.guide_day != 0)
        if not shown:
            label(self.content, "Geen zenders met gidsgegevens in deze selectie.", 11, MUTED).pack(anchor="w", padx=S(44))
        if self.guide_day == 0:
            timeline.create_line(now_x, head_h - S(6), now_x, height, fill=LIVE_RED, width=S(2), tags="now")
            ui.round_rect(timeline, now_x - S(24), S(4), now_x + S(24), S(24), S(9), fill=LIVE_RED, outline="", tags="now")
            timeline.create_text(now_x, S(14), text=hhmm(moment) or "NU", fill="#ffffff", font=(FONT, 8, "bold"), tags="now")
            timeline.after(80, lambda: timeline.winfo_exists() and scroll_to(now_x - S(160)))
        elif self.guide_day < 0:
            timeline.after(80, lambda: timeline.winfo_exists() and scroll_to(18 * 3600 * pps))
        if len(with_guide) > len(shown):
            Pill(self.content, f"Meer zenders  ·  nog {number(len(with_guide) - len(shown))}", self.more,
                 kind="ghost").pack(anchor="w", padx=S(44), pady=(0, S(30)))

    # ------------------------------------------------------------ downloads + settings

    def downloaded_file(self, item_id):
        for entry in self.downloaded:
            if entry.get("id") == item_id and entry.get("file") and Path(entry["file"]).is_file():
                return entry["file"]
        return None

    def save_downloads(self):
        try:
            data.write_json(data.STATE.with_name("downloads.json"), data.seal(self.downloaded, self.source))
        except OSError as error:
            self.toast(elide(error_text(error), 10, S(480), True), "close")

    def purge_downloads(self):
        """Remove downloads that passed their keep-until date, and entries whose file is gone."""
        days = int(self.preferences.get("download_days", 30) or 0)
        now = time()
        kept, changed = [], False
        for entry in self.downloaded:
            path = Path(entry.get("file", ""))
            expired = days and entry.get("saved") and now - entry["saved"] > days * 86400
            if expired:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            if expired or not path.is_file():
                changed = True
                continue
            kept.append(entry)
        if changed:
            self.downloaded = kept
            self.save_downloads()

    def delete_download(self, entry):
        try:
            Path(entry["file"]).unlink(missing_ok=True)
        except OSError as error:
            self.toast(elide(error_text(error), 10, S(480), True), "close")
            return
        self.downloaded = [e for e in self.downloaded if e is not entry]
        self.save_downloads()
        self.toast("Download verwijderd", "trash")
        if self.tab == "downloads":
            self.render()

    def download(self, item, quiet=False):
        key = item["id"]
        if key in self.download_jobs:
            self.toast("Deze download is al bezig", "download")
            return
        if self.downloaded_file(key):
            if not quiet:
                self.toast("Staat al op je pc · te vinden bij Downloads", "check")
            return
        url = item.get("url", "")
        extension = Path(urlsplit(url).path).suffix.lower()
        if extension not in (".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v", ".ts"):
            self.toast("Deze titel kan niet gedownload worden", "close")
            return
        folder = Path(self.preferences.get("download_folder", data.STATE.parent / "Downloads"))
        title = f"{item['series']} - {item['title']}" if item.get("series") else str(item["title"])
        name = re.sub(r'[^\w -]', "_", title)[:90].strip() or "Zono"
        path = folder / f"{name}-{uuid4().hex[:6]}{extension}"
        job = {"item": item, "title": title, "path": path, "done": 0, "total": 0, "started": None,
               "cancel": threading.Event(), "speed": 0.0}
        self.download_jobs[key] = job
        if not quiet:
            self.toast("Toegevoegd aan Downloads", "download")

        def progress(done, total):
            if job["started"] is None:
                job["started"] = monotonic()
            job["done"], job["total"] = done, total
            elapsed = monotonic() - job["started"]
            job["speed"] = done / elapsed if elapsed > 0.5 else 0.0

        def finished(_):
            self.download_jobs.pop(key, None)
            size = path.stat().st_size if path.exists() else 0
            entry = dict(item, file=str(path), saved=time(), size=size, title=item["title"])
            self.downloaded = [e for e in self.downloaded if e.get("id") != key] + [entry]
            self.save_downloads()
            self.toast(f"Klaar: {elide(title, 10, S(300), True)}", "check")
            if self.tab == "downloads":
                self.render()

        def failed(error):
            self.download_jobs.pop(key, None)
            if isinstance(error, data.Cancelled):
                self.toast("Download geannuleerd", "close")
            else:
                self.toast(f"Download mislukt: {elide(error_text(error), 10, S(380), True)}", "close")
            if self.tab == "downloads":
                self.render()
        job["future"] = self.run(lambda: data.download(url, path, progress, job["cancel"]), finished, failed,
                                 executor=self.download_workers)

    def cancel_download(self, key):
        job = self.download_jobs.get(key)
        if not job:
            return
        job["cancel"].set()
        if job.get("future") and job["future"].cancel():
            self.download_jobs.pop(key, None)
            self.toast("Download geannuleerd", "close")
            if self.tab == "downloads":
                self.render()

    @staticmethod
    def size_text(size):
        if size >= 1024 ** 3:
            return f"{size / 1024 ** 3:.1f} GB".replace(".", ",")
        return f"{max(1, round(size / 1024 ** 2))} MB"

    def downloads_view(self):
        folder = self.preferences.get("download_folder", str(data.STATE.parent / "Downloads"))
        days = int(self.preferences.get("download_days", 30) or 0)
        total = sum(int(e.get("size") or 0) for e in self.downloaded)
        summary = f"{len(self.downloaded)} titels op deze pc  ·  {self.size_text(total)}" if self.downloaded else \
            "Download films en afleveringen om ze zonder internet te bekijken, bijvoorbeeld op het vliegtuig."
        self.page_header("Downloads", summary)
        area = tk.Frame(self.content, bg=BG)
        area.pack(fill="x", padx=S(44))
        tools = tk.Frame(area, bg=BG)
        tools.pack(fill="x", pady=(0, S(6)))
        Pill(tools, "Map wijzigen", self.change_folder, kind="ghost", icon="folder").pack(side="left")
        label(tools, elide(folder, 9, S(520)), 9, DIM, BG).pack(side="left", padx=S(12))
        keep = tk.Frame(area, bg=BG)
        keep.pack(fill="x", pady=(S(4), S(18)))
        label(keep, "Automatisch verwijderen na", 10, SOFT, BG).pack(side="left", padx=(0, S(12)))
        for value, text in ((7, "7 dagen"), (14, "14 dagen"), (30, "30 dagen"), (0, "Nooit")):
            Pill(keep, text, lambda v=value: (self.set_pref("download_days", v), self.render()),
                 kind="chip_on" if value == days else "chip", h=32, px=11).pack(side="left", padx=(0, S(8)))

        active = [r for r in self.recordings if r.get("status") in ("planned", "recording")]
        if active:
            label(area, "Opnames", 14, TEXT, BG, True).pack(anchor="w", pady=(S(8), S(8)))
            for entry in sorted(active, key=lambda r: r["start"]):
                row = tk.Frame(area, bg=PANEL, padx=S(16), pady=S(12))
                row.pack(fill="x", pady=(0, S(6)))
                recording = entry["status"] == "recording"
                Pill(row, "REC" if recording else "", None, kind="live" if recording else "ghost",
                     icon=None if recording else "record", h=26 if recording else 34, px=9.5, radius=6 if recording else None,
                     weight="bold").pack(side="left")
                texts = tk.Frame(row, bg=PANEL)
                texts.pack(side="left", padx=S(14))
                label(texts, elide(entry["title"], 11, S(520), True), 11, TEXT, PANEL, True).pack(anchor="w")
                day = datetime.fromtimestamp(entry["start"])
                when = "vandaag" if day.date() == datetime.now().date() else day.strftime("%d/%m")
                state_text = "Wordt nu opgenomen" if recording else f"Gepland {when}"
                label(texts, f"{entry['channel']}  ·  {hhmm(entry['start'])} – {hhmm(entry['end'])}  ·  {state_text}",
                      9, MUTED, PANEL).pack(anchor="w")
                Pill(row, "Stoppen" if recording else "Annuleren", lambda e=entry: self.cancel_recording(e),
                     kind="ghost", icon="close", h=34, padx=12).pack(side="right")
        if self.download_jobs:
            label(area, "Bezig", 14, TEXT, BG, True).pack(anchor="w", pady=(S(8), S(8)))
            bars = []
            for key, job in list(self.download_jobs.items()):
                row = tk.Frame(area, bg=PANEL, padx=S(16), pady=S(12))
                row.pack(fill="x", pady=(0, S(6)))
                top = tk.Frame(row, bg=PANEL)
                top.pack(fill="x")
                label(top, elide(job["title"], 11, S(560), True), 11, TEXT, PANEL, True).pack(side="left")
                Pill(top, "", lambda k=key: self.cancel_download(k), kind="ghost", icon="close", h=32).pack(side="right")
                meter = tk.Canvas(row, bg=PANEL, height=S(8), highlightthickness=0)
                meter.pack(fill="x", pady=(S(8), S(4)))
                info = label(row, "Wachten…", 9, MUTED, PANEL)
                info.pack(anchor="w")
                bars.append((job, meter, info))

            def refresh():
                if not bars or not bars[0][1].winfo_exists():
                    return
                for job, meter, info in bars:
                    width = max(1, meter.winfo_width())
                    meter.delete("all")
                    meter.create_line(S(4), S(4), width - S(4), S(4), width=S(6), fill=RAISED, capstyle="round")
                    if job["total"]:
                        ratio = job["done"] / job["total"]
                        meter.create_line(S(4), S(4), S(4) + (width - S(8)) * ratio, S(4), width=S(6), fill=ACCENT_SOFT,
                                          capstyle="round")
                        left = (job["total"] - job["done"]) / job["speed"] if job["speed"] else 0
                        text = f"{round(ratio * 100)}%  ·  {self.size_text(job['done'])} van {self.size_text(job['total'])}"
                        if job["speed"]:
                            text += f"  ·  {job['speed'] / 1024 ** 2:.1f} MB/s".replace(".", ",")
                            text += f"  ·  nog {max(1, round(left / 60))} min"
                        info.configure(text=text)
                    elif job["done"]:
                        info.configure(text=f"{self.size_text(job['done'])} binnen")
                if self.download_jobs:
                    bars[0][1].after(500, refresh)
                else:
                    self.render()
            refresh()

        if not self.downloaded and not self.download_jobs and not active:
            box = tk.Frame(area, bg=BG)
            box.pack(fill="x", pady=S(50))
            Pill(box, "", None, kind="ghost", icon="download", h=72).pack()
            label(box, "Nog geen downloads", 17, TEXT, BG, True).pack(pady=(S(16), S(4)))
            label(box, "Open een film en kies Download, of kies bij een serie ‘Seizoen downloaden’.", 10, MUTED).pack()
            return
        if self.downloaded:
            label(area, "Op deze pc", 14, TEXT, BG, True).pack(anchor="w", pady=(S(14), S(8)))
        for entry in sorted(self.downloaded, key=lambda e: -(e.get("saved") or 0)):
            row = tk.Frame(area, bg=BG, padx=S(12), pady=S(8))
            row.pack(fill="x", pady=1)
            thumb = tk.Label(row, bg=BG, bd=0, image=ui.placeholder_photo(S(40), S(58), RAISED, 6))
            thumb.pack(side="left")
            self.load_thumb(thumb, entry, (S(40), S(58)))
            texts = tk.Frame(row, bg=BG)
            texts.pack(side="left", fill="x", expand=True, padx=S(14))
            title = f"{entry['series']} · {entry['title']}" if entry.get("series") else entry["title"]
            label(texts, elide(title, 11, S(560), True), 11, TEXT, BG, True).pack(anchor="w")
            details = [self.size_text(int(entry.get("size") or 0))] if entry.get("size") else []
            if days and entry.get("saved"):
                left = max(0, days - int((time() - entry["saved"]) / 86400))
                details.append(f"nog {left} dag{'en' if left != 1 else ''} beschikbaar")
            details.append("speelt offline")
            label(texts, "  ·  ".join(details), 9, MUTED, BG).pack(anchor="w")
            Pill(row, "", lambda e=entry: self.delete_download(e), kind="ghost", icon="trash", h=36).pack(side="right")
            Pill(row, "", lambda e=entry: self.open_player(e), kind="primary", icon="play", h=36).pack(side="right", padx=S(8))
            ui.bind_hover(row, lambda r=row: ui.set_bg(r, PANEL), lambda r=row: ui.set_bg(r, BG))
            ui.bind_click(row, lambda e=entry: self.open_player(e))

    def change_folder(self):
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            self.update_preferences(dict(self.preferences, download_folder=folder))
            self.render()

    def update_preferences(self, preferences):
        try:
            data.write_json(data.STATE.with_name("preferences.json"), preferences)
        except OSError as error:
            messagebox.showerror("Zono", error_text(error), parent=self.root)
            return False
        self.preferences = preferences
        return True

    def remember_preference(self, key, value):
        if self.preferences.get(key) == value:
            return
        self.preferences = dict(self.preferences, **{key: value})
        try:
            data.write_json(data.STATE.with_name("preferences.json"), self.preferences)
        except OSError:
            pass

    def panel(self, parent, title, subtitle=None):
        box = tk.Frame(parent, bg=PANEL, padx=S(26), pady=S(22))
        box.pack(fill="x", pady=(0, S(16)))
        label(box, title, 14, TEXT, PANEL, True).pack(anchor="w")
        if subtitle:
            label(box, subtitle, 10, MUTED, PANEL).pack(anchor="w", pady=(2, 0))
        return box

    def set_pref(self, key, value, note="Opgeslagen"):
        self.remember_preference(key, value)
        if note:
            self.toast(note)

    def choice_row(self, parent, title, options, current, key, bg=PANEL, note="Opgeslagen", after=None):
        label(parent, title, 10, SOFT, bg).pack(anchor="w", pady=(S(18), S(8)))
        row = tk.Frame(parent, bg=bg)
        row.pack(anchor="w")
        pills = {}

        def pick(value):
            for option, pill in pills.items():
                pill.update_pill(kind="chip_on" if option == value else "chip")
            self.set_pref(key, value, note)
            if after:
                after(value)
        for value, text in options:
            pills[value] = Pill(row, text, lambda v=value: pick(v), kind="chip_on" if value == current else "chip",
                                h=34, px=11.5)
            pills[value].pack(side="left", padx=(0, S(8)))

    def switch_row(self, parent, title, text, key, default=True, bg=PANEL, after=None):
        row = tk.Frame(parent, bg=bg)
        row.pack(anchor="w", fill="x", pady=(S(18), 0))

        def changed(value):
            self.set_pref(key, value)
            if after:
                after(value)
        Switch(row, self.preferences.get(key, default), changed).pack(side="left", anchor="n")
        texts = tk.Frame(row, bg=bg)
        texts.pack(side="left", padx=S(14))
        label(texts, title, 10, TEXT, bg, True).pack(anchor="w")
        label(texts, text, 9, MUTED, bg, wraplength=S(620), justify="left").pack(anchor="w")

    def settings_view(self):
        kids = bool(self.profile and self.profile.get("kids"))
        self.page_header("Instellingen", "Wijzigingen worden meteen bewaard.")
        area = tk.Frame(self.content, bg=BG)
        area.pack(fill="x", padx=S(44))

        profile = self.panel(area, "Profiel")
        row = tk.Frame(profile, bg=PANEL)
        row.pack(anchor="w", fill="x", pady=(S(14), 0))
        if self.profile:
            tk.Label(row, image=ui.avatar_photo(self.profile.get("color", 0), S(56), kids), bg=PANEL).pack(side="left")
            texts = tk.Frame(row, bg=PANEL)
            texts.pack(side="left", padx=S(16))
            label(texts, self.profile.get("name", ""), 13, TEXT, PANEL, True).pack(anchor="w")
            label(texts, ("Kinderprofiel" if kids else "Profiel") + ("  ·  beveiligd met pincode" if self.profile.get("pin") else ""),
                  9, MUTED, PANEL).pack(anchor="w")
        buttons = tk.Frame(row, bg=PANEL)
        buttons.pack(side="right")
        Pill(buttons, "Profiel wisselen", lambda: self.show_profiles(), kind="ghost", icon="swap", h=40, padx=16).pack(side="left")
        if not kids:
            Pill(buttons, "Profielen beheren", lambda: self.show_profiles(True), kind="ghost", icon="pencil",
                 h=40, padx=16).pack(side="left", padx=(S(10), 0))

        general = self.panel(area, "Algemeen")
        views = ("home", "live", "guide", "movie", "series")
        startup = self.preferences.get("startup", "home")
        self.choice_row(general, "Startscherm", [(v, TABS[v]) for v in views], startup if startup in views else "home", "startup")
        self.choice_row(general, "Uitgelichte titels op Ontdekken wisselen", [(0, "Uit"), (5, "5 sec"), (7, "7 sec"), (10, "10 sec")],
                        self.preferences.get("slide_seconds", 7), "slide_seconds")

        playback = self.panel(area, "Afspelen")
        label(playback, "Standaardvolume", 10, SOFT, PANEL).pack(anchor="w", pady=(S(18), S(6)))
        volume_row = tk.Frame(playback, bg=PANEL)
        volume_row.pack(anchor="w")
        tk.Label(volume_row, image=ui.pill_photo(icon="volume", kind="quiet", h=28, hover=False, disabled=False),
                 bg=PANEL).pack(side="left")
        value = label(volume_row, f"{self.volume}%", 10, MUTED, PANEL, width=5)

        def volume_done(level):
            self.set_volume(level)
            self.set_pref("volume", int(level))
        Slider(volume_row, 280, self.preferences.get("volume", 75), 100,
               command=lambda v: value.configure(text=f"{int(v)}%"), release=volume_done).pack(side="left", padx=S(8))
        value.pack(side="left")
        self.choice_row(playback, "Buffer (hoeveel video vooraf geladen wordt)",
                        [(1000, "Snel  ·  1 sec"), (3000, "Normaal  ·  3 sec"), (8000, "Stabiel  ·  8 sec")],
                        int(self.preferences.get("buffer_ms", 3000)), "buffer_ms",
                        note="Opgeslagen · geldt vanaf de volgende stream")
        label(playback, "Hapert je stream? Kies Stabiel. Zappen gaat dan iets trager.", 9, MUTED, PANEL).pack(anchor="w", pady=(S(6), 0))
        self.switch_row(playback, "Hardwareversnelling", "Gebruikt je grafische kaart voor vloeiender beeld. Zet uit als je beeldfouten ziet.",
                        "hw_decode")
        self.switch_row(playback, "Automatisch opnieuw verbinden", "Probeert tot 3 keer opnieuw als een stream wegvalt.", "reconnect")
        self.switch_row(playback, "Volgende aflevering automatisch afspelen",
                        "Tijdens de aftiteling telt Zono af en start daarna de volgende aflevering, zoals bij Netflix.",
                        "autonext")
        self.switch_row(playback, "Knop ‘Intro overslaan’", "In de eerste minuten van een aflevering: één klik spoelt de "
                        "intro door (ongeveer anderhalve minuut).", "intro_button")
        if SAFE_MODE:
            notice = tk.Frame(playback, bg="#2a1f12", padx=S(14), pady=S(10))
            notice.pack(anchor="w", fill="x", pady=(S(18), 0))
            label(notice, "Veilige start: Zono werd vorige keer niet goed afgesloten, daarom staat live pauzeren even uit.",
                  10, "#ffd9a8", "#2a1f12").pack(side="left")
            Pill(notice, "Weer aanzetten", self.leave_safe_mode, kind="primary", h=34, padx=12).pack(side="right")
        self.choice_row(playback, "Live tv pauzeren en terugspoelen · experimenteel (Zono bewaart de laatste minuten op je pc)",
                        [(0, "Uit"), (15, "15 min"), (30, "30 min"), (60, "60 min")], self.buffer_minutes(),
                        "live_buffer_min_v2", note="Geldt vanaf de volgende zender die je opent")
        label(playback, "Gebruikt tijdelijk schijfruimte: ongeveer 1 tot 4 GB per uur, afhankelijk van de zender. "
                        "Wordt automatisch gewist.", 9, MUTED, PANEL).pack(anchor="w", pady=(S(6), 0))
        self.switch_row(playback, "Laatste zender automatisch afspelen", "Live TV start bij het openen met de zender die je het laatst keek.",
                        "autoplay_live")
        self.switch_row(playback, "Beeld-in-beeld als je Zono minimaliseert",
                        "Het beeld speelt verder in een klein venster dat bovenop je andere programma's blijft.", "auto_pip")

        personal = self.panel(area, "Ontdekken en landen")
        label(personal, "Kies zelf wat Ontdekken toont en in welke volgorde, en welke landen eerst komen.", 10, MUTED,
              PANEL).pack(anchor="w", pady=(S(4), S(12)))
        chosen = self.preferred_countries()
        tools = tk.Frame(personal, bg=PANEL)
        tools.pack(anchor="w")
        Pill(tools, "Ontdekken aanpassen", self.edit_home, kind="ghost", icon="pencil", h=40, padx=16).pack(side="left")
        Pill(tools, "Zenders beheren", self.manage_channels, kind="ghost", icon="eye", h=40, padx=16).pack(side="left", padx=(S(10), 0))
        Pill(tools, "Landen en talen" + (f"  ·  {', '.join(countries.name(c).split(' /')[0] for c in chosen[:3])}" if chosen else ""),
             self.edit_countries, kind="ghost", icon="live", h=40, padx=16).pack(side="left", padx=S(10))

        guide = self.panel(area, "TV-gids")
        self.choice_row(guide, "Tijdcorrectie (als de gids niet gelijk loopt met de zender)",
                        [(-2, "−2 uur"), (-1, "−1 uur"), (0, "Geen"), (1, "+1 uur"), (2, "+2 uur")],
                        self.preferences.get("epg_offset", 0), "epg_offset", after=lambda _: self.guide_cache.clear())

        if not kids:
            content = self.panel(area, "Inhoud", "Verberg categorieën en titels die een van deze woorden bevatten (gescheiden door komma's).")
            words = tk.StringVar(value=self.preferences.get("hidden_words", ""))
            entry = self.field(content, "Verborgen woorden", words)

            def store_words(_=None):
                if words.get().strip() != self.preferences.get("hidden_words", ""):
                    self.set_pref("hidden_words", words.get().strip(), "Opgeslagen · filter toegepast")
                    self.set_library(self.state.get("library", []))
            entry.bind("<Return>", store_words)
            entry.bind("<FocusOut>", store_words, add="+")
            label(content, "Bijvoorbeeld: adult, xxx, sport", 9, DIM, PANEL).pack(anchor="w", pady=(S(6), 0))

            if self.source:
                summary = f"Xtream Codes  ·  {urlsplit(self.source.get('server', '')).hostname or self.source.get('server', '')}"
                if self.state.get("protected") or data.needs_protection(self.state):
                    summary += "  ·  wachtwoord versleuteld opgeslagen"
            elif self.library:
                summary = f"M3U-afspeellijst  ·  {number(len(self.library))} titels"
            else:
                summary = "Nog geen provider gekoppeld."
            provider = self.panel(area, "Provider", summary)
            buttons = tk.Frame(provider, bg=PANEL)
            buttons.pack(anchor="w", pady=(S(16), 0))
            Pill(buttons, "Provider koppelen", self.configure_source, kind="ghost", icon="wifi", h=40).pack(side="left")
            if self.source:
                Pill(buttons, "Bibliotheek vernieuwen", lambda: self.refresh_library(False), kind="ghost", icon="refresh",
                     h=40).pack(side="left", padx=S(10))

        if not kids:
            extra = self.panel(area, "Castfoto's en trailers (optioneel)",
                               "Met een gratis sleutel van themoviedb.org toont Zono foto's van acteurs, trailers en betere aanraders.")
            key_var = tk.StringVar(value=self.preferences.get("tmdb_key", ""))
            self.field(extra, "TMDB API-sleutel (v3)", key_var, True)
            buttons = tk.Frame(extra, bg=PANEL)
            buttons.pack(anchor="w", pady=(S(12), 0))
            result = label(buttons, "", 9, MUTED, PANEL)

            def save_key():
                key = key_var.get().strip()
                if not key:
                    self.set_pref("tmdb_key", "", "Sleutel verwijderd")
                    return
                result.configure(text="Controleren…", fg=MUTED)

                def ok(_):
                    self.tmdb_cache.clear()
                    self.set_pref("tmdb_key", key, "Sleutel bewaard · castfoto's staan aan")
                    if result.winfo_exists():
                        result.configure(text="✓ Sleutel werkt", fg=ACCENT_SOFT)

                def bad(_):
                    if result.winfo_exists():
                        result.configure(text="Deze sleutel werkt niet. Kopieer de ‘API Key (v3)’.", fg="#fda4af")
                self.run(lambda: tmdb.check_key(key), ok, bad)
            Pill(buttons, "Opslaan", save_key, kind="ghost", icon="check", h=38, padx=16).pack(side="left")
            Pill(buttons, "Gratis sleutel aanvragen", lambda: webbrowser.open("https://www.themoviedb.org/settings/api"),
                 kind="quiet", icon="next", h=38, padx=14).pack(side="left", padx=S(10))
            result.pack(side="left", padx=S(8))

        storage = self.panel(area, "Opslag en hulp")
        buttons = tk.Frame(storage, bg=PANEL)
        buttons.pack(anchor="w", pady=(S(16), 0))

        def clear_cache():
            self.art_cache.clear()
            self.logo_cache.clear()
            self.hero_art.clear()
            self.guide_cache.clear()
            ui.poster_art.cache_clear()
            self.toast("Cache gewist")
        Pill(buttons, "Cache wissen", clear_cache, kind="ghost", icon="trash", h=40).pack(side="left")

        Pill(buttons, "Logboek openen", self.show_log, kind="ghost", icon="info", h=40).pack(side="left", padx=S(10))
        label(storage, "Gaat er iets mis? In het logboek staat wat er gebeurde. Stuur het mee als je hulp vraagt.",
              9, MUTED, PANEL).pack(anchor="w", pady=(S(8), 0))

        keys = self.panel(area, "Sneltoetsen")
        table = tk.Frame(keys, bg=PANEL)
        table.pack(anchor="w", pady=(S(12), 0))
        shortcuts = (("Ctrl + F  of  /", "Zoeken"), ("↑  ↓", "Zappen in Live TV en in de speler"),
                     ("Spatie", "Pauze / verder"), ("←  →", "10 seconden terug / vooruit"),
                     ("F  of dubbelklik", "Volledig scherm"), ("M", "Geluid aan / uit"),
                     ("S", "Ondertitels en audio"), ("G", "TV-gids in de speler"), ("T", "Terugkijken in de speler"),
                     ("C", "Casten naar je tv"), ("P", "Beeld-in-beeld"), ("0 – 9", "Zender kiezen met zijn nummer"),
                     ("N", "Volgende aflevering"), ("Esc", "Terug / volledig scherm verlaten"))
        for index, (key, meaning) in enumerate(shortcuts):
            label(table, key, 10, TEXT, PANEL, True, anchor="w").grid(row=index, column=0, sticky="w", pady=S(3))
            label(table, meaning, 10, MUTED, PANEL, anchor="w").grid(row=index, column=1, sticky="w", padx=(S(30), 0))
        label(area, f"Zono Desktop {VERSION}  ·  Ingebouwde VideoLAN-videomotor", 9, DIM).pack(anchor="w", pady=(S(8), S(30)))

    # ------------------------------------------------------------ dialogs

    def fit(self, window, w, h):
        W = min(S(w), int(window.winfo_screenwidth() * .92))
        H = min(S(h), int(window.winfo_screenheight() * .88))
        window.geometry(f"{W}x{H}")

    def dialog(self, title, bg=SIDE):
        window = tk.Toplevel(self.root, bg=bg)
        window.title(title)
        window.transient(self.root)
        window.grab_set()
        return window

    def field(self, parent, name, variable, masked=False):
        bg = parent.cget("bg")
        label(parent, name, 10, SOFT, bg).pack(anchor="w", pady=(S(10), S(4)))
        border = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        border.pack(fill="x")
        entry = tk.Entry(border, textvariable=variable, show="•" if masked else "", bg=PANEL, fg=TEXT,
                         insertbackground=TEXT, relief="flat", bd=0, highlightthickness=0, font=(FONT, 11))
        entry.pack(fill="x", padx=S(12), ipady=S(8))
        entry.bind("<FocusIn>", lambda _: border.configure(highlightbackground=ACCENT))
        entry.bind("<FocusOut>", lambda _: border.configure(highlightbackground=LINE))
        return entry

    def configure_source(self):
        if self.profile and self.profile.get("kids"):
            self.toast("Niet beschikbaar in een kinderprofiel", "lock")
            return
        window = self.sheet(560, 640)
        frame = tk.Frame(window, bg=SIDE, padx=S(34), pady=S(30))
        frame.pack(fill="both", expand=True)
        label(frame, "Provider koppelen", 20, TEXT, SIDE, True).pack(anchor="w")
        label(frame, "Koppel je IPTV-abonnement via Xtream Codes of een M3U-afspeellijst. "
                     "Je wachtwoord wordt versleuteld bewaard op deze computer.", 10, MUTED, SIDE,
              wraplength=S(480), justify="left").pack(anchor="w", pady=(S(4), S(18)))
        mode = {"value": 0 if self.source or not self.library else 1}
        segment = tk.Frame(frame, bg=SIDE)
        segment.pack(anchor="w", pady=(0, S(6)))
        tabs = {}
        fields = tk.Frame(frame, bg=SIDE)
        fields.pack(fill="x")
        values = [tk.StringVar(value=(self.source or {}).get(key, "")) for key in ("server", "user", "password")]
        link, path = tk.StringVar(), tk.StringVar()

        def switch(value=None):
            if value is not None:
                mode["value"] = value
            for key, pill in tabs.items():
                pill.update_pill(kind="chip_on" if key == mode["value"] else "chip")
            for child in fields.winfo_children():
                child.destroy()
            if mode["value"] == 0:
                for index, name in enumerate(("Serveradres", "Gebruikersnaam", "Wachtwoord")):
                    self.field(fields, name, values[index], index == 2)
            else:
                self.field(fields, "M3U-link", link)
                self.field(fields, "Of een lokaal bestand", path)

                def browse():
                    chosen = filedialog.askopenfilename(parent=self.root, filetypes=[("M3U", "*.m3u *.m3u8"), ("Alle bestanden", "*.*")])
                    if chosen:
                        path.set(chosen)
                Pill(fields, "Bestand kiezen", browse, kind="ghost", icon="folder", h=36).pack(anchor="w", pady=(S(10), 0))
        for value, text in ((0, "Xtream Codes"), (1, "M3U")):
            tabs[value] = Pill(segment, text, lambda v=value: switch(v), kind="chip", h=34, px=11.5)
            tabs[value].pack(side="left", padx=(0, S(8)))
        switch()
        status = label(frame, "", 10, ACCENT_SOFT, SIDE, wraplength=S(480), justify="left")
        status.pack(anchor="w", pady=(S(16), S(10)))
        actions = tk.Frame(frame, bg=SIDE)
        actions.pack(anchor="w")

        def fail(error):
            if window.winfo_exists():
                status.configure(text=error_text(error))
                start.set_enabled(True)
                clear.set_enabled(True)

        def commit(entries, source, preserve=False):
            if not window.winfo_exists():
                return
            new_state = {"revision": uuid4().hex, "library": entries, "source": source}
            if preserve:
                new_state.update(favorites=self.favorites, progress=self.progress)

            def done(_):
                self.state, self.source = new_state, source
                self.set_library(entries)
                self.favorites = new_state.get("favorites", {})
                self.progress = new_state.get("progress", {})
                self.hero_art.clear()
                self.guide_cache.clear()
                self.stop_playback()
                window.close()
                self.select("home")
                self.toast(f"Bibliotheek geladen  ·  {number(len(entries))} titels" if entries else "Provider gewist")
            window.closable = False

            def save_failed(error):
                window.closable = True
                fail(error)
            self.run(lambda: data.save_state(new_state), done, save_failed)

        def submit():
            source = dict(zip(("server", "user", "password"), (v.get().strip() for v in values))) if mode["value"] == 0 else None
            local, remote = path.get().strip(), link.get().strip()
            start.set_enabled(False)
            clear.set_enabled(False)
            status.configure(text="Bibliotheek laden… dit kan bij grote providers even duren.")

            def load():
                if source is not None:
                    if not all(source.values()):
                        raise ValueError("Vul alle Xtream-velden in.")
                    return data.catalog(source)
                if local:
                    with Path(local).open("rb") as handle:
                        raw = handle.read(data.SOURCE_LIMIT + 1)
                    if len(raw) > data.SOURCE_LIMIT:
                        raise ValueError("Dit M3U-bestand is groter dan 256 MiB.")
                    return data.parse_m3u(raw.decode("utf-8-sig", errors="replace"))
                if not remote:
                    raise ValueError("Vul een M3U-link in of kies een bestand.")
                return data.parse_m3u(data.fetch(remote))

            def loaded(entries):
                if not entries:
                    fail(ValueError("De bron bevat geen herkenbare titels."))
                else:
                    commit(entries, source, bool(source and source == self.source))
            self.run(load, loaded, fail)

        def erase():
            if messagebox.askyesno("Bron wissen", "Bron, favorieten en kijkvoortgang wissen?", parent=self.root):
                start.set_enabled(False)
                clear.set_enabled(False)
                commit([], None)
        start = Pill(actions, "Bibliotheek laden", submit, kind="primary", h=42, padx=22)
        clear = Pill(actions, "Bron wissen", erase, kind="danger", h=42, padx=20)
        start.pack(side="left", padx=(0, S(10)))
        clear.pack(side="left")

    def save_activity(self):
        data.save_activity(self.state, self.favorites, self.progress)

    def toggle(self, item, parent=None):
        key = item["id"]
        previous = self.favorites.get(key)
        if previous:
            del self.favorites[key]
        else:
            self.favorites[key] = item
        try:
            self.save_activity()
        except OSError as error:
            if previous:
                self.favorites[key] = previous
            else:
                del self.favorites[key]
            messagebox.showerror("Zono", error_text(error), parent=parent or self.root)
            return key in self.favorites
        if parent is None:
            self.toast("Bewaard in je favorieten" if key in self.favorites else "Verwijderd uit je favorieten",
                       "heart_fill" if key in self.favorites else "heart")
        return key in self.favorites

    def open_item(self, item):
        if item["kind"] == "series":
            self.show_detail(item)
        else:
            self.open_player(item)

    def styled_list(self, parent, bg=PANEL):
        holder = tk.Frame(parent, bg=bg)
        scroll = ttk.Scrollbar(holder, style="Zono.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y")
        listing = tk.Listbox(holder, bg=bg, fg=TEXT, selectbackground=ACCENT, selectforeground="#ffffff",
                             font=(FONT, 11), relief="flat", bd=0, highlightthickness=0, activestyle="none",
                             yscrollcommand=scroll.set)
        listing.pack(side="left", fill="both", expand=True, padx=S(10), pady=S(8))
        scroll.configure(command=listing.yview)
        return holder, listing

    # ------------------------------------------------------------ phone / AirPlay sharing

    def share_qr(self, parent, bg=SIDE, size=200):
        url = self.remote.url()
        picture = qr.image(url, scale=max(3, round(S(size) / 40)), border=3)
        picture = picture.resize((S(size), S(size)), Image.Resampling.NEAREST)
        holder = tk.Frame(parent, bg=bg)
        art = tk.Label(holder, bg=bg, bd=0)
        art.photo = ImageTk.PhotoImage(ui.round_corners(picture, S(12)))
        art.configure(image=art.photo)
        art.pack(anchor="w")
        label(holder, url, 9, MUTED, bg).pack(anchor="w", pady=(S(8), 0))
        return holder

    def set_sharing(self, enabled):
        self.remember_preference("share_enabled", bool(enabled))
        if enabled and not self.remote.running:
            try:
                self.remote.start()
            except OSError as error:
                self.toast(elide(error_text(error), 10, S(480), True), "close")
                return False
        elif not enabled and self.remote.running:
            self.remote.stop()
        return True

    def open_share(self):
        window = self.sheet(620, 640)
        frame = tk.Frame(window, bg=SIDE, padx=S(34), pady=S(30))
        frame.pack(fill="both", expand=True)
        label(frame, "Kijken op je telefoon", 20, TEXT, SIDE, True).pack(anchor="w")
        label(frame, "Kijk je zenders, films en series op je iPhone, iPad, tv-box of in de browser van je smart-tv. "
                     "Met AirPlay stuur je het beeld vanaf je iPhone naar je Apple TV.", 10, MUTED, SIDE,
              wraplength=S(540), justify="left").pack(anchor="w", pady=(S(4), S(16)))
        row = tk.Frame(frame, bg=SIDE)
        row.pack(anchor="w", fill="x")
        body = tk.Frame(frame, bg=SIDE)
        body.pack(fill="x", pady=(S(18), 0))

        def show():
            for child in body.winfo_children():
                child.destroy()
            if not self.remote.running:
                label(body, "Zet delen aan om een QR-code te krijgen.", 10, DIM, SIDE).pack(anchor="w")
                return
            columns = tk.Frame(body, bg=SIDE)
            columns.pack(anchor="w")
            self.share_qr(columns).pack(side="left", anchor="n")
            steps = tk.Frame(columns, bg=SIDE)
            steps.pack(side="left", anchor="n", padx=(S(26), 0))
            for number_, text in enumerate((
                    "Verbind je telefoon met hetzelfde wifi als deze pc.",
                    "Open de camera en scan de QR-code.",
                    "Tik op een zender, film of aflevering.",
                    "Apple TV: tik in de speler op het AirPlay-icoon en kies je Apple TV."), 1):
                line = tk.Frame(steps, bg=SIDE)
                line.pack(anchor="w", pady=(0, S(10)))
                Pill(line, str(number_), None, kind="accent", h=24, px=10, weight="bold").pack(side="left", anchor="n")
                label(line, text, 10, SOFT, SIDE, wraplength=S(250), justify="left").pack(side="left", padx=(S(10), 0))
            label(body, "Vraagt Windows om toegang voor Zono in je netwerk? Kies dan ‘Toegang toestaan’ voor privénetwerken.",
                  9, DIM, SIDE, wraplength=S(540), justify="left").pack(anchor="w", pady=(S(14), 0))

        def changed(value):
            if self.set_sharing(value):
                show()
        Switch(row, self.remote.running, changed).pack(side="left")
        texts = tk.Frame(row, bg=SIDE)
        texts.pack(side="left", padx=S(14))
        label(texts, "Delen in mijn wifi", 11, TEXT, SIDE, True).pack(anchor="w")
        label(texts, "Alleen toestellen met de QR-code kunnen meekijken. Zono moet hiervoor open staan.",
              9, MUTED, SIDE).pack(anchor="w")
        show()

    # ------------------------------------------------------------ search (top right)

    def build_search(self):
        holder = tk.Frame(self.main, bg=BG)
        holder.place(relx=1, x=-S(34), y=S(22), anchor="ne")
        self.search_holder = holder
        self.search_button = tk.Label(holder, bg=BG, bd=0, cursor="hand2")
        self.search_button.pack()
        self.search_button.hover = False
        self.search_button.bind("<Button-1>", lambda _: self.open_search())
        self.search_button.bind("<Enter>", lambda _: self.hover_search(True))
        self.search_button.bind("<Leave>", lambda _: self.hover_search(False))
        self.search_look_job = None
        self.search_field = tk.Label(holder, bg=BG, bd=0)
        self.search_var = tk.StringVar()
        self.search = tk.Entry(self.search_field, textvariable=self.search_var, bg=PANEL, fg=TEXT,
                               insertbackground=TEXT, relief="flat", bd=0, highlightthickness=0, font=(FONT, 11))
        self.search_hint = label(self.search_field, "Films, series of zenders", 11, DIM, PANEL, cursor="xterm")
        self.search_hint.bind("<Button-1>", lambda _: self.search.focus_set())
        self.search_x = Pill(self.search_field, "", self.close_search, kind="quiet", icon="close", h=30, bg=PANEL)
        self.search_field.configure(cursor="xterm")
        self.search_field.bind("<Button-1>", lambda _: self.search.focus_set())
        self.results_panel = tk.Label(self.main, bg=BG, bd=0)
        self.results_inner = tk.Frame(self.results_panel, bg=SIDE)
        self.results_inner.pack(padx=S(2), pady=S(10))
        self.search_var.trace_add("write", lambda *_: self.schedule_suggest())
        self.search.bind("<Return>", lambda _: (self.search_activate(), "break")[1])
        self.search.bind("<Escape>", lambda _: (self.close_search(), "break")[1])
        self.suggest_job = None

    @staticmethod
    def field_width():
        return S(380)

    def backdrop_under(self, x, y, w, h):
        """What lies under a floating control (in main-area coordinates), so rounded corners blend in."""
        image = Image.new("RGB", (max(1, w), max(1, h)), BG)
        hero = getattr(self, "hero_canvas", None)
        try:
            if hero is not None and hero.winfo_exists() and hero.winfo_ismapped() \
                    and getattr(hero, "bg_pil", None) is not None:
                hx = hero.winfo_rootx() - self.main.winfo_rootx()
                hy = hero.winfo_rooty() - self.main.winfo_rooty()
                top = self.canvas.winfo_rooty() - self.main.winfo_rooty()
                art = hero.bg_pil
                visible_top = max(hy, top)
                # only cut out the small piece under the control (copying the whole picture made scrolling slow)
                left, upper = x - hx, max(y, visible_top) - hy
                right, lower = min(art.width, left + w), min(art.height, y + h - hy)
                if right > max(0, left) and lower > upper:
                    piece = art.crop((max(0, left), upper, right, lower)).convert("RGB")
                    image.paste(piece, (max(0, left) - left, upper + hy - y))
        except tk.TclError:
            pass
        return image

    def hover_search(self, on):
        self.search_button.hover = on
        self.refresh_search_look()

    def queue_search_look(self):
        if not getattr(self, "search_look_job", None):
            self.search_look_job = self.root.after(16, self.refresh_search_look)

    def refresh_search_look(self, field_width=None):
        """Redraw the search button / field / results onto whatever is behind them."""
        self.search_look_job = None
        if not hasattr(self, "search_button"):
            return
        right = self.main.winfo_width() - S(34)
        if right <= S(100):
            right = max(S(400), self.root.winfo_width() - S(SIDEBAR_W) - S(34))
        top, size = S(22), S(44)
        hero = getattr(self, "hero_canvas", None)
        try:
            under = (hero.winfo_rooty() - self.main.winfo_rooty(), id(hero)) if hero is not None and hero.winfo_exists() \
                and hero.winfo_ismapped() and hero.winfo_rooty() - self.main.winfo_rooty() + hero.winfo_height() > top \
                else None
        except tk.TclError:
            under = None
        key = (under, self.search_open, self.search_button.hover, field_width, right,
               self.results_panel.winfo_manager() if self.search_open else None,
               id(getattr(hero, "bg_pil", None)) if under else None)
        if key == getattr(self, "search_look_key", None) and not self.search_open:
            return
        self.search_look_key = key
        if not self.search_open:
            base = self.backdrop_under(right - size, top, size, size)
            photo = ImageTk.PhotoImage(ui.render_round_button(base, "search", self.search_button.hover))
            self.search_button.configure(image=photo, width=size, height=size)
            self.search_button.photo = photo
            return
        width = field_width or self.field_width()
        base = self.backdrop_under(right - width, top, width, size)
        photo = ImageTk.PhotoImage(ui.render_card(base, size // 2, PANEL, LINE, "search", S(22)))
        self.search_field.configure(image=photo, width=width, height=size)
        self.search_field.photo = photo
        panel = self.results_panel
        if panel.winfo_manager():
            panel.update_idletasks()
            w, h = panel.winfo_reqwidth(), panel.winfo_reqheight()
            base = self.backdrop_under(right - w, S(74), w, h)
            photo = ImageTk.PhotoImage(ui.render_card(base, S(16), SIDE, LINE))
            panel.configure(image=photo)
            panel.photo = photo

    def open_search(self):
        if self.player_view or self.picker is not None:
            return
        if self.search_open:
            self.search.focus_set()
            return
        self.search_open = True
        if self.stage_mode == "slot":
            self.set_stage("mini")
        self.search_button.pack_forget()
        self.search_field.pack()
        self.search_holder.lift()
        end = self.field_width()

        def grow(step=1):
            if not self.search_open:
                return
            width = int(S(44) + (end - S(44)) * min(1, step / 7) ** 0.7)
            self.refresh_search_look(width)
            if step < 7:
                self.root.after(14, lambda: grow(step + 1))
            else:
                self.search.place(x=S(44), rely=.5, anchor="w", width=end - S(92), height=S(26))
                self.search_x.place(relx=1, x=-S(8), rely=.5, anchor="e")
                self.update_search_hint()
                self.search.focus_set()
                self.update_suggestions()
        grow()

    def update_search_hint(self):
        if self.search_open and not self.search_var.get():
            self.search_hint.place(x=S(46), rely=.5, anchor="w")
        else:
            self.search_hint.place_forget()

    def close_search(self):
        if not getattr(self, "search_open", False):
            return
        self.search_open = False
        self.results_panel.place_forget()
        self.search.place_forget()
        self.search_x.place_forget()
        self.search_hint.place_forget()
        self.search_field.pack_forget()
        self.search_button.hover = False
        self.refresh_search_look()
        self.search_button.pack()
        if self.search_var.get():
            self.search_var.set("")
        self.canvas.focus_set()
        if self.session and self.session["live"] and self.tab == "live" and not self.detail_item \
                and self.live_slot is not None and self.live_slot.winfo_exists():
            self.set_stage("slot", self.live_slot)

    def click_outside(self, event):
        if not self.search_open:
            return
        widget = event.widget
        inside = False
        while widget is not None:
            if widget in (self.search_holder, self.results_panel):
                inside = True
                break
            widget = getattr(widget, "master", None)
        if not inside:
            self.close_search()

    def schedule_suggest(self):
        self.update_search_hint()
        if self.suggest_job:
            self.root.after_cancel(self.suggest_job)
        self.suggest_job = self.root.after(140, self.update_suggestions)

    def update_suggestions(self):
        self.suggest_job = None
        card, panel = self.results_panel, self.results_inner
        for child in panel.winfo_children():
            child.destroy()
        self.search_rows, self.search_index = [], -1
        text = self.search_var.get().strip().casefold()
        if not self.search_open or not text:
            card.place_forget()
            return
        groups = {"movie": [], "series": [], "live": []}
        # Typing one more letter only narrows the previous matches, so scan those instead of the whole library.
        previous, matches = getattr(self, "search_cache", ("", None))
        pool = matches if matches is not None and previous and text.startswith(previous) else self.search_pool
        matches = [(title, item) for title, item in pool if text in title]
        self.search_cache = (text, matches)
        total = len(matches)
        for title, item in matches:
            bucket = groups.get(item.get("kind"))
            if bucket is not None and len(bucket) < 12:
                bucket.append(item)
        for kind in groups:
            groups[kind].sort(key=lambda i: (not str(i.get("title", "")).casefold().startswith(text), -score(i)))
            del groups[kind][4:]
        width = self.field_width() + S(80)
        tk.Frame(panel, bg=SIDE, width=width, height=S(2)).pack()
        if not total:
            label(panel, f"Niets gevonden voor “{self.search_var.get().strip()}”", 10, MUTED, SIDE).pack(
                anchor="w", padx=S(18), pady=S(16))
        lives = groups["live"]
        for kind, heading in (("movie", "FILMS"), ("series", "SERIES"), ("live", "ZENDERS")):
            if not groups[kind]:
                continue
            label(panel, heading, 8, DIM, SIDE, True).pack(anchor="w", padx=S(18), pady=(S(10), S(4)))
            for item in groups[kind]:
                self.search_row(panel, item, width, lives)
        if total:
            footer = tk.Frame(panel, bg=SIDE, padx=S(18), pady=S(12), cursor="hand2")
            footer.pack(fill="x", pady=(S(6), 0))
            label(footer, f"Alle {number(total)} resultaten bekijken", 10, ACCENT_SOFT, SIDE, True).pack(side="left")
            label(footer, "Enter", 9, DIM, SIDE).pack(side="right")
            ui.bind_hover(footer, lambda: ui.set_bg(footer, RAISED), lambda: ui.set_bg(footer, SIDE))
            ui.bind_click(footer, self.show_search_page)
        card.place(relx=1, x=-S(34), y=S(74), anchor="ne")
        card.lift()
        self.refresh_search_look()

    def search_row(self, panel, item, width, lives):
        row = tk.Frame(panel, bg=SIDE, padx=S(14), pady=S(6), cursor="hand2")
        row.pack(fill="x")
        live = item["kind"] == "live"
        thumb = tk.Label(row, bg=SIDE, bd=0, image=ui.placeholder_photo(S(40) if live else S(34), S(40) if live else S(50), RAISED, 6))
        thumb.pack(side="left")
        texts = tk.Frame(row, bg=SIDE)
        texts.pack(side="left", padx=S(12))
        label(texts, elide(item["title"], 11, width - S(120), True), 11, TEXT, SIDE, True).pack(anchor="w")
        group = str(item.get("group") or "")
        sub = KIND_LABEL.get(item["kind"], "") + (f"  ·  {group}" if group and group != "Overige" else "")
        if score(item) > 0:
            sub = f"★ {score(item):.1f}  ·  " + sub
        label(texts, elide(sub, 9, width - S(120)), 9, MUTED, SIDE).pack(anchor="w")
        if live:
            self.load_logo(thumb, item, S(40))
        else:
            self.load_thumb(thumb, item, (S(34), S(50)))
        index = len(self.search_rows)
        row.activate = (lambda: self.open_player(item, lives)) if live else (lambda: self.show_detail(item))
        row.paint = lambda flag: ui.set_bg(row, RAISED if flag else SIDE)
        self.search_rows.append(row)
        ui.bind_hover(row, lambda: self.search_move(index, absolute=True), lambda: row.paint(False))
        ui.bind_click(row, lambda: self.search_activate(index))

    def search_move(self, delta, absolute=False):
        if not self.search_rows:
            return
        if 0 <= self.search_index < len(self.search_rows) and self.search_rows[self.search_index].winfo_exists():
            self.search_rows[self.search_index].paint(False)
        self.search_index = delta if absolute else max(-1, min(len(self.search_rows) - 1, self.search_index + delta))
        if 0 <= self.search_index < len(self.search_rows):
            self.search_rows[self.search_index].paint(True)

    def search_activate(self, index=None):
        index = self.search_index if index is None else index
        if 0 <= index < len(self.search_rows):
            action = self.search_rows[index].activate
            self.close_search()
            action()
        elif self.search_var.get().strip():
            self.show_search_page()

    def show_search_page(self):
        text = self.search_var.get().strip()
        self.close_search()
        if text:
            self.detail_item = None
            self.query.set(text)

    def load_thumb(self, widget, item, size):
        url = art_url(item, "image")
        key = ("thumb", url or item.get("title"), size)
        if key in self.logo_cache:
            widget.configure(image=self.logo_cache[key])
            return
        title, kind = str(item["title"]), item["kind"]

        def build():
            base = (safe(cover, url, size) if url else None) or ui.poster_art(title, kind, *size)
            return ui.round_corners(base, S(6))

        def done(image):
            photo = ImageTk.PhotoImage(image)
            self.remember_photo(self.logo_cache, key, photo, 600)
            if widget.winfo_exists():
                widget.configure(image=photo)
        self.run(build, done, lambda _: None, artwork=True)

    @staticmethod
    def remember_photo(cache, key, photo, limit):
        cache[key] = photo
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    # ------------------------------------------------------------ smooth scrolling and staged building

    def smooth_scroll(self, pixels):
        box = self.canvas.bbox("all")
        if not box:
            return
        total, view = box[3], self.canvas.winfo_height()
        if total <= view:
            return
        top = self.canvas.yview()[0] * total
        base = self.scroll_target if self.scroll_job and self.scroll_target is not None else top
        self.scroll_target = max(0, min(total - view, base + pixels))
        if not self.scroll_job:
            self.scroll_job = self.root.after(0, self.scroll_step)

    def scroll_step(self):
        self.scroll_job = None
        box = self.canvas.bbox("all")
        if not box or self.scroll_target is None:
            return
        total = box[3]
        top = self.canvas.yview()[0] * total
        difference = self.scroll_target - top
        if abs(difference) < 3:
            self.canvas.yview_moveto(self.scroll_target / total)
            self.scroll_target = None
            return
        self.canvas.yview_moveto((top + difference * 0.35) / total)
        self.scroll_job = self.root.after(16, self.scroll_step)

    def defer(self, function):
        self.deferred.append((self.generation, function))
        if not self.defer_job:
            self.defer_job = self.root.after(1, self.run_deferred)

    def run_deferred(self):
        self.defer_job = None
        while self.deferred:
            generation, function = self.deferred.pop(0)
            if generation == self.generation:
                try:
                    function()
                except tk.TclError:
                    pass
                except Exception:
                    self.report_error(*sys.exc_info())
                break
        if self.deferred:
            self.defer_job = self.root.after(6, self.run_deferred)

    # ------------------------------------------------------------ playback (one shared video engine)

    def build_stage(self):
        self.stage = tk.Frame(self.root, bg="#000000", cursor="hand2")
        self.stage.bind("<Button-1>", self.stage_click)
        self.stage.bind("<Double-Button-1>", self.stage_double)
        mini = tk.Frame(self.root, bg=SIDE, highlightthickness=1, highlightbackground=LINE, padx=S(10))
        self.mini = mini
        texts = tk.Frame(mini, bg=SIDE)
        texts.pack(side="left", fill="both", expand=True)
        self.mini_title = label(texts, "", 10, TEXT, SIDE, True, anchor="w", cursor="hand2")
        self.mini_title.pack(anchor="w", pady=(S(6), 0), fill="x")
        self.mini_sub = label(texts, "", 9, MUTED, SIDE, anchor="w")
        self.mini_sub.pack(anchor="w", fill="x")
        self.mini_title.bind("<Button-1>", lambda _: self.expand_player())
        Pill(mini, "", self.stop_playback, kind="quiet", icon="close", h=34).pack(side="right")
        Pill(mini, "", self.expand_player, kind="quiet", icon="expand", h=34).pack(side="right")
        Pill(mini, "", self.open_pip, kind="quiet", icon="pip", h=34).pack(side="right")
        self.mini_play = Pill(mini, "", self.toggle_pause, kind="quiet", icon="pause", h=34)
        self.mini_play.pack(side="right")

        def update(session):
            if not session:
                return True
            title = session["item"].get("title", "")
            self.mini_title.configure(text=elide(title, 10, S(220), True))
            if session["live"]:
                position = session["position"]
                behind = self.live_offset()
                sub = (("LIVE" if behind < 5 else f"−{clock(behind)} achter live") + (f"  ·  {position + 1}" if position >= 0 else ""))
            else:
                length = self.engine.media_player_get_length(self.engine.player)
                moment = self.engine.media_player_get_time(self.engine.player)
                sub = f"{clock(moment / 1000)} / {clock(length / 1000)}" if length > 0 and moment >= 0 else "Laden…"
            if session.get("count_until"):
                sub = f"Volgende aflevering over {max(0, int(session['count_until'] - monotonic()) + 1)} s"
            self.mini_sub.configure(text=sub)
            icon = "pause" if session.get("view_state", session.get("state")) == 3 else "play"
            if self.mini_play.opts["icon"] != icon:
                self.mini_play.update_pill(icon=icon)
            return True
        self.listeners["mini"] = update

    def ensure_engine(self):
        if self.engine:
            return True
        self.root.update_idletasks()
        try:
            trace("videomotor starten")
            self.engine = Player(self.stage.winfo_id())
            trace("videomotor klaar")
        except (OSError, ValueError, AttributeError):
            self.engine = None
            return False
        return True

    def play(self, item, playlist=None):
        if not self.ensure_engine():
            self.toast("De ingebouwde videospeler kon niet starten", "close")
            return False
        if self.session and not self.session["live"]:
            self.remember_progress()
        try:
            offline = item.get("file") or self.downloaded_file(item.get("id"))
            url = Path(offline).as_uri() if offline and Path(offline).is_file() else data.check_url(item["url"])
            options = self.play_options()
            self.close_buffer()
            self.session = None
            self.clear_live_buffers()
            buffer = None
            seconds = self.buffer_minutes() * 60
            heavy = re.search(r"(?<![A-Z0-9])(4K|8K|16K|UHD|2160P?|HEVC|H265)(?![A-Z0-9])|[ᵁ]ᴴᴰ",
                              str(item.get("raw_title") or item.get("title", "")), re.I)
            waiting = False
            if item["kind"] == "live" and seconds and not offline:
                buffer = engine_module.LiveBuffer(url, data.STATE.parent / "buffer" / uuid4().hex[:10], seconds)
                if heavy:
                    # 4K: a light background recorder saves the stream (no picture work), and the player shows the
                    # saved pieces with the graphics card. Starts a few seconds later, but rewinding works too.
                    buffer.start_recorder()
                    waiting = True
                else:
                    options = options + [":sout=" + buffer.display_chain(), ":sout-keep"]
            trace(f"afspelen: {item.get('title', '')} ({item.get('kind')}, buffer {'aan' if buffer is not None else 'uit'}"
                  f"{', 4K' if heavy else ''})")
            if waiting:
                self.engine.stop()
            else:
                self.engine.open(url, options)
            trace("afspelen gestart")
        except (ValueError, OSError, KeyError):
            self.toast("Deze titel kan niet worden geopend", "close")
            return False
        playlist = [e for e in (playlist or []) if e.get("url") or e.get("file")]
        position = next((i for i, e in enumerate(playlist) if e.get("id") == item.get("id")), -1)
        live = item["kind"] == "live"
        self.session = {
            "item": item, "playlist": playlist, "live": live, "position": position,
            "previous": playlist[position - 1] if position > 0 else None,
            "next": playlist[position + 1] if 0 <= position < len(playlist) - 1 else None,
            "resume": 0 if live else self.progress.get(item["id"], {}).get("time", 0),
            "saved": monotonic(), "state": None, "ended": False, "failed": False, "count_until": None,
            "url": url, "options": options, "retries": 0, "buffer": buffer, "heavy": bool(live and heavy),
            "await_buffer": monotonic() if waiting else None, "direct_url": url,
            "intro": bool(item.get("series")) and self.preferences.get("intro_button", True),
        }
        self.apply_volume()
        self.autoplayed = True
        if live:
            self.remember_preference("last_channel", item["id"])
        if not self.tick_job:
            self.tick_job = self.root.after(400, self.session_tick)
        self.queue_place()
        return True

    def play_options(self):
        buffer = int(self.preferences.get("buffer_ms", 3000) or 3000)
        options = [f":network-caching={buffer}", f":live-caching={buffer}", ":http-reconnect"]
        options.append(":avcodec-hw=any" if self.preferences.get("hw_decode", True) else ":avcodec-hw=none")
        return options

    def retry(self, session):
        self.reconnect_job = None
        if self.session is not session or not self.engine:
            return
        buffer = session.get("buffer")
        if buffer is not None:
            # Safety first: when a live stream with the pause buffer fails, play it the plain way (as before the
            # buffer existed) and leave the buffer off until Zono restarts.
            session["buffer"] = None
            self.close_quietly(buffer)
            session["url"] = session.get("direct_url") or session["url"]
            session["options"] = self.play_options()
            if not self.buffer_failed:
                self.buffer_failed = True
                data.log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Live pauzeren uitgeschakeld: "
                               f"{session['item'].get('title', '')} speelde niet met de buffer")
        try:
            self.engine.open(session["url"], session["options"])
        except (ValueError, OSError):
            return
        session.update(failed=False, ended=False, state=None, reconnecting=False)
        session.pop("playing_since", None)

    def stop_playback(self):
        if self.pip_window is not None:
            window, self.pip_window = self.pip_window, None
            self.listeners.pop("pip", None)
            try:
                window.destroy()
            except tk.TclError:
                pass
        if self.session and not self.session["live"]:
            self.remember_progress()
        if self.engine:
            self.engine.stop()
        self.close_buffer()
        self.session = None
        self.clear_live_buffers()
        if self.player_close:
            self.player_close(minimize=False)
        self.stage_mode, self.stage_target = "hidden", None
        self.place_stage()
        if self.tab == "live" and not self.detail_item:
            self.render()

    def toggle_pause(self):
        session = self.session
        if self.engine and session and session["live"] and session.get("buffer") is not None \
                and not session["buffer"].local:
            self.go_local(8, paused=True)
            return
        if self.engine and session:
            self.engine.media_player_pause(self.engine.player)

    # ------------------------------------------------------------ live pause / rewind

    def buffer_minutes(self):
        if SAFE_MODE or self.buffer_failed:
            return 0
        try:
            return max(0, int(self.preferences.get("live_buffer_min_v2", 0)))
        except (TypeError, ValueError):
            return 30

    def explain_rewind(self, session):
        if SAFE_MODE:
            text = "Terugspoelen staat even uit: veilige start. Zet het weer aan bij Instellingen › Afspelen"
        elif self.buffer_failed:
            text = "Terugspoelen is uitgeschakeld omdat de zender er niet goed mee speelde · herstart Zono om opnieuw te proberen"
        elif not self.buffer_minutes():
            text = "Terugspoelen is een proefoptie · zet ‘Live tv pauzeren’ aan bij Instellingen › Afspelen"
        else:
            text = "Terugspoelen lukt niet bij deze zender"
        self.toast(text, "info")

    def leave_safe_mode(self):
        global SAFE_MODE
        SAFE_MODE = False
        self.toast("Live pauzeren staat weer aan · geldt vanaf de volgende zender", "check")
        if self.tab == "settings":
            self.render()

    @staticmethod
    def close_quietly(thing):
        """Stopping a network stream can take VLC a few seconds: do it in the background, never on the screen."""
        def run():
            try:
                thing.close()
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def close_buffer(self):
        session = self.session
        if session and session.get("buffer") is not None:
            self.hand_over_recordings(session["buffer"])
            self.close_quietly(session["buffer"])
            session["buffer"] = None

    def stop_shift(self, resume_live=True):
        """Kept for older call sites: rewinding now uses the one and only player."""

    def clear_live_buffers(self):
        """Remove the files of earlier live buffers (the running one is kept)."""
        root = data.STATE.parent / "buffer"
        current = self.session.get("buffer") if self.session else None
        keep = current.root if current is not None else None
        if not root.is_dir():
            return
        for folder in root.iterdir():
            if keep is None or folder != keep:
                shutil.rmtree(folder, ignore_errors=True)

    def live_buffer(self):
        """Seconds of the current live channel that Zono kept (0 when there is no buffer)."""
        session = self.session
        buffer = session.get("buffer") if session else None
        if buffer is None:
            return 0
        try:
            return buffer.seconds_kept()
        except OSError:
            return 0

    def live_offset(self):
        """How many seconds behind live the picture is."""
        session = self.session
        buffer = session.get("buffer") if session else None
        if buffer is None or not buffer.local or not self.engine:
            return 0
        engine = self.engine
        length = engine.media_player_get_length(engine.player)
        moment = engine.media_player_get_time(engine.player)
        if length > 0 and moment >= 0:
            session["offset"] = max(0.0, (length - moment) / 1000)
        return session.get("offset", 0)

    def go_local(self, offset, paused=False):
        """From now on play the saved pieces from disk, `offset` seconds behind live. A small recorder keeps the
        provider stream coming in, so this still uses one connection."""
        session = self.session
        buffer = session.get("buffer") if session else None
        if buffer is None or not self.engine:
            return False
        kept = buffer.seconds_kept()
        if kept < 10:
            self.toast("Zono bouwt nog een buffer op · probeer het over een paar seconden", "clock")
            return False
        offset = max(6, min(offset, kept - 4))
        try:
            buffer.keep_parts()
            self.engine.stop()
            buffer.start_recorder()
            options = [f":adaptive-livedelay={int(offset * 1000)}", ":network-caching=500",
                       ":avcodec-hw=any" if self.preferences.get("hw_decode", True) else ":avcodec-hw=none"]
            self.engine.open(buffer.index_uri(), options)
        except (OSError, ValueError, AttributeError) as error:
            data.log_error(f"Terugspoelen: {error!r}")
            self.toast("Terugspoelen lukt nu niet", "close")
            return False
        session.update(url=buffer.index_uri(), state=None, failed=False, ended=False, offset=offset,
                       options=[":adaptive-livedelay=6000", ":network-caching=500", options[-1]],
                       pause_when_ready=paused)
        self.apply_volume()
        return True

    def live_to(self, offset):
        """Show the live channel `offset` seconds in the past (0 = live)."""
        session = self.session
        buffer = session.get("buffer") if session else None
        if buffer is None or not self.engine:
            return
        if not buffer.local:
            if offset >= 5:
                self.go_local(offset)
            return
        engine = self.engine
        length = engine.media_player_get_length(engine.player)
        if length > 0 and engine.media_player_is_seekable(engine.player):
            target = max(4.0, offset)  # "live" stays a few seconds behind, so the picture never runs dry
            engine.media_player_set_time(engine.player, int(max(0, length - target * 1000)))
            session["offset"] = target
            if engine.media_player_get_state(engine.player) == 4:
                engine.media_player_pause(engine.player)

    def live_seek(self, seconds):
        if not self.session or self.session.get("buffer") is None:
            return
        self.live_to(max(0, min(self.live_buffer() - 4, self.live_offset() - seconds)))

    def apply_volume(self):
        level = 0 if self.muted else self.volume
        if self.engine:
            self.engine.audio_set_volume(self.engine.player, level)

    def set_volume(self, value):
        self.volume, self.muted = int(value), False
        self.apply_volume()

    def toggle_mute(self):
        self.muted = not self.muted
        self.apply_volume()

    def jump(self, seconds):
        if self.engine and self.session and self.session["live"]:
            self.live_seek(seconds)
            return
        if not self.engine or not self.session:
            return
        length = self.engine.media_player_get_length(self.engine.player)
        moment = self.engine.media_player_get_time(self.engine.player)
        if length > 0 and moment >= 0:
            self.engine.media_player_set_time(self.engine.player, max(0, min(length - 1, moment + seconds * 1000)))

    def save_watched(self):
        try:
            data.write_json(data.STATE.with_name("watched.json"), self.watched)
        except OSError:
            pass

    def set_watched(self, item_id, seen=True):
        if seen:
            self.watched[item_id] = int(time())
            self.progress.pop(item_id, None)
        else:
            self.watched.pop(item_id, None)
        self.save_watched()

    def glide(self, canvas, pixels):
        """Scroll a row of cards sideways smoothly instead of jumping."""
        if not canvas.winfo_exists():
            return
        region = canvas.cget("scrollregion").split()
        total = float(region[2]) if len(region) == 4 else 0
        view = canvas.winfo_width()
        if total <= view:
            return
        start = canvas.canvasx(0)
        base = getattr(canvas, "glide_target", start) if getattr(canvas, "glide_job", None) else start
        target = max(0.0, min(total - view, base + pixels))
        canvas.glide_target = target
        if getattr(canvas, "glide_job", None):
            canvas.after_cancel(canvas.glide_job)
        steps = 14

        def step(index=1):
            if not canvas.winfo_exists():
                return
            amount = 1 - (1 - index / steps) ** 3  # ease out
            canvas.xview_moveto((start + (target - start) * amount) / total)
            if index < steps:
                canvas.glide_job = canvas.after(14, lambda: step(index + 1))
            else:
                canvas.glide_job = None
                canvas.glide_target = target
        step()

    def remember_progress(self, ended=False):
        session = self.session
        if not session or session["live"] or not self.engine or session["item"].get("kind") == "catchup":
            return
        item = session["item"]
        length = self.engine.media_player_get_length(self.engine.player) / 1000
        moment = self.engine.media_player_get_time(self.engine.player) / 1000
        if ended or (length > 0 and (moment >= length - 3 or (length > 300 and moment >= length * 0.93))):
            # finished (the credits count as finished, like Netflix): tick it off and take it out of "Verder kijken"
            self.progress.pop(item["id"], None)
            self.watched[item["id"]] = int(time())
            self.save_watched()
        elif length > 0 and moment >= 3:
            self.progress[item["id"]] = {"item": item, "time": moment, "duration": length,
                                         "updated": int(datetime.now().timestamp() * 1000)}
        else:
            return
        try:
            self.save_activity()
        except OSError:
            pass

    def session_tick(self):
        self.tick_job = None
        try:
            self._session_tick()
        except Exception:
            self.report_error(*sys.exc_info())
            if self.session and not self.tick_job:
                self.tick_job = self.root.after(1000, self.session_tick)

    def _session_tick(self):
        session = self.session
        if not session or not self.engine:
            return
        engine = self.engine
        if session.get("await_buffer"):
            buffer = session.get("buffer")
            kept = buffer.seconds_kept() if buffer is not None else 0
            if buffer is not None and kept >= 8:
                hw = ":avcodec-hw=any" if self.preferences.get("hw_decode", True) else ":avcodec-hw=none"
                options = [":adaptive-livedelay=5000", ":network-caching=800", hw]
                engine.open(buffer.index_uri(), options)
                session.update(url=buffer.index_uri(), options=options, await_buffer=None, state=None)
                trace("4K: afspelen vanaf buffer")
            elif buffer is None or buffer.recorder_failed() or monotonic() - session["await_buffer"] > 25:
                # could not build a buffer: just play the channel directly
                session["await_buffer"] = None
                if buffer is not None:
                    self.close_quietly(buffer)
                session["buffer"] = None
                session["options"] = self.play_options()
                session["url"] = session["direct_url"]
                engine.open(session["url"], session["options"])
                trace("4K: buffer lukte niet, rechtstreeks afspelen")
            else:
                session["state"] = session["view_state"] = 1  # "Stream openen…"
                for name, listener in list(self.listeners.items()):
                    try:
                        if listener(self.session) is False:
                            self.listeners.pop(name, None)
                    except tk.TclError:
                        self.listeners.pop(name, None)
                self.tick_job = self.root.after(500, self.session_tick)
                return
        state = engine.media_player_get_state(engine.player)
        session["state"] = state
        session["view_state"] = state
        buffer = session.get("buffer")
        if buffer is not None and buffer.local:
            if state == 3 and session.get("pause_when_ready"):
                engine.media_player_pause(engine.player)
                session["pause_when_ready"] = False
            if buffer.recorder_failed() and monotonic() - session.get("recorder_retry", 0) > 15 \
                    and session.get("recorder_retries", 0) < 5:  # the provider dropped: reconnect, but calmly
                session["recorder_retry"] = monotonic()
                session["recorder_retries"] = session.get("recorder_retries", 0) + 1
                try:
                    buffer.start_recorder()
                except (OSError, ValueError):
                    pass
        if state == 3:
            if session["resume"] and engine.media_player_get_length(engine.player) > 0:
                engine.media_player_set_time(engine.player, int(session["resume"] * 1000))
                session["resume"] = 0
            if monotonic() - session["saved"] > 10:
                session["saved"] = monotonic()
                self.remember_progress()
            session.setdefault("playing_since", monotonic())
            if monotonic() - session["playing_since"] > 30:
                session["retries"] = 0
        elif (state == 7 or (state == 6 and session["live"])) and not session["failed"]:
            session["failed"] = True
            trace(f"stream gestopt (status {state}, buffer {'aan' if session.get('buffer') is not None else 'uit'}): "
                  f"{session['item'].get('title', '')}")
            if session["retries"] == 2 and session["live"]:
                data.log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Zender valt telkens weg: {session['item'].get('title', '')} "
                               f"(VLC-status {state}). Speelt er nog iets op een ander toestel? Veel abonnementen laten "
                               f"maar één stream tegelijk toe.")
            if self.preferences.get("reconnect", True) and session["retries"] < 3:
                session["retries"] += 1
                session["reconnecting"] = True
                self.toast(f"Verbinding weggevallen · opnieuw verbinden ({session['retries']}/3)", "refresh")
                self.reconnect_job = self.root.after(1500, lambda: self.retry(session))
            else:
                session["reconnecting"] = False
                busy = bool(self.recorders) or (self.remote.running and self.remote.converter)
                self.toast("Deze stream start niet · " + ("er loopt nog een opname of een stream naar je telefoon"
                                                          if busy else "probeer een andere zender of herstart Zono"), "close")
        elif state == 6 and not session["ended"]:
            session["ended"] = True
            self.remember_progress(ended=True)
            if session["next"] and not session["live"] and self.preferences.get("autonext", True) \
                    and not session.get("count_until"):
                session["count_until"] = monotonic() + 8
        if state in (3, 4) and session["next"] and not session["live"] and not session.get("upnext_dismissed"):
            length = engine.media_player_get_length(engine.player) / 1000
            moment = engine.media_player_get_time(engine.player) / 1000
            left = length - moment
            # the credits, like Netflix: from the last minute (or last 3 %) a "Volgende aflevering" button on the
            # picture; in the last 15 seconds it counts down and starts the next episode by itself
            session["upnext_show"] = length > 300 and 0 < left <= max(60, length * 0.03)
            if session["upnext_show"] and state == 3 and left <= 15 and not session.get("count_until") \
                    and self.preferences.get("autonext", True):
                session["count_until"] = monotonic() + max(3, left)
        if session.get("count_until") and monotonic() >= session["count_until"]:
            following, playlist = session["next"], session["playlist"]
            if self.player_view is not None:
                self.open_player(following, playlist, fullscreen=bool(self.player_full))
            else:
                self.play(following, playlist)
                self.toast(f"Volgende: {elide(following.get('title', ''), 10, S(300), True)}", "play")
        for name, listener in list(self.listeners.items()):
            try:
                if listener(self.session) is False:
                    self.listeners.pop(name, None)
            except tk.TclError:
                self.listeners.pop(name, None)
        if self.session:
            self.tick_job = self.root.after(500, self.session_tick)

    # ------------------------------------------------------------ picture-in-picture (separate always-on-top window)

    def move_video(self, hwnd):
        """Re-attach the running video to another window and continue where it was."""
        session, engine = self.session, self.engine
        if not session or not engine:
            return
        moment = engine.media_player_get_time(engine.player) if not session["live"] else -1
        buffer = session.get("buffer")
        if buffer is not None and not buffer.local:
            buffer.keep_parts()
            session["options"] = self.play_options() + [":sout=" + buffer.display_chain(), ":sout-keep"]
        engine.stop()
        engine.set_window(hwnd)
        try:
            engine.open(session["url"], session["options"])
        except (ValueError, OSError):
            return
        if moment and moment > 0:
            session["resume"] = moment / 1000
        session.update(state=None, ended=False, failed=False)
        self.apply_volume()

    def open_pip(self, automatic=False):
        if not self.session or self.pip_window is not None:
            return
        self.pip_auto = automatic
        if self.player_close:
            self.player_close(minimize=False, keep_mode=True)
        window = tk.Toplevel(self.root, bg="#000000")
        self.pip_window = window
        window.title(f"Zono  ·  {self.session['item'].get('title', '')}")
        width = S(480)
        height = int(width * 9 / 16) + S(44)
        x = window.winfo_screenwidth() - width - S(28)
        y = window.winfo_screenheight() - height - S(80)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(S(280), S(200))
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        icon = Path(__file__).with_name("Zono.ico")
        if icon.exists():
            try:
                window.iconbitmap(str(icon))
            except tk.TclError:
                pass
        bar = tk.Frame(window, bg=SIDE, height=S(44), padx=S(8))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        surface = tk.Frame(window, bg="#000000", cursor="hand2")
        surface.pack(fill="both", expand=True)
        title = label(bar, elide(self.session["item"].get("title", ""), 10, S(220), True), 10, TEXT, SIDE, True)
        Pill(bar, "", lambda: self.close_pip(stop=True), kind="quiet", icon="close", h=32).pack(side="right")
        Pill(bar, "", lambda: self.close_pip(expand=True), kind="quiet", icon="expand", h=32).pack(side="right")
        play = Pill(bar, "", self.toggle_pause, kind="quiet", icon="pause", h=32)
        play.pack(side="left")
        title.pack(side="left", padx=S(6))

        def update(session):
            if not window.winfo_exists():
                return False
            if session:
                icon_name = "pause" if session.get("state") == 3 else "play"
                if play.opts["icon"] != icon_name:
                    play.update_pill(icon=icon_name)
                title.configure(text=elide(session["item"].get("title", ""), 10, S(220), True))
            return True
        self.listeners["pip"] = update
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_pip())
        window.bind("<space>", lambda _: self.toggle_pause())
        window.bind("<Escape>", lambda _: self.close_pip())
        surface.bind("<Double-Button-1>", lambda _: self.close_pip(expand=True))
        window.update_idletasks()
        self.stage_mode, self.stage_target = "pip", None
        self.place_stage()
        self.move_video(surface.winfo_id())

    def close_pip(self, expand=False, stop=False, mode="mini", target=None):
        window = self.pip_window
        if window is None:
            return
        self.pip_window = None
        self.listeners.pop("pip", None)
        if stop:
            try:
                window.destroy()
            except tk.TclError:
                pass
            self.stop_playback()
            return
        self.root.update_idletasks()
        self.move_video(self.stage.winfo_id())
        try:
            window.destroy()
        except tk.TclError:
            pass
        if self.root.state() == "iconic":
            self.root.deiconify()
        if expand and self.session:
            self.expand_player()
        else:
            self.set_stage(mode, target)

    def root_state_changed(self, event):
        if event.widget is not self.root:
            return
        if self.root.state() == "iconic":
            if self.session and self.pip_window is None and self.preferences.get("auto_pip", True) \
                    and self.session.get("state") == 3:
                self.root.after(150, lambda: self.open_pip(automatic=True))
        elif self.pip_window is not None and self.preferences.get("auto_pip", True) and getattr(self, "pip_auto", False):
            self.close_pip()

    def set_stage(self, mode, target=None):
        if self.pip_window is not None and mode in ("slot", "full"):
            self.close_pip(mode=mode, target=target)
            return
        self.stage_mode, self.stage_target = mode, target
        self.place_stage()
        for delay in (150, 450):
            self.root.after(delay, self.queue_place)

    def queue_place(self):
        self.queue_search_look()
        if not self.place_job:
            self.place_job = self.root.after(30, self.place_stage)

    def place_stage(self):
        self.place_job = None
        if not hasattr(self, "stage"):
            return
        if (self.picker is not None and self.picker.winfo_exists()) or (self.sheet_close and not self.player_view) \
                or self.trailer_view is not None or self.multiview is not None:
            self.stage.place_forget()
            self.mini.place_forget()
            return
        if not self.session or self.stage_mode in ("hidden", "pip"):
            self.stage.place_forget()
            self.mini.place_forget()
            return
        target = self.stage_target
        if self.stage_mode in ("slot", "full"):
            if target is None or not target.winfo_exists():
                self.stage_mode, self.stage_target = "mini", None
            elif not target.winfo_ismapped() or target.winfo_width() <= 1:
                self.stage.place_forget()
                self.mini.place_forget()
                self.root.after(60, self.queue_place)
                return
            else:
                x = target.winfo_rootx() - self.root.winfo_rootx()
                y = target.winfo_rooty() - self.root.winfo_rooty()
                w, h = target.winfo_width(), target.winfo_height()
                visible = True
                if self.stage_mode == "slot":
                    top = self.main.winfo_rooty() - self.root.winfo_rooty()
                    visible = y >= top - S(4) and y + h <= top + self.main.winfo_height() + S(4) and not self.sheet_close
                if visible:
                    self.mini.place_forget()
                    self.stage.place(x=x, y=y, relx=0, rely=0, width=w, height=h, anchor="nw")
                    self.stage.lift()
                    return
        width = S(384)
        height = int(width * 9 / 16)
        margin, bar = S(20), S(50)
        self.stage.place(relx=1, rely=1, x=-margin, y=-(margin + bar), width=width, height=height, anchor="se")
        self.mini.place(relx=1, rely=1, x=-margin, y=-margin, width=width, height=bar, anchor="se")
        self.stage.lift()
        self.mini.lift()

    def stage_click(self, _=None):
        if self.stage_mode == "full" and self.player_show:
            self.player_show()
        elif self.stage_mode not in ("full", "slot"):
            self.expand_player()

    def stage_double(self, _=None):
        if self.stage_mode == "full" and self.player_full_toggle:
            self.player_full_toggle()
        elif self.stage_mode == "slot":
            self.expand_player(fullscreen=True)

    def expand_player(self, fullscreen=False):
        if self.session:
            self.open_player(self.session["item"], self.session["playlist"], fullscreen=fullscreen)

    def find_episodes(self, session):
        """An episode started from "Verder kijken", Downloads or search has no episode list yet: fetch the series,
        so "Volgende aflevering" works like on Netflix."""
        session["looked_up"] = True
        item = session["item"]
        if not self.source:
            return
        sid = item.get("series_sid")
        if not sid:
            name = str(item.get("series", "")).casefold()
            match = next((s for s in self.by_kind.get("series", [])
                          if name and name in (str(s.get("title", "")).casefold(), str(s.get("raw_title", "")).casefold())), None)
            sid = match.get("sid") if match else None
            image = match.get("image", "") if match else ""
        else:
            image = item.get("image", "")
        if not sid:
            return
        source = self.source

        def done(rows):
            if self.session is not session or not rows:
                return
            for row in rows:
                row.setdefault("series", item.get("series", ""))
                row.setdefault("series_sid", sid)
                row.setdefault("image", image or item.get("image", ""))
            position = next((i for i, r in enumerate(rows) if r.get("id") == item.get("id")), -1)
            if position < 0:  # same episode, other link: match on title within the season
                position = next((i for i, r in enumerate(rows) if r.get("title") == item.get("title")
                                 and r.get("group") == item.get("group")), -1)
            if position < 0:
                return
            session.update(playlist=rows, position=position,
                           previous=rows[position - 1] if position > 0 else None,
                           next=rows[position + 1] if position < len(rows) - 1 else None)
            if session["next"] and self.player_view is not None and self.session is session:
                self.open_player(item, rows, fullscreen=bool(self.player_full))  # rebuild the buttons, video keeps going
        self.run(lambda: data.episodes(source, sid), done, lambda _: None)

    def open_player(self, item, playlist=None, fullscreen=False):
        """Full-window player inside the app. Leaving it keeps the video playing in the mini player."""
        if self.sheet_close:
            self.sheet_close()
        if self.player_close:
            self.player_close(minimize=False, keep_mode=True)
        same = bool(self.session and self.session["item"].get("id") == item.get("id"))
        if not same and not self.play(item, playlist):
            return
        session = self.session
        if item.get("series") and not session["next"] and not session.get("looked_up"):
            self.find_episodes(session)
        live = session["live"]
        window = tk.Frame(self.root, bg=BG)
        window.place(x=0, y=0, relwidth=1, relheight=1)
        window.lift()
        self.player_view = window
        state = {"full": False, "hide": None, "closing": False, "guide": None}
        window.configure(bg="#000000")
        header = tk.Frame(window, bg="#000000", padx=S(14), pady=S(10))
        header.pack(fill="x")
        controls = tk.Frame(window, bg="#000000", padx=S(14), pady=S(6))
        controls.pack(side="bottom", fill="x")
        video = tk.Frame(window, bg="#000000")
        video.pack(fill="both", expand=True)
        video.bind("<Configure>", lambda _: self.queue_place())
        Pill(header, "", lambda: close(), kind="bare", icon="back", h=46, bg="#000000").pack(side="left")
        Pill(header, "", lambda: self.stop_playback(), kind="bare", icon="close", h=46, bg="#000000").pack(side="right")
        status = label(header, "", 10, ACCENT_SOFT, "#000000", wraplength=S(420), justify="right")
        status.pack(side="right", padx=S(12))

        def switch_to(other):
            if other:
                self.open_player(other, session["playlist"], fullscreen=state["full"])

        def set_full(flag):
            state["full"] = flag
            self.player_full = flag
            try:
                self.root.attributes("-fullscreen", flag)
            except tk.TclError:
                pass
            if flag:
                header.pack_forget()
                schedule_hide()
            else:
                header.pack(side="top", fill="x", before=controls)
                show_controls()
            self.queue_place()

        def show_controls(_=None):
            if not window.winfo_exists():
                return
            if not controls.winfo_ismapped():
                controls.pack(side="bottom", fill="x", before=video)
                self.queue_place()
            for widget in (window, self.stage):
                try:
                    widget.configure(cursor="")
                except tk.TclError:
                    pass
            schedule_hide()

        def schedule_hide():
            if state["hide"]:
                window.after_cancel(state["hide"])
                state["hide"] = None
            if state["full"]:
                state["hide"] = window.after(2600, hide)

        def hide():
            state["hide"] = None
            if state["full"] and window.winfo_exists():
                controls.pack_forget()
                self.queue_place()
                for widget in (window, self.stage):
                    try:
                        widget.configure(cursor="none")
                    except tk.TclError:
                        pass

        def floating_panel(width, corner="right", alpha=0.86):
            """A see-through panel that floats over the video, so the picture keeps its size."""
            shell = tk.Toplevel(window, bg=SIDE)
            shell.withdraw()
            shell.overrideredirect(True)
            try:
                shell.attributes("-alpha", alpha)
            except tk.TclError:
                pass
            panel = tk.Frame(shell, bg=SIDE, padx=S(20), pady=S(18))
            panel.pack(fill="both", expand=True)
            panel.shell = shell
            shell.bind("<MouseWheel>", self.wheel)
            shell.bind("<Button-4>", lambda e: self.wheel(e, 120))
            shell.bind("<Button-5>", lambda e: self.wheel(e, -120))
            last = {"geometry": None, "shown": False}

            def follow():
                if not shell.winfo_exists():
                    return
                visible = video.winfo_ismapped() and self.root.state() != "iconic" and window.winfo_exists()
                if not visible:
                    if last["shown"]:
                        shell.withdraw()
                        last["shown"] = False
                else:
                    margin = S(14)
                    if corner == "card":
                        w, h = shell.winfo_reqwidth(), shell.winfo_reqheight()
                        x = video.winfo_rootx() + video.winfo_width() - w - S(28)
                        y = video.winfo_rooty() + video.winfo_height() - h - S(28)
                    else:
                        w = min(S(width), max(S(200), video.winfo_width() - 2 * margin))
                        h = max(S(160), video.winfo_height() - 2 * margin)
                        x = video.winfo_rootx() + video.winfo_width() - w - margin
                        y = video.winfo_rooty() + margin
                    geometry = f"{w}x{h}+{x}+{y}"
                    if geometry != last["geometry"]:
                        shell.geometry(geometry)
                        last["geometry"] = geometry
                    if not last["shown"]:
                        shell.deiconify()
                        ui.window_style(shell, rounded=True, no_activate=True)
                        last["shown"] = True
                    shell.lift()
                shell.after(150, follow)
            shell.after(10, follow)
            return panel

        def close_panel():
            if state["guide"] is not None and state["guide"].winfo_exists():
                shell = getattr(state["guide"], "shell", None)
                state["guide"].destroy()
                if shell is not None and shell.winfo_exists():
                    shell.destroy()
            state["guide"] = None
            state["panel"] = None
            self.queue_place()

        def toggle_cast():
            if state.get("panel") == "cast":
                close_panel()
                return
            close_panel()
            panel = floating_panel(380)
            state["guide"], state["panel"] = panel, "cast"
            self.queue_place()
            top = tk.Frame(panel, bg=SIDE)
            top.pack(fill="x")
            label(top, "Casten", 14, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", close_panel, kind="ghost", icon="close", h=32).pack(side="right")
            body = tk.Frame(panel, bg=SIDE)
            body.pack(fill="both", expand=True, pady=(S(10), 0))

            def section(title):
                label(body, title, 8, DIM, SIDE, True).pack(anchor="w", pady=(S(12), S(6)))

            def render_panel(devices=None, searching=False):
                if not body.winfo_exists():
                    return
                for child in body.winfo_children():
                    child.destroy()
                if self.casting:
                    device = self.casting["device"]
                    box = tk.Frame(body, bg=RAISED, padx=S(14), pady=S(12))
                    box.pack(fill="x", pady=(S(6), 0))
                    label(box, "SPEELT AF OP", 8, ACCENT_SOFT, RAISED, True).pack(anchor="w")
                    label(box, elide(device["name"], 12, S(300), True), 12, TEXT, RAISED, True).pack(anchor="w")
                    label(box, elide(self.casting["title"], 10, S(300)), 10, MUTED, RAISED).pack(anchor="w")
                    buttons = tk.Frame(box, bg=RAISED)
                    buttons.pack(anchor="w", pady=(S(10), 0))
                    Pill(buttons, "", lambda: self.run(lambda: cast.pause(device), lambda _: None, lambda _: None),
                         kind="ghost", icon="pause", h=36).pack(side="left")
                    Pill(buttons, "", lambda: self.run(lambda: cast.resume(device), lambda _: None, lambda _: None),
                         kind="ghost", icon="play", h=36).pack(side="left", padx=S(8))
                    Pill(buttons, "Stoppen op tv", lambda: stop_cast(device), kind="danger", icon="close", h=36).pack(side="left")
                section("TV'S IN JE NETWERK")
                if searching:
                    label(body, "Zoeken naar tv's…", 10, MUTED, SIDE).pack(anchor="w")
                elif not devices:
                    label(body, "Geen tv gevonden. Staat je tv aan en zit hij op hetzelfde wifi? Bij een LG-tv: zet in Instellingen › "
                          "Algemeen › Apparaten de optie ‘LG Connect Apps’ (of ‘Scherm delen’) aan.", 10, MUTED, SIDE,
                          wraplength=S(320), justify="left").pack(anchor="w")
                for device in devices or []:
                    line = tk.Frame(body, bg=SIDE, padx=S(10), pady=S(9), cursor="hand2")
                    line.pack(fill="x", pady=1)
                    tk.Label(line, image=ui.pill_photo(icon="tv", kind="ghost", h=34, hover=False, disabled=False),
                             bg=SIDE).pack(side="left")
                    texts = tk.Frame(line, bg=SIDE)
                    texts.pack(side="left", padx=S(10))
                    label(texts, elide(device["name"], 11, S(250), True), 11, TEXT, SIDE, True).pack(anchor="w")
                    if device.get("model"):
                        label(texts, elide(device["model"], 9, S(250)), 9, MUTED, SIDE).pack(anchor="w")
                    ui.bind_hover(line, lambda l=line: ui.set_bg(l, RAISED), lambda l=line: ui.set_bg(l, SIDE))
                    ui.bind_click(line, lambda d=device: start_cast(d))
                if not searching:
                    Pill(body, "Opnieuw zoeken", search, kind="quiet", icon="refresh", h=34, padx=12).pack(anchor="w", pady=(S(6), 0))
                section("APPLE TV")
                label(body, "Open Zono op je iPhone en tik in de speler op het AirPlay-icoon.", 10, SOFT, SIDE,
                      wraplength=S(320), justify="left").pack(anchor="w")
                if self.remote.running:
                    self.share_qr(body, SIDE, 150).pack(anchor="w", pady=(S(10), 0))
                else:
                    Pill(body, "QR-code voor iPhone tonen", lambda: (self.set_sharing(True), render_panel(devices)),
                         kind="ghost", icon="phone", h=38, padx=14).pack(anchor="w", pady=(S(10), 0))

            def search():
                render_panel(searching=True)
                self.run(lambda: cast.discover(), lambda found: render_panel(found),
                         lambda _: render_panel([]))

            def start_cast(device):
                current = self.session
                if not current:
                    return
                title = current["item"].get("title", "Zono")
                self.toast(f"Verbinden met {elide(device['name'], 10, S(240), True)}…", "cast")

                def done(_):
                    self.casting = {"device": device, "title": title}
                    if self.engine and current.get("state") == 3:
                        self.toggle_pause()
                    self.toast(f"Speelt af op {elide(device['name'], 10, S(260), True)}", "cast")
                    render_panel(state.get("devices"))

                def failed(error):
                    self.toast("De tv weigerde deze stream. Probeer een andere zender of film.", "close")
                self.run(lambda: cast.play(device, current["url"], title), done, failed)

            def stop_cast(device):
                self.casting = None
                self.run(lambda: cast.stop(device), lambda _: None, lambda _: None)
                render_panel(state.get("devices"))
                self.toast("Casten gestopt", "cast")

            original_render = render_panel

            def render_panel(devices=None, searching=False):
                if devices is not None:
                    state["devices"] = devices
                original_render(devices if devices is not None else state.get("devices"), searching)
            search()

        def toggle_tracks():
            if state.get("panel") == "tracks":
                close_panel()
                return
            close_panel()
            panel = floating_panel(360)
            state["guide"], state["panel"] = panel, "tracks"
            self.queue_place()
            top = tk.Frame(panel, bg=SIDE)
            top.pack(fill="x")
            label(top, "Ondertitels en audio", 14, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", close_panel, kind="ghost", icon="close", h=32).pack(side="right")
            scroller = tk.Canvas(panel, bg=SIDE, highlightthickness=0, bd=0, yscrollincrement=S(12))
            scroller.pack(fill="both", expand=True, pady=(S(12), 0))
            body = tk.Frame(scroller, bg=SIDE)
            body_id = scroller.create_window(0, 0, window=body, anchor="nw")
            body.bind("<Configure>", lambda _: scroller.configure(scrollregion=(0, 0, body.winfo_reqwidth(), body.winfo_reqheight())))
            scroller.bind("<Configure>", lambda e: scroller.itemconfigure(body_id, width=e.width))
            self.panel_scroller = scroller
            note = {"text": ""}

            def choose(kind, track_id):
                engine = self.engine
                if not engine:
                    return
                engine.set_track(kind, track_id)

                def check():
                    if body.winfo_exists() and engine is self.engine:
                        note["text"] = "" if engine.current_track(kind) == track_id else \
                            "Dit spoor kon niet worden ingeschakeld. Probeer een ander spoor."
                        fill(99)
                body.after(400, check)

            def load_file():
                engine = self.engine
                if not engine:
                    return
                chosen = filedialog.askopenfilename(parent=self.root, title="Ondertitelbestand kiezen",
                                                    filetypes=[("Ondertitels", "*.srt *.ass *.ssa *.vtt *.sub"),
                                                               ("Alle bestanden", "*.*")])
                if not chosen:
                    return
                if engine.add_subtitle(chosen):
                    note["text"] = ""
                    self.toast("Ondertitels geladen", "cc")
                    body.after(800, lambda: fill(99))
                else:
                    note["text"] = "Dit bestand kon niet als ondertitel worden geladen."
                    fill(99)

            def fill(attempt=0):
                if not body.winfo_exists():
                    return
                for child in body.winfo_children():
                    child.destroy()
                engine = self.engine
                found = False
                if note["text"]:
                    label(body, note["text"], 10, "#ff8a95", SIDE, wraplength=S(300), justify="left").pack(anchor="w", pady=(0, S(6)))
                for kind, heading in (("audio", "AUDIO"), ("subtitles", "ONDERTITELS")):
                    tracks = engine.tracks(kind) if engine else []
                    if not tracks:
                        continue
                    found = True
                    current = engine.current_track(kind)
                    label(body, heading, 8, DIM, SIDE, True).pack(anchor="w", pady=(S(10), S(4)))
                    for track_id, name in tracks:
                        name = "Uit" if name.casefold() in ("disable", "disabled") else name
                        active = track_id == current
                        line = tk.Frame(body, bg=RAISED if active else SIDE, padx=S(10), pady=S(8), cursor="hand2")
                        line.pack(fill="x", pady=1)
                        label(line, "✓" if active else "", 10, ACCENT_SOFT, line.cget("bg"), True, width=2).pack(side="left")
                        label(line, elide(name, 10, S(260), active), 10, TEXT if active else SOFT,
                              line.cget("bg"), active).pack(side="left")
                        ui.bind_hover(line, lambda l=line, a=active: ui.set_bg(l, RAISED if a else "#1c1c24"),
                                      lambda l=line, a=active: ui.set_bg(l, RAISED if a else SIDE))
                        ui.bind_click(line, lambda k=kind, t=track_id: choose(k, t))
                waiting = attempt < 12
                if not found:
                    label(body, "Sporen laden…" if waiting else "Deze stream heeft geen extra audio of ingebouwde ondertitels.",
                          10, MUTED, SIDE, wraplength=S(300), justify="left").pack(anchor="w")
                session = self.session
                if session and not session["live"]:
                    label(body, "EIGEN ONDERTITELS", 8, DIM, SIDE, True).pack(anchor="w", pady=(S(18), S(4)))
                    label(body, "Heb je een .srt-bestand voor deze film of aflevering? Laad het hier.", 9, MUTED, SIDE,
                          wraplength=S(300), justify="left").pack(anchor="w", pady=(0, S(8)))
                    Pill(body, "Ondertitelbestand openen", load_file, kind="ghost", icon="cc", h=36, padx=12).pack(anchor="w")
                scroller.yview_moveto(0) if attempt == 0 else None
                if not found and waiting:
                    body.after(1000, lambda: fill(attempt + 1))
            fill()

        def toggle_replay():
            if state.get("panel") == "replay":
                close_panel()
                return
            close_panel()
            panel = floating_panel(380)
            state["guide"], state["panel"] = panel, "replay"
            self.queue_place()
            top = tk.Frame(panel, bg=SIDE)
            top.pack(fill="x")
            label(top, "Terugkijken", 14, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", close_panel, kind="ghost", icon="close", h=32).pack(side="right")
            label(panel, elide(item["title"], 10, S(300)), 10, MUTED, SIDE).pack(anchor="w", pady=(S(2), S(10)))
            holder = tk.Frame(panel, bg=SIDE)
            holder.pack(fill="both", expand=True)
            listing = tk.Canvas(holder, bg=SIDE, highlightthickness=0)
            scroll = ttk.Scrollbar(holder, orient="vertical", command=listing.yview, style="Zono.Vertical.TScrollbar")
            scroll.pack(side="right", fill="y")
            listing.pack(side="left", fill="both", expand=True)
            listing.configure(yscrollcommand=scroll.set)
            rows = tk.Frame(listing, bg=SIDE)
            listing.create_window(0, 0, window=rows, anchor="nw", width=S(320))
            rows.bind("<Configure>", lambda _: listing.configure(scrollregion=listing.bbox("all")))
            listing.bind("<MouseWheel>", lambda e: listing.yview_scroll(-int(e.delta / 120) * 2, "units"))
            label(rows, "Programma’s laden…", 10, MUTED, SIDE).pack(anchor="w")

            def fill(entries):
                if not rows.winfo_exists():
                    return
                for child in rows.winfo_children():
                    child.destroy()
                past = [e for e in entries if self.archivable(item, e)]
                past.sort(key=lambda e: -e["start"])
                today = datetime.now().date()
                heading = None
                for entry in past[:80]:
                    day = datetime.fromtimestamp(entry["start"]).date()
                    name = "Vandaag" if day == today else "Gisteren" if (today - day).days == 1 else day.strftime("%d/%m")
                    if name != heading:
                        heading = name
                        label(rows, name.upper(), 8, DIM, SIDE, True).pack(anchor="w", pady=(S(10), S(4)))
                    line = tk.Frame(rows, bg=SIDE, padx=S(10), pady=S(8), cursor="hand2")
                    line.pack(fill="x", pady=1)
                    label(line, hhmm(entry["start"]), 10, ACCENT_SOFT, SIDE, True, width=6, anchor="w").pack(side="left", anchor="n")
                    label(line, elide(entry["title"] or "Programma", 10, S(220)), 10, TEXT, SIDE).pack(side="left", anchor="n")
                    ui.bind_hover(line, lambda l=line: ui.set_bg(l, RAISED), lambda l=line: ui.set_bg(l, SIDE))
                    ui.bind_click(line, lambda e=entry: self.play_catchup(item, e))
                    for widget in (line, *line.winfo_children()):
                        widget.bind("<MouseWheel>", lambda e: listing.yview_scroll(-int(e.delta / 120) * 2, "units"))
                if not past:
                    label(rows, "Er zijn (nog) geen programma’s om terug te kijken.", 10, MUTED, SIDE,
                          wraplength=S(300), justify="left").pack(anchor="w")

            def failed(error):
                if rows.winfo_exists():
                    for child in rows.winfo_children():
                        child.destroy()
                    label(rows, error_text(error), 10, MUTED, SIDE, wraplength=S(300), justify="left").pack(anchor="w")
            self.fetch_guide(item, fill, failed, full=True)

        def toggle_guide():
            if state.get("panel") == "guide":
                close_panel()
                return
            close_panel()
            panel = floating_panel(360)
            state["guide"], state["panel"] = panel, "guide"
            self.queue_place()
            top = tk.Frame(panel, bg=SIDE)
            top.pack(fill="x")
            label(top, "TV-gids", 14, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", close_panel, kind="ghost", icon="close", h=32).pack(side="right")
            label(panel, elide(item["title"], 10, S(300)), 10, MUTED, SIDE).pack(anchor="w", pady=(S(2), S(12)))
            rows = tk.Frame(panel, bg=SIDE)
            rows.pack(fill="both", expand=True)
            label(rows, "Programma’s laden…", 10, MUTED, SIDE).pack(anchor="w")

            def fill(entries):
                if not rows.winfo_exists():
                    return
                for child in rows.winfo_children():
                    child.destroy()
                moment = time()
                upcoming = [e for e in entries if not e["end"] or e["end"] > moment][:12]
                for entry in upcoming:
                    active = entry["start"] <= moment < entry["end"]
                    line = tk.Frame(rows, bg=RAISED if active else SIDE, padx=S(10), pady=S(8))
                    line.pack(fill="x", pady=1)
                    label(line, hhmm(entry["start"]) or "--:--", 10, ACCENT_SOFT if active else MUTED,
                          line.cget("bg"), active, width=6, anchor="w").pack(side="left", anchor="n")
                    label(line, elide(entry["title"] or "Programma", 10, S(230), active), 10,
                          TEXT if active else SOFT, line.cget("bg"), active).pack(side="left", anchor="n")
                if not upcoming:
                    label(rows, "Geen gidsgegevens van deze provider.", 10, MUTED, SIDE).pack(anchor="w")

            def failed(error):
                if rows.winfo_exists():
                    for child in rows.winfo_children():
                        child.destroy()
                    label(rows, error_text(error), 10, MUTED, SIDE, wraplength=S(300), justify="left").pack(anchor="w")
            self.fetch_guide(item, fill, failed)

        # Netflix-style: a thin full-width time bar, below it plain white icons, the title in the middle
        black = "#000000"
        track = tk.Frame(controls, bg=black)
        track.pack(fill="x")
        buttons = tk.Frame(controls, bg=black)
        buttons.pack(fill="x", pady=(S(2), 0))
        left = tk.Frame(buttons, bg=black)
        left.pack(side="left")
        right = tk.Frame(buttons, bg=black)
        right.pack(side="right")
        middle = tk.Frame(buttons, bg=black)
        middle.pack(side="left", fill="x", expand=True)
        bare = dict(kind="bare", h=48, bg=black)

        play = Pill(left, "", self.toggle_pause, icon="pause", **bare)
        play.pack(side="left")
        buffered = live and bool(session.get("buffer"))
        if live:
            back = (lambda: (self.jump(-30), show_controls())) if buffered else (lambda: self.explain_rewind(session))
            ahead = (lambda: (self.jump(30), show_controls())) if buffered else (lambda: self.explain_rewind(session))
            Pill(left, "", back, icon="skip_back", **bare).pack(side="left", padx=(S(8), 0))
            Pill(left, "", ahead, icon="skip_fwd", **bare).pack(side="left", padx=(S(4), 0))
        else:
            Pill(left, "", lambda: (self.jump(-10), show_controls()), icon="skip_back", **bare).pack(side="left", padx=(S(8), 0))
            Pill(left, "", lambda: (self.jump(10), show_controls()), icon="skip_fwd", **bare).pack(side="left", padx=(S(4), 0))

        def set_volume(value):
            self.set_volume(value)
            mute.update_pill(icon="volume")

        def toggle_mute():
            self.toggle_mute()
            mute.update_pill(icon="mute" if self.muted else "volume")
            show_controls()
        mute = Pill(left, "", toggle_mute, icon="mute" if self.muted else "volume", **bare)
        mute.pack(side="left", padx=(S(8), 0))
        volume = Slider(left, 96, self.volume, 100, command=set_volume, bg=black, fill="#e8e8ee", track="#3a3a42")
        volume.pack(side="left", padx=(0, S(10)))

        # title in the middle: "Serie  S1:E3  Titel" / "LIVE  1  Zender"
        heading = tk.Frame(middle, bg=black)
        heading.pack(anchor="center", pady=(S(12), 0))
        if live:
            Pill(heading, "LIVE", None, kind="live", h=22, px=9.5, radius=5, weight="bold", bg=black).pack(side="left", padx=(0, S(10)))
            if session["position"] >= 0:
                label(heading, str(session["position"] + 1), 12, MUTED, black, True).pack(side="left", padx=(0, S(8)))
            label(heading, elide(item["title"], 12, S(420), True), 12, TEXT, black, True).pack(side="left")
        elif item.get("series"):
            label(heading, elide(str(item["series"]), 12, S(300), True), 12, TEXT, black, True).pack(side="left")
            if session["position"] >= 0 and item.get("group"):
                season = re.sub(r"\D", "", str(item["group"])) or "1"
                number_in = sum(1 for e in session["playlist"][:session["position"] + 1] if e.get("group") == item.get("group"))
                label(heading, f"S{season}:A{number_in}", 12, MUTED, black, True).pack(side="left", padx=(S(10), S(8)))
            label(heading, elide(str(item["title"]), 12, S(320)), 12, SOFT, black).pack(side="left", padx=(S(4), 0))
        elif item.get("kind") == "catchup":
            Pill(heading, "TERUGKIJKEN", None, kind="accent", h=22, px=9.5, radius=5, weight="bold", bg=black).pack(side="left", padx=(0, S(10)))
            label(heading, elide(item["title"], 12, S(380), True), 12, TEXT, black, True).pack(side="left")
            label(heading, f"   {item.get('channel', '')}  ·  {item.get('when', '')}", 10, MUTED, black).pack(side="left")
        else:
            label(heading, elide(item["title"], 12, S(520), True), 12, TEXT, black, True).pack(side="left")

        # the time bar
        elapsed = label(track, "LIVE" if live else "", 9, SOFT, black, width=7)
        seek = total = live_button = None
        if buffered:
            def seek_live(value):
                kept = self.live_buffer()
                self.live_to(max(0, kept - value))
            elapsed.pack(side="left")
            seek = Slider(track, 300, 1, 1, release=seek_live, bg=black, fill=ACCENT, thumb=ACCENT, track="#3a3a42")
            seek.pack(side="left", fill="x", expand=True)
            live_button = Pill(track, "LIVE", lambda: (self.live_to(0), show_controls()), kind="live", h=24, px=9,
                               radius=6, weight="bold", bg=black)
            live_button.pack(side="left", padx=(S(8), 0))
        elif not live:
            def seek_to(value):
                if self.engine and self.engine.media_player_get_length(self.engine.player) > 0:
                    self.engine.media_player_set_time(self.engine.player, int(value))
            seek = Slider(track, 300, 0, 1, release=seek_to, bg=black, fill=ACCENT, thumb=ACCENT, track="#3a3a42")
            seek.pack(side="left", fill="x", expand=True)
            total = label(track, "", 10, SOFT, black, width=7)
            total.pack(side="left", padx=(S(8), 0))

        # right: what you need while watching
        Pill(right, "", lambda: set_full(not state["full"]), icon="expand", **bare).pack(side="right", padx=(S(6), 0))
        if not live and self.engine and getattr(self.engine, "extras", {}).get("media_player_set_rate"):
            Pill(right, "", lambda: speed_menu(), icon="speed", **bare).pack(side="right", padx=(S(6), 0))
        Pill(right, "", toggle_tracks, icon="cc", **bare).pack(side="right", padx=(S(6), 0))
        if not live and item.get("series") and len(session["playlist"]) > 1:
            Pill(right, "", lambda: toggle_episodes(), icon="series", **bare).pack(side="right", padx=(S(6), 0))
        if session["next"] and not live:
            Pill(right, "", lambda: switch_to(session["next"]), icon="next", **bare).pack(side="right", padx=(S(6), 0))
        Pill(right, "", toggle_cast, icon="cast", **bare).pack(side="right", padx=(S(6), 0))
        Pill(right, "", lambda: self.open_pip(), icon="pip", **bare).pack(side="right", padx=(S(6), 0))
        favorite = Pill(right, "", lambda: favorite.update_pill(icon="heart_fill" if self.toggle(item) else "heart"),
                        icon="heart_fill" if item["id"] in self.favorites else "heart", **bare)
        favorite.pack(side="right", padx=(S(6), 0))
        rec_button = None
        if live and item.get("url"):
            def record_click():
                entry = self.active_recording(item["id"])
                if entry:
                    self.cancel_recording(entry)
                    return
                record_menu()
            rec_button = Pill(right, "R", record_click, kind="rec", h=40, width=40, weight="bold", bg=black)
            rec_button.pack(side="right", padx=(S(6), S(4)))
        if live and len(session["playlist"]) > 1:
            Pill(right, "", lambda: self.open_multiview(item), icon="grid", **bare).pack(side="right", padx=(S(6), 0))
        if live and item.get("archive") and item.get("sid") and self.source:
            Pill(right, "", toggle_replay, icon="refresh", **bare).pack(side="right", padx=(S(6), 0))
        if live and item.get("sid") and self.source:
            Pill(right, "", toggle_guide, icon="guide", **bare).pack(side="right", padx=(S(6), 0))

        def speed_menu():
            if state.get("card") is not None and state["card"].winfo_exists():
                state["card"].shell.destroy()
            card = floating_panel(0, corner="card", alpha=0.96)
            card.kind = "speed"
            state["card"] = card
            card.configure(padx=S(16), pady=S(14))
            label(card, "AFSPEELSNELHEID", 8, ACCENT_SOFT, SIDE, True).pack(anchor="w", pady=(0, S(8)))
            row = tk.Frame(card, bg=SIDE)
            row.pack()
            for rate in (0.5, 0.75, 1.0, 1.25, 1.5):
                text = ("Normaal" if rate == 1 else f"{rate:g}×".replace(".", ","))
                Pill(row, text, lambda r=rate: (self.engine.set_rate(r), session.update(rate=r), card.shell.destroy(),
                                                state.update(card=None)),
                     kind="chip_on" if session.get("rate", 1.0) == rate else "chip", h=34, px=11.5, bg=SIDE).pack(side="left", padx=(0, S(6)))

        def toggle_episodes():
            if state.get("panel") == "episodes":
                close_panel()
                return
            close_panel()
            panel = floating_panel(380)
            state["guide"], state["panel"] = panel, "episodes"
            top = tk.Frame(panel, bg=SIDE)
            top.pack(fill="x")
            label(top, elide(str(item.get("series", "Afleveringen")), 14, S(280), True), 14, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", close_panel, kind="ghost", icon="close", h=32).pack(side="right")
            scroller = tk.Canvas(panel, bg=SIDE, highlightthickness=0, bd=0, yscrollincrement=S(12))
            scroller.pack(fill="both", expand=True, pady=(S(12), 0))
            body = tk.Frame(scroller, bg=SIDE)
            body_id = scroller.create_window(0, 0, window=body, anchor="nw")
            body.bind("<Configure>", lambda _: scroller.configure(scrollregion=(0, 0, body.winfo_reqwidth(), body.winfo_reqheight())))
            scroller.bind("<Configure>", lambda e: scroller.itemconfigure(body_id, width=e.width))
            self.panel_scroller = scroller
            group, current_row = None, None
            for entry in session["playlist"]:
                if entry.get("group") != group:
                    group = entry.get("group")
                    label(body, str(group or "").upper(), 8, DIM, SIDE, True).pack(anchor="w", pady=(S(10), S(4)))
                on = entry.get("id") == item.get("id")
                seen = entry.get("id") in self.watched
                line = tk.Frame(body, bg=RAISED if on else SIDE, padx=S(10), pady=S(8), cursor="hand2")
                line.pack(fill="x", pady=1)
                label(line, "▶" if on else ("✓" if seen else ""), 10, ACCENT_SOFT, line.cget("bg"), True, width=2).pack(side="left")
                label(line, elide(str(entry.get("title", "")), 10, S(260), on), 10, TEXT if on else (MUTED if seen else SOFT),
                      line.cget("bg"), on).pack(side="left")
                if not on:
                    ui.bind_hover(line, lambda l=line: ui.set_bg(l, "#1c1c24"), lambda l=line: ui.set_bg(l, SIDE))
                    ui.bind_click(line, lambda e=entry: (close_panel(), switch_to(e)))
                else:
                    current_row = line
            if current_row is not None:
                panel.after(200, lambda: scroller.winfo_exists() and scroller.yview_moveto(
                    max(0, current_row.winfo_y() - S(80)) / max(1, body.winfo_height())))

        def nudge_volume(delta):
            value = max(0, min(100, self.volume + delta))
            volume.set(value)
            set_volume(value)
            show_controls()

        rec_label = label(header, "", 11, "#ff5a6b", BG, True)

        def record_menu():
            if state.get("card") is not None and state["card"].winfo_exists():
                state["card"].shell.destroy()
            card = floating_panel(0, corner="card", alpha=0.96)
            card.kind = "record"
            state["card"] = card
            card.configure(padx=S(18), pady=S(16))
            label(card, "OPNEMEN", 8, "#ff5a6b", SIDE, True).pack(anchor="w")
            label(card, elide(str(item.get("title", "")), 13, S(320), True), 13, TEXT, SIDE, True).pack(anchor="w", pady=(S(2), S(10)))
            cached = self.guide_cache.get(item.get("sid"))
            program = current_program(cached[1]) if cached else None

            def go(end, title=None):
                card.shell.destroy()
                state["card"] = None
                self.record_now(item, end, title)
            now = time()
            if program and program.get("end", 0) > now + 60:
                Pill(card, f"Dit programma  ·  tot {hhmm(program['end'])}",
                     lambda: go(program["end"] + 120, program.get("title")), kind="primary", icon="record", h=40,
                     padx=16).pack(fill="x", pady=(0, S(6)))
            for minutes, text in ((30, "30 minuten"), (60, "1 uur"), (120, "2 uur")):
                Pill(card, text, lambda m=minutes: go(now + m * 60), kind="ghost", icon="clock", h=38, padx=14).pack(
                    fill="x", pady=(0, S(6)))
            Pill(card, "Annuleren", lambda: (card.shell.destroy(), state.update(card=None)), kind="quiet", h=36).pack(fill="x")

        def show_card(current):
            """Netflix-style helpers: "Intro overslaan" early in an episode, "Volgende aflevering" near the end."""
            wanted = None
            if current.get("next") and (current.get("count_until") or current.get("upnext_show")):
                wanted = "next"
            elif not live and current.get("intro") and self.engine:
                moment = self.engine.media_player_get_time(self.engine.player) / 1000
                if 5 <= moment <= 240 and not current.get("intro_done"):
                    wanted = "intro"
            card = state.get("card")
            if card is not None and card.winfo_exists() and card.kind in ("record", "speed"):
                return
            if card is not None and (not card.winfo_exists() or card.kind != wanted):
                if card.winfo_exists():
                    card.shell.destroy()
                state["card"] = card = None
            if wanted and card is None:
                card = floating_panel(0, corner="card", alpha=0.94)
                card.kind = wanted
                card.configure(padx=S(18), pady=S(16))
                if wanted == "intro":
                    def skip_intro():
                        current["intro_done"] = True
                        self.jump(85)
                        show_controls()
                    card.configure(padx=S(4), pady=S(4))
                    Pill(card, "Intro overslaan", skip_intro, kind="primary", icon="skip_fwd", h=46, padx=22, radius=8).pack()
                else:
                    following = current["next"]
                    label(card, "VOLGENDE AFLEVERING", 8, ACCENT_SOFT, SIDE, True).pack(anchor="w")
                    label(card, elide(str(following.get("title", "")), 13, S(320), True), 13, TEXT, SIDE, True).pack(
                        anchor="w", pady=(S(2), S(2)))
                    card.counter = label(card, "", 10, MUTED, SIDE)
                    card.counter.pack(anchor="w")
                    buttons = tk.Frame(card, bg=SIDE)
                    buttons.pack(anchor="w", pady=(S(12), 0))

                    def now():
                        current["count_until"] = monotonic()
                    def cancel():
                        current["count_until"] = None
                        current["upnext_dismissed"] = True
                        current["upnext_show"] = False
                    Pill(buttons, "Nu afspelen", now, kind="primary", icon="play", h=40, padx=16).pack(side="left")
                    Pill(buttons, "Annuleren", cancel, kind="ghost", h=40, padx=16).pack(side="left", padx=(S(8), 0))
                state["card"] = card
            if card is not None and wanted == "next":
                if current.get("count_until"):
                    left = max(0, int(current["count_until"] - monotonic()) + 1)
                    card.counter.configure(text=f"Begint over {left} seconde{'n' if left != 1 else ''}")
                else:
                    card.counter.configure(text="Begint automatisch na de aftiteling" if self.preferences.get("autonext", True)
                                           else "Klik om meteen verder te kijken")

        def update(current):
            if not window.winfo_exists() or current is not session:
                return window.winfo_exists()
            icon = "pause" if current.get("view_state", current.get("state")) == 3 else "play"
            if play.opts["icon"] != icon:
                play.update_pill(icon=icon)
            show_card(current)
            if rec_button is not None:
                entry = self.active_recording(item["id"])
                if entry:
                    took = int(time() - entry["start"])
                    text = f"●  REC  {took // 60}:{took % 60:02d}"
                    if rec_label.cget("text")[:1] != "●" or not rec_label.winfo_ismapped():
                        rec_label.pack(side="right", padx=S(12))
                    rec_label.configure(text=text)
                    if rec_button.opts["text"] != "■":
                        rec_button.update_pill(text="■")
                elif rec_label.winfo_ismapped():
                    rec_label.pack_forget()
                    rec_button.update_pill(text="R")
                elif rec_button.opts["text"] != "R":
                    rec_button.update_pill(text="R")
            if buffered:
                kept = self.live_buffer()
                behind = self.live_offset()
                seek.set(max(0, kept - behind), max(kept, 1))
                elapsed.configure(text="LIVE" if behind < 5 else "−" + clock(behind))
                wanted = "live" if behind < 5 else "ghost"
                if live_button.opts["kind"] != wanted:
                    live_button.update_pill(kind=wanted, text="LIVE" if behind < 5 else "Naar live")
            if current.get("count_until"):
                status.configure(text=f"Volgende aflevering over {max(0, int(current['count_until'] - monotonic()) + 1)} s")
            elif current.get("failed"):
                status.configure(text="Deze stream kan niet worden afgespeeld. Probeer een andere titel.")
            elif current.get("state") in (1, 2):
                status.configure(text="Stream openen…")
            elif current.get("ended"):
                status.configure(text="Afspelen beëindigd.")
            else:
                status.configure(text="")
            if seek is not None and not live and self.engine:
                length = self.engine.media_player_get_length(self.engine.player)
                moment = self.engine.media_player_get_time(self.engine.player)
                if length > 0 and moment >= 0:
                    seek.set(moment, length)
                    total.configure(text=clock(max(0, length - moment) / 1000))
            return True
        self.listeners["full"] = update

        def key(event):
            name = event.keysym.lower()
            char = getattr(event, "char", "")
            if live and char and char.isdigit():
                playlist = session["playlist"]
                self.zap_input(char, playlist, lambda index: switch_to(playlist[index]))
                return "break"
            if name == "escape":
                if state["full"]:
                    set_full(False)
                else:
                    close()
            elif name == "space":
                self.toggle_pause()
                show_controls()
            elif name in ("f", "f11"):
                set_full(not state["full"])
            elif name == "m":
                toggle_mute()
            elif name == "n" and session["next"]:
                switch_to(session["next"])
            elif name == "left" and live and not buffered:
                self.explain_rewind(session)
            elif name == "left" and (not live or buffered):
                self.jump(-10)
                show_controls()
            elif name == "right" and (not live or buffered):
                self.jump(10)
                show_controls()
            elif name == "end" and buffered:
                self.live_to(0)
            elif name in ("up", "prior") and live:
                switch_to(session["previous"])
            elif name in ("down", "next") and live:
                switch_to(session["next"])
            elif name == "up":
                nudge_volume(5)
            elif name == "down":
                nudge_volume(-5)
            elif name == "g" and live and item.get("sid") and self.source:
                toggle_guide()
            elif name == "s":
                toggle_tracks()
            elif name == "c":
                toggle_cast()
            elif name == "p":
                self.root.after(10, self.open_pip)
            elif name == "t" and live and item.get("archive"):
                toggle_replay()
            return "break"
        self.player_keys = key
        for widget in (window, header, controls, self.stage, video):
            widget.bind("<Motion>", show_controls, add="+")

        def close(minimize=True, keep_mode=False):
            close_panel()
            if state.get("card") is not None and state["card"].winfo_exists():
                state["card"].shell.destroy()
                state["card"] = None
            if state["closing"]:
                return
            state["closing"] = True
            if state["hide"]:
                window.after_cancel(state["hide"])
            if state["full"]:
                try:
                    self.root.attributes("-fullscreen", False)
                except tk.TclError:
                    pass
            try:
                self.stage.configure(cursor="hand2")
            except tk.TclError:
                pass
            self.listeners.pop("full", None)
            window.destroy()
            if self.player_view is window:
                self.player_view = self.player_keys = self.player_close = None
                self.player_show = self.player_full_toggle = None
                self.player_full = False
            if keep_mode:
                return
            if minimize and self.session:
                self.set_stage("mini")
                if self.tab == "live" and not self.detail_item:
                    self.render()
        self.player_close = close
        self.player_show = show_controls
        self.player_full_toggle = lambda: set_full(not state["full"])
        self.player_full = False
        self.set_stage("full", video)
        update(session)
        window.focus_set()
        if fullscreen:
            window.after(80, lambda: window.winfo_exists() and set_full(True))

    def open_trailer(self, item):
        """Play the YouTube trailer inside Zono, like Netflix. Falls back to the browser when that cannot work."""
        key = item.get("trailer")
        if not key:
            return
        if self.trailer_view is not None:
            self.close_trailer()
        if self.search_open:
            self.close_search()
        watch = f"https://www.youtube.com/watch?v={key}"
        if not webview.available():
            webbrowser.open(watch)
            self.toast("Trailer geopend in je browser", "trailer")
            return
        paused = False
        if self.engine and self.session and self.session.get("state") == 3 and not self.casting:
            self.toggle_pause()
            paused = True
        view = tk.Frame(self.root, bg="#000000")
        view.place(x=0, y=0, relwidth=1, relheight=1)
        view.lift()
        bar = tk.Frame(view, bg="#000000", height=S(64))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        Pill(bar, "Terug", self.close_trailer, kind="ghost", icon="back", h=40, bg="#000000").pack(side="left", padx=S(20))
        label(bar, elide(f"Trailer  ·  {item.get('title', '')}", 12, S(700), True), 12, TEXT, "#000000", True).pack(side="left")
        frame = tk.Frame(view, bg="#000000")
        frame.pack(fill="both", expand=True)
        loading = label(frame, "Trailer laden…", 11, MUTED, "#000000")
        loading.place(relx=.5, rely=.45, anchor="center")
        page = webview.EmbeddedPage(self.root, frame, data.STATE.parent / "webview")
        self.trailer_view = {"view": view, "page": page, "paused": paused}
        self.queue_place()

        def ready():
            if loading.winfo_exists():
                loading.place_forget()

        def failed(_):
            if self.trailer_view and self.trailer_view["page"] is page:
                self.close_trailer()
                webbrowser.open(watch)
                self.toast("Trailer geopend in je browser", "trailer")

        def start():
            if self.trailer_view and self.trailer_view["page"] is page:
                try:
                    token = uuid4().hex[:12]
                    page.open(webview.page_url(key, token), ready, failed, title=token)
                except Exception as error:
                    failed(error)
        self.root.after(60, start)

    def close_trailer(self):
        trailer, self.trailer_view = self.trailer_view, None
        if not trailer:
            return
        trailer["page"].close()
        try:
            trailer["view"].destroy()
        except tk.TclError:
            pass
        if trailer["paused"] and self.engine and self.session and self.session.get("state") != 3:
            self.toggle_pause()
        self.queue_place()

    # ------------------------------------------------------------ multiview: 2 or 4 channels at once

    def open_multiview(self, first=None):
        channels = self.by_kind.get("live", [])
        if not channels:
            return
        if first is None and self.session and self.session["live"]:
            first = self.session["item"]
        if self.player_close:
            self.player_close(minimize=False)
        self.stop_playback()
        if self.search_open:
            self.close_search()
        view = tk.Frame(self.root, bg="#000000")
        view.place(x=0, y=0, relwidth=1, relheight=1)
        view.lift()
        state = {"view": view, "tiles": [], "layout": 2 if first is None else 2, "audio": 0}
        self.multiview = state
        self.queue_place()
        header = tk.Frame(view, bg=BG, padx=S(18), pady=S(12))
        header.pack(fill="x")
        Pill(header, "", self.close_multiview, kind="ghost", icon="back", h=38).pack(side="left")
        label(header, "Multiview", 14, TEXT, BG, True).pack(side="left", padx=S(12))
        label(header, "Klik op een beeld voor het geluid  ·  dubbelklik om groot te kijken", 10, MUTED, BG).pack(side="left")
        chips = {}
        grid = tk.Frame(view, bg="#000000")
        grid.pack(fill="both", expand=True, padx=S(6), pady=S(6))

        def set_layout(count):
            if count == state["layout"] and state["tiles"]:
                return
            state["layout"] = count
            for value, pill in chips.items():
                pill.update_pill(kind="chip_on" if value == count else "chip")
            build(count)
        for value, text in ((4, "4 zenders"), (2, "2 zenders")):
            chips[value] = Pill(header, text, lambda v=value: set_layout(v), kind="chip", h=34, px=11.5)
            chips[value].pack(side="right", padx=(S(8), 0))
        note = label(view, "Elke zender gebruikt een eigen verbinding met je provider. Start een beeld niet? Dan staat je "
                           "abonnement waarschijnlijk minder verbindingen tegelijk toe.", 9, DIM, "#000000")
        note.pack(side="bottom", pady=(0, S(8)), before=grid)

        def tile_player(tile):
            if tile.get("player") is None:
                tile["video"].update_idletasks()
                tile["player"] = Player(tile["video"].winfo_id())
            return tile["player"]

        def apply_audio():
            for index, tile in enumerate(state["tiles"]):
                on = index == state["audio"]
                tile["frame"].configure(highlightbackground=ACCENT if on else "#1a1a22")
                tile["sound"].configure(text="🔊" if on and tile.get("channel") else "")
                if tile.get("player"):
                    try:
                        tile["player"].audio_set_volume(tile["player"].player, 0 if (not on or self.muted) else self.volume)
                    except Exception:
                        pass

        def play_in(tile, channel):
            tile["channel"] = channel
            close_picker(tile)
            tile["name"].configure(text=elide(str(channel.get("title", "")), 11, S(380), True))
            tile["video"].pack(fill="both", expand=True)
            tile["empty"].pack_forget()
            try:
                tile_player(tile).open(data.check_url(channel["url"]), self.play_options())
            except (OSError, ValueError, AttributeError, KeyError):
                tile["name"].configure(text="Deze zender kan niet starten")
            apply_audio()

        def stop_tile(tile):
            if tile.get("player"):
                try:
                    tile["player"].stop()
                except Exception:
                    pass

        def close_picker(tile):
            if tile.get("picker") is not None and tile["picker"].winfo_exists():
                tile["picker"].destroy()
            tile["picker"] = None

        def pick(tile):
            stop_tile(tile)
            tile["video"].pack_forget()
            tile["empty"].pack_forget()
            close_picker(tile)
            box = tk.Frame(tile["body"], bg=SIDE, padx=S(14), pady=S(12))
            box.pack(fill="both", expand=True)
            tile["picker"] = box
            top = tk.Frame(box, bg=SIDE)
            top.pack(fill="x")
            label(top, "Kies een zender", 12, TEXT, SIDE, True).pack(side="left")
            Pill(top, "", lambda: (close_picker(tile), restore(tile)), kind="ghost", icon="close", h=30).pack(side="right")
            query = tk.StringVar()
            entry = tk.Entry(box, textvariable=query, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                             font=(FONT, 11), highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
            entry.pack(fill="x", pady=(S(10), S(8)), ipady=S(6))
            holder, listing = self.styled_list(box, bg=SIDE)
            holder.pack(fill="both", expand=True)
            shown = []

            def refresh(*_):
                text = query.get().strip().casefold()
                shown[:] = [c for c in channels if text in str(c.get("title", "")).casefold()][:400]
                listing.delete(0, "end")
                for number_, channel in enumerate(shown, 1):
                    listing.insert("end", f"  {channel.get('title', '')}")

            def choose(_=None):
                selection = listing.curselection()
                index = selection[0] if selection else (0 if shown else None)
                if index is not None and index < len(shown):
                    play_in(tile, shown[index])
                return "break"
            query.trace_add("write", refresh)
            listing.bind("<Double-Button-1>", choose)
            listing.bind("<Return>", choose)
            entry.bind("<Return>", choose)
            entry.bind("<Down>", lambda _: (listing.focus_set(), listing.selection_set(0)))
            refresh()
            entry.focus_set()

        def restore(tile):
            if tile.get("channel"):
                play_in(tile, tile["channel"])
            else:
                tile["empty"].pack(expand=True)

        def make_tile(parent, index):
            frame = tk.Frame(parent, bg="#000000", highlightthickness=S(2), highlightbackground="#1a1a22")
            bar = tk.Frame(frame, bg=BG, padx=S(10), pady=S(6))
            bar.pack(fill="x")
            name = label(bar, "Leeg", 11, TEXT, BG, True)
            name.pack(side="left")
            sound = label(bar, "", 10, ACCENT_SOFT, BG)
            sound.pack(side="left", padx=S(8))
            tile = {"frame": frame, "name": name, "sound": sound, "player": None, "channel": None, "picker": None}
            Pill(bar, "", lambda: open_big(tile), kind="quiet", icon="expand", h=28, bg=BG).pack(side="right")
            Pill(bar, "Wissel", lambda: pick(tile), kind="quiet", icon="swap", h=28, bg=BG, padx=10).pack(side="right")
            body = tk.Frame(frame, bg="#000000")
            body.pack(fill="both", expand=True)
            video = tk.Frame(body, bg="#000000", cursor="hand2")
            empty = tk.Frame(body, bg="#000000")
            Pill(empty, "Zender kiezen", lambda: pick(tile), kind="ghost", icon="plus", h=44, padx=18).pack()
            empty.pack(expand=True)
            tile.update(body=body, video=video, empty=empty)

            def focus(_=None):
                state["audio"] = state["tiles"].index(tile)
                apply_audio()
            for widget in (frame, bar, name, video):
                widget.bind("<Button-1>", focus, add="+")
            video.bind("<Double-Button-1>", lambda _: open_big(tile))
            return tile

        def open_big(tile):
            channel = tile.get("channel")
            if channel:
                self.close_multiview()
                self.open_player(channel, channels)

        def build(count):
            previous = [t.get("channel") for t in state["tiles"]]
            for tile in state["tiles"]:
                if tile.get("player"):
                    try:
                        tile["player"].close()
                    except Exception:
                        pass
            for child in grid.winfo_children():
                child.destroy()
            state["tiles"] = []
            columns = 2
            rows = 1 if count == 2 else 2
            for r in range(rows):
                grid.rowconfigure(r, weight=1, uniform="rows")
            for c in range(columns):
                grid.columnconfigure(c, weight=1, uniform="cols")
            for index in range(count):
                tile = make_tile(grid, index)
                tile["frame"].grid(row=index // columns, column=index % columns, sticky="nsew", padx=S(4), pady=S(4))
                state["tiles"].append(tile)
            state["audio"] = min(state["audio"], count - 1)
            self.root.update_idletasks()
            for tile, channel in zip(state["tiles"], previous):
                if channel:
                    play_in(tile, channel)
            apply_audio()
        state["apply_audio"] = apply_audio
        set_layout(2)
        if first is not None:
            play_in(state["tiles"][0], first)

        def keys(event):
            if event.keysym.lower() == "escape":
                self.close_multiview()
                return "break"
            return None
        self.overlay_keys = keys

    def close_multiview(self):
        state, self.multiview = self.multiview, None
        if not state:
            return
        self.overlay_keys = None
        for tile in state["tiles"]:
            if tile.get("player"):
                try:
                    tile["player"].close()
                except Exception:
                    pass
        try:
            state["view"].destroy()
        except tk.TclError:
            pass
        self.queue_place()

    def close(self):
        try:
            (data.ROOT / "running.flag").unlink(missing_ok=True)
        except OSError:
            pass
        self.close_trailer()
        self.close_multiview()
        if self.recorders and not messagebox.askyesno(
                "Zono", "Er loopt een opname. Als je Zono sluit, stopt de opname (wat al is opgenomen blijft bewaard). Toch sluiten?",
                parent=self.root):
            return
        if self.download_jobs:
            if not messagebox.askyesno("Zono", "Er lopen nog downloads. Als je Zono sluit, worden ze gestopt. Toch sluiten?",
                                       parent=self.root):
                return
            for job in self.download_jobs.values():
                job["cancel"].set()
        try:
            self.root.withdraw()  # disappear at once, even if a stream takes a moment to stop
        except tk.TclError:
            pass
        if self.pip_window is not None:
            try:
                self.pip_window.destroy()
            except tk.TclError:
                pass
        if self.session and not self.session["live"]:
            self.remember_progress()
        if self.engine:
            self.engine.close()
            self.engine = None
        self.close_buffer()
        self.session = None
        self.clear_live_buffers()
        for key, recorder in list(self.recorders.items()):
            try:
                recorder.close()
            except Exception:
                pass
            entry = next((r for r in self.recordings if r.get("id") == key), None)
            if entry:
                self.finish_recording(entry, stopped=True)
        try:
            self.remote.stop()
        except OSError:
            pass
        for executor in (self.workers, self.art_workers, self.guide_workers, self.download_workers, self.info_workers):
            executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def configure_scale(root):
    override = os.environ.get("ZONO_SCALE")
    if override:
        scale = float(override)
        root.tk.call("tk", "scaling", scale * 96 / 72)
    else:
        scale = root.winfo_fpixels("1i") / 96
    ui.SCALE = max(1.0, min(3.0, scale))


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", ctypes.c_uint32),
                ("cntThreads", ctypes.c_uint32), ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


def other_zono_processes():
    """Process ids of other running Zono copies (any version), found by the runtime they run from."""
    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.OpenProcess.restype = ctypes.c_void_p
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    found = []
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return found
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = kernel.Process32FirstW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
        while more:
            pid = entry.th32ProcessID
            if entry.szExeFile.lower() in ("pythonw.exe", "python.exe") and pid != os.getpid():
                handle = kernel.OpenProcess(0x1000, False, pid)
                if handle:
                    buffer = ctypes.create_unicode_buffer(1024)
                    size = ctypes.c_uint32(1024)
                    if kernel.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buffer, ctypes.byref(size)):
                        path = Path(buffer.value)
                        if path.parent.name.lower() == "runtime" and "zono" in str(path).lower():
                            found.append(pid)
                    kernel.CloseHandle(ctypes.c_void_p(handle))
            more = kernel.Process32NextW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    finally:
        kernel.CloseHandle(ctypes.c_void_p(snapshot))
    return found


def show_existing_window(pids):
    """Bring a visible Zono window of one of `pids` to the front. Returns False when none is visible."""
    user32 = ctypes.windll.user32
    hits = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):
        owner = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(ctypes.c_void_p(hwnd)) and \
                user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd)) > 0:
            hits.append(hwnd)
            return False
        return True
    user32.EnumWindows(callback_type(visit), None)
    if not hits:
        return False
    user32.ShowWindow(ctypes.c_void_p(hits[0]), 9)  # restore when minimised
    user32.SetForegroundWindow(ctypes.c_void_p(hits[0]))
    return True


def claim_single_instance():
    """Make sure only one Zono runs. An existing window is brought to the front; a copy that is still running
    without a window (left over after closing) is stopped, so Zono simply starts."""
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.OpenProcess.restype = ctypes.c_void_p
    for attempt in range(2):
        mutex = kernel.CreateMutexW(None, False, "Local\\ZonoIPTVDesktop")
        if mutex and kernel.GetLastError() != 183:
            return mutex
        if mutex:
            kernel.CloseHandle(ctypes.c_void_p(mutex))
        others = other_zono_processes()
        if others and show_existing_window(set(others)):
            return None
        if attempt:
            break
        for pid in others:
            handle = kernel.OpenProcess(0x0001 | 0x00100000, False, pid)  # terminate + synchronize
            if handle:
                kernel.TerminateProcess(ctypes.c_void_p(handle), 1)
                kernel.WaitForSingleObject(ctypes.c_void_p(handle), 4000)
                kernel.CloseHandle(ctypes.c_void_p(handle))
        for _ in range(20):  # the mutex disappears once the old copy is gone
            mutex = kernel.CreateMutexW(None, False, "Local\\ZonoIPTVDesktop")
            if mutex and kernel.GetLastError() != 183:
                return mutex
            if mutex:
                kernel.CloseHandle(ctypes.c_void_p(mutex))
            kernel.Sleep(200)
    ctypes.windll.user32.MessageBoxW(None, "Zono draait nog op de achtergrond en kon niet worden gestopt.\n\n"
                                     "Open Taakbeheer (Ctrl+Shift+Esc), beëindig ‘pythonw’ of ‘Zono’ en probeer "
                                     "opnieuw, of start je pc opnieuw op.", "Zono", 0x40)
    return None


def size_window(root):
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{min(S(1360), int(screen_w * .92))}x{min(S(860), int(screen_h * .88))}")
    root.minsize(min(S(1000), int(screen_w * .8)), min(S(640), int(screen_h * .7)))


def splash(root):
    """The logo, right away: building the app and reading a big library can take a second or two."""
    cover = tk.Frame(root, bg=BG)
    cover.place(x=0, y=0, relwidth=1, relheight=1)
    try:
        words = ImageTk.PhotoImage(ui.render_logo(64))
        name = tk.Label(cover, image=words, bg=BG)
        name.image = words
        name.place(relx=.5, rely=.46, anchor="center")
    except Exception:
        pass
    note = tk.Label(cover, text="Laden…", bg=BG, fg=MUTED, font=(FONT, 10))
    note.place(relx=.5, rely=.46, y=S(70), anchor="center")
    root.update()
    return cover


def main():
    mutex = claim_single_instance()
    if not mutex:
        return
    try:
        data.ROOT.mkdir(parents=True, exist_ok=True)
        (data.ROOT / "start.log").write_text(f"Zono {VERSION} start {datetime.now():%Y-%m-%d %H:%M:%S}\n", encoding="utf-8")
    except OSError:
        pass
    flag = data.ROOT / "running.flag"
    global SAFE_MODE
    SAFE_MODE = flag.exists()  # the last start never reached a normal close: freeze, crash or power cut
    try:
        data.ROOT.mkdir(parents=True, exist_ok=True)
        flag.write_text(datetime.now().isoformat(), encoding="utf-8")
    except OSError:
        pass
    enable_dpi_awareness()
    root = tk.Tk()
    root.configure(bg=BG)
    configure_scale(root)
    icon = Path(__file__).with_name("Zono.ico")
    if icon.exists():
        root.iconbitmap(str(icon))
    root.title("Zono")
    size_window(root)
    cover = splash(root)
    trace("startscherm getoond")
    Zono(root, data.load_profiles())
    cover.lift()
    root.after(250, cover.destroy)
    root.mainloop()
    # Never linger without a window: background work (a stuck download, a stream to the phone) must not keep an
    # invisible Zono alive that blocks the next start.
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        data.log_error(f"{datetime.now():%Y-%m-%d %H:%M:%S}  Zono {VERSION} kon niet starten\n{traceback.format_exc()}")
        ctypes.windll.user32.MessageBoxW(None, f"Zono kon niet starten ({type(error).__name__}). Details staan in "
                                         f"{data.LOG}.", "Zono", 0x10)
