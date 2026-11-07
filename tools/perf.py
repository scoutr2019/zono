"""Measure how fast Zono feels with a very large provider (56 000 titles by default).

    python tools/perf.py            (Windows)
    xvfb-run -a python tools/perf.py  (Linux)

Prints the time to start, to show every page, to scroll and to type a search. Nothing touches the network.
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests as helpers  # noqa: E402
from tests import fakes  # noqa: E402

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 56000


def main():
    folder = helpers.TEMP / "Zono"
    folder.mkdir(parents=True, exist_ok=True)
    items = fakes.library(SIZE)
    (folder / "library.json").write_text(json.dumps({"revision": "p", "library": items, "source": fakes.SOURCE,
                                                     "favorites": {}, "progress": {}}))
    import tkinter as tk
    import catalogue as data
    import app
    data.details, data.guide, data.full_guide = fakes.details, fakes.guide, fakes.guide
    app.Player = fakes.FakePlayer
    app.webview.available = lambda: False
    root = tk.Tk()
    app.configure_scale(root)
    root.geometry("1360x860+0+0")
    started = time.perf_counter()
    zono = app.Zono(root, data.load_profiles())
    root.update()
    print(f"{'Opstarten':22s} {(time.perf_counter() - started) * 1000:6.0f} ms   ({len(zono.library)} titels)")

    def measure(name, action):
        begin = time.perf_counter()
        action()
        root.update()
        while zono.deferred or zono.defer_job:
            root.update()
        print(f"{name:22s} {(time.perf_counter() - begin) * 1000:6.0f} ms")

    for name, tab in (("Ontdekken", "home"), ("Live TV", "live"), ("TV-gids", "guide"), ("Films", "movie"),
                      ("Series", "series"), ("Favorieten", "favorites"), ("Downloads", "downloads"),
                      ("Instellingen", "settings")):
        measure(name, lambda t=tab: zono.select(t))
    measure("Film detail", lambda: zono.show_detail(zono.by_kind["movie"][0]))
    measure("Serie detail", lambda: zono.show_detail(zono.by_kind["series"][0]))
    measure("Ontdekken (opnieuw)", lambda: zono.select("home"))

    steps, original = [], zono.scroll_step

    def timed():
        begin = time.perf_counter()
        original()
        steps.append(time.perf_counter() - begin)
    zono.scroll_step = timed
    for _ in range(10):
        zono.smooth_scroll(app.S(300))
        begin = time.perf_counter()
        while zono.scroll_job and time.perf_counter() - begin < 3:
            root.update()
    print(f"{'Scrollen':22s} {statistics.mean(steps) * 1000:6.1f} ms per beeld (traagste {max(steps) * 1000:.1f} ms)")

    zono.open_search()
    root.update()
    times = []
    for letter in "film 12":
        zono.search_var.set(zono.search_var.get() + letter)
        begin = time.perf_counter()
        zono.update_suggestions()
        root.update()
        times.append(time.perf_counter() - begin)
    print(f"{'Zoeken':22s} {statistics.mean(times) * 1000:6.0f} ms per letter (traagste {max(times) * 1000:.0f} ms)")
    log = data.LOG
    print("Logboek:", "leeg" if not log.exists() else log.read_text(encoding="utf-8")[-600:])
    root.destroy()


if __name__ == "__main__":
    main()
