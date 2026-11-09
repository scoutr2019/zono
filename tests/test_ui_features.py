"""The real app with an M3U playlist and an XMLTV guide: guide, searching programmes, reminders, series
recordings and the problem report panel. Needs a display (xvfb-run on Linux)."""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests as helpers
from tests import fakes

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    DISPLAY = True
except Exception:
    DISPLAY = False


def stamp(offset):
    return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(time.time() + offset))


XML = f"""<tv><channel id="een.be"><display-name>Eén</display-name></channel>
<programme start="{stamp(-1800)}" stop="{stamp(1800)}" channel="een.be"><title>Het Journaal</title></programme>
<programme start="{stamp(3600)}" stop="{stamp(5400)}" channel="een.be"><title>Thuis (S30E12)</title></programme>
<programme start="{stamp(90000)}" stop="{stamp(91800)}" channel="een.be"><title>Thuis (S30E13)</title></programme>
<programme start="{stamp(7200)}" stop="{stamp(9000)}" channel="een.be"><title>Sporza: voetbal</title></programme>
</tv>"""


class Guide(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = XML.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(DISPLAY, "no display (run under xvfb-run on Linux)")
class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        import urllib.request
        urllib.request._opener = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Guide)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        folder = helpers.TEMP / "Zono"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("reminders.json", "recordings.json", "zono.log"):
            (folder / name).unlink(missing_ok=True)
        channels = [{"id": f"http://127.0.0.1:9/{i}.ts", "kind": "live", "title": title, "group": "BE",
                     "image": "", "url": f"http://127.0.0.1:9/{i}.ts", **({"epg": "een.be"} if i == 0 else {})}
                    for i, title in enumerate(["Eén HD", "Canvas", "VTM"])]
        (folder / "library.json").write_text(json.dumps({
            "revision": "f", "library": channels + fakes.library(60)[6:], "source": None, "favorites": {},
            "progress": {}, "epg_url": f"http://127.0.0.1:{cls.server.server_address[1]}/guide.xml"}))
        import catalogue as data
        import app
        app.Player = fakes.FakePlayer
        app.webview.available = lambda: False
        cls.data, cls.app = data, app
        helpers.fresh_ui()
        cls.root = tk.Tk()
        app.configure_scale(cls.root)
        cls.root.geometry("1360x860+0+0")
        cls.zono = app.Zono(cls.root, data.load_profiles())
        cls.pump(5)  # the guide is loaded 3 s after start

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.server.shutdown()
        cls.server.server_close()

    @classmethod
    def pump(cls, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            cls.root.update()
            time.sleep(0.01)

    def clean(self, step):
        log = self.data.LOG
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        self.assertNotIn("Traceback", text, f"error after {step}:\n{text}")

    def channel(self):
        return next(i for i in self.zono.by_kind["live"] if i.get("epg") == "een.be")

    def test_1_guide_for_m3u(self):
        z = self.zono
        self.assertIsNotNone(z.epg, "the XMLTV guide was loaded")
        self.assertTrue(z.has_guide(self.channel()))
        rows = []
        z.fetch_guide(self.channel(), rows.extend)
        self.assertEqual(rows[0]["title"], "Het Journaal")
        z.select("guide")
        self.pump(1)
        z.select("live")
        self.pump(1)
        self.clean("guide pages")

    def test_2_search_programmes(self):
        z = self.zono
        z.query.set("voetbal")
        self.pump(1)
        found = z.epg.search("voetbal", z.by_kind["live"])
        self.assertEqual([p["title"] for _, p in found], ["Sporza: voetbal"])
        z.query.set("")
        self.pump(0.3)
        self.clean("search")

    def test_3_reminder_and_series(self):
        z = self.zono
        channel = self.channel()
        upcoming = next(r for r in z.epg.rows(channel) if r["title"].startswith("Thuis"))
        z.program_sheet(channel, upcoming, z.by_kind["live"])
        self.pump(0.3)
        z.toggle_reminder(channel, upcoming)
        self.assertTrue(z.reminder_for(channel, upcoming))
        z.toggle_series(channel, upcoming)
        self.pump(0.5)
        planned = [r for r in z.recordings if r["status"] == "planned" and r["title"].startswith("Thuis")]
        self.assertEqual(len(planned), 2, "both coming episodes are planned")
        saved = json.loads((helpers.TEMP / "Zono" / "reminders.json").read_text())
        self.assertEqual(len(saved["series"]), 1)
        # the reminder fires a minute before the start
        reminder = z.reminders[0]
        reminder["start"] = time.time() + 30
        z.check_reminders(time.time())
        self.assertTrue(reminder["notified"])
        self.pump(0.3)
        if z.sheet_close:
            z.sheet_close()
        z.select("downloads")
        self.pump(0.5)
        self.clean("reminders and series")

    def test_4_report_panel(self):
        z = self.zono
        z.report_problem("Escape werkt niet")
        self.pump(0.5)
        self.assertIsNotNone(z.sheet_close)
        z.sheet_close()
        z.select("settings")
        self.pump(1)
        self.clean("report panel and settings")


if __name__ == "__main__":
    unittest.main()
