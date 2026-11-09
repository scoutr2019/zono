"""Starts the real Zono window with a fake video engine and a fake provider, walks through every screen and
fails when anything lands in the error log. Needs a display (on Linux: run under xvfb-run)."""
import json
import os
import time
import unittest

import tests as helpers
from tests import fakes

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")


def go_offline():
    """Every network request must fail fast: send all traffic to a closed local port. Returns the old settings."""
    import urllib.request
    saved = {key: os.environ.get(key) for key in PROXY_KEYS}
    for key in PROXY_KEYS[:4]:
        os.environ[key] = "http://127.0.0.1:9"
    for key in PROXY_KEYS[4:]:
        os.environ.pop(key, None)
    urllib.request._opener = None  # urlopen() remembers the proxy settings of its first call
    return saved


def restore(saved):
    import urllib.request
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    urllib.request._opener = None

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    DISPLAY = True
except Exception:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, "no display (run under xvfb-run on Linux)")
class Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_proxies = go_offline()
        folder = helpers.TEMP / "Zono"
        folder.mkdir(parents=True, exist_ok=True)
        items = fakes.library()
        (folder / "profiles.json").write_text(json.dumps(
            {"profiles": [{"id": "main", "name": "Test", "color": 0, "folder": "", "kids": False}], "last": "main"}))
        (folder / "library.json").write_text(json.dumps(
            {"revision": "t", "library": items, "source": fakes.SOURCE, "favorites": {items[0]["id"]: items[0]},
             "progress": {items[500]["id"]: {"item": items[500], "time": 1800, "duration": 5400, "updated": 1}}}))
        import catalogue as data
        import app
        data.details = fakes.details
        data.guide = data.full_guide = fakes.guide
        data.episodes = lambda source, sid: fakes.details(source, {"id": sid, "kind": "series"})[1]
        app.Player = fakes.FakePlayer
        app.webview.available = lambda: False
        cls.data, cls.app = data, app
        helpers.fresh_ui()
        cls.root = tk.Tk()
        app.configure_scale(cls.root)
        cls.root.geometry("1360x860+0+0")
        cls.zono = app.Zono(cls.root, data.load_profiles())
        cls.pump(1.0)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.zono.stop_playback()
        except Exception:
            pass
        cls.root.destroy()
        restore(cls.saved_proxies)

    @classmethod
    def pump(cls, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            cls.root.update()
            time.sleep(0.01)

    def assert_clean(self, step):
        log = self.data.LOG
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        # notices ("Melding: ...", e.g. the guide could not be fetched offline) are fine; errors are not
        errors = "\n\n".join(b for b in text.split("\n\n") if b.strip() and "Melding:" not in b)
        self.assertEqual(errors, "", f"error after: {step}\n{text}")

    def test_1_every_page(self):
        for tab in ("home", "live", "guide", "movie", "series", "favorites", "downloads", "settings", "home"):
            self.zono.select(tab)
            self.pump(0.6)
            self.assert_clean(f"page {tab}")

    def test_2_details(self):
        z = self.zono
        z.show_detail(z.by_kind["movie"][0])
        self.pump(0.8)
        z.show_detail(z.by_kind["series"][0])
        self.pump(0.8)
        z.back()
        self.pump(0.4)
        self.assert_clean("details")

    def test_3_search(self):
        z = self.zono
        z.open_search()
        self.pump(0.3)
        for letter in "film 12":
            z.search_var.set(z.search_var.get() + letter)
            self.pump(0.2)
        z.show_search_page()
        self.pump(0.6)
        z.close_search()
        self.assert_clean("search")

    def test_4_play_episode_and_player(self):
        z = self.zono
        _, episodes = fakes.details(None, {"id": "s0", "kind": "series"})
        self.assertTrue(z.play(episodes[0], episodes), "the episode should start")
        self.assertIsNotNone(z.session)
        z.expand_player()
        self.pump(2.5)  # several player clock ticks: progress, up-next and intro cards
        z.stop_playback()
        self.pump(0.5)
        self.assert_clean("player")

    def test_4b_escape_from_full_screen_after_controls_hid(self):
        """Bug from a user (2.2.1): Esc in full screen, after the controls had hidden themselves, crashed with
        'window isn't packed'."""
        z = self.zono
        _, episodes = fakes.details(None, {"id": "s0", "kind": "series"})
        z.play(episodes[0], episodes)
        z.expand_player(fullscreen=True)
        self.pump(3.2)  # the controls hide after 2.6 s in full screen
        z.player_keys(type("Event", (), {"keysym": "Escape", "char": "", "widget": self.root, "state": 0})())
        self.pump(0.5)
        z.stop_playback()
        self.pump(0.3)
        self.assert_clean("escape from full screen")

    def test_5_live_channel(self):
        z = self.zono
        z.select("live")
        self.pump(0.5)
        z.live_jump(3)
        self.pump(1.5)
        self.assertTrue(z.session and z.session["live"], "the channel should play")
        z.live_nav(1)
        self.pump(1.0)
        z.stop_playback()
        self.pump(0.3)
        self.assert_clean("live tv")

    def test_6_sheets(self):
        z = self.zono
        z.select("home")
        self.pump(0.4)
        z.edit_home()
        self.pump(0.5)
        z.edit_countries()
        self.pump(0.5)
        z.show_log()
        self.pump(0.5)
        self.assert_clean("sheets")

    def test_7_scrolling(self):
        z = self.zono
        z.select("movie")
        self.pump(0.4)
        for _ in range(6):
            z.smooth_scroll(self.app.S(400))
            self.pump(0.25)
        self.assert_clean("scrolling")

    def test_9_errors_are_caught(self):
        """The check itself works: an error inside a Tk callback is written to the log."""
        self.root.after(1, lambda: 1 / 0)
        self.pump(0.3)
        log = self.data.LOG
        self.assertIn("ZeroDivisionError", log.read_text(encoding="utf-8") if log.exists() else "")
        log.unlink()

    def test_8_timers_stay_bounded(self):
        """A runaway timer once froze PCs: the number of pending Tk callbacks must stay small while idle."""
        self.zono.select("home")
        self.pump(3)
        before = len(self.root.tk.call("after", "info"))
        self.pump(4)
        after = len(self.root.tk.call("after", "info"))
        self.assertLess(after, 60)
        self.assertLessEqual(after, before + 10)


if __name__ == "__main__":
    unittest.main()
