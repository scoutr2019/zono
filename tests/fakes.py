"""Stand-ins for the parts the UI tests cannot use: the VLC engine and the IPTV provider."""
import random
import time


class FakePlayer:
    """Behaves like player.Player while a 112-minute film plays at 44 minutes."""
    extras = {"media_player_set_rate": 1}

    def __init__(self, hwnd):
        self.player = 1
        self.track = 3

    def open(self, url, options=()):
        pass

    def close(self):
        pass

    def stop(self):
        pass

    def set_window(self, hwnd):
        pass

    def set_rate(self, rate):
        return True

    def add_subtitle(self, path):
        return True

    def media_player_get_state(self, _):
        return 3  # playing

    def media_player_get_length(self, _):
        return 6_720_000

    def media_player_get_time(self, _):
        return 2_650_000

    def media_player_is_seekable(self, _):
        return 1

    def tracks(self, kind):
        return [(1, "Nederlands"), (2, "English")] if kind == "audio" else [(-1, "Disable"), (3, "Nederlands")]

    def current_track(self, kind):
        return 1 if kind == "audio" else self.track

    def set_track(self, kind, track):
        self.track = track

    def __getattr__(self, name):  # every other libvlc call: accept and do nothing
        return lambda *args, **kwargs: 0


SOURCE = {"server": "http://127.0.0.1:9", "user": "demo", "password": "demo"}


def library(size=3000, seed=7):
    """A provider-like catalogue with the messy names real providers use."""
    rng = random.Random(seed)
    items, now = [], int(time.time())
    countries = ["NL", "BE", "FR", "DE", "UK", "TR"]
    for i in range(size // 10):
        code = countries[i % len(countries)]
        items.append({"id": f"live{i}", "kind": "live", "title": f"{code} | Kanaal {i} {'4K' if i % 9 == 0 else 'HD'}",
                      "group": f"{code} | Algemeen", "image": "", "url": f"http://127.0.0.1:9/live/u/p/{i}.m3u8",
                      "sid": str(i), "archive": i % 3 == 0, "archive_days": 3})
    for i in range(size * 7 // 10):
        code = countries[i % len(countries)]
        items.append({"id": f"m{i}", "kind": "movie", "title": f"[ALL] {code}: Film nummer {i} ({1990 + i % 35})",
                      "group": f"{code} - {['ACTIE', 'DRAMA', 'KOMEDIE', 'THRILLER'][i % 4]}", "image": "",
                      "url": f"http://127.0.0.1:9/movie/u/p/{i}.mkv", "sid": str(i),
                      "rating": round(rng.uniform(4, 9), 1), "added": now - i * 3600})
    for i in range(size // 5):
        items.append({"id": f"s{i}", "kind": "series", "title": f"Serie {i}", "group": "SERIES", "image": "",
                      "sid": str(i), "rating": round(rng.uniform(4, 9), 1), "added": now - i * 7200})
    return items


def details(source, item):
    info = {"plot": "Een verhaal over een stad aan zee.", "genre": "Drama, Mysterie", "rating": "7.4",
            "releasedate": "2024-03-01", "duration": "01:52:00", "cast": "Emma Claes, Lucas Janssens"}
    episodes = []
    if item["kind"] == "series":
        episodes = [{"id": f"{item['id']}e{s}{e}", "title": f"Aflevering {e}", "raw_title": f"[ALL] S0{s}E0{e}",
                     "group": f"Seizoen {s}", "kind": "movie", "url": f"http://127.0.0.1:9/series/u/p/{s}{e}.mp4"}
                    for s in (1, 2) for e in range(1, 9)]
    return info, episodes


def guide(source, sid):
    now = time.time()
    return [{"title": f"Programma {i}", "start": now - 1800 + i * 3600, "end": now + 1800 + i * 3600, "label": ""}
            for i in range(6)]
