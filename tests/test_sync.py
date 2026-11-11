"""Linking Zono apps (src/sync.py): the locking matches the TV app (tweetnacl), the package merges newest-wins, and the
real app takes over a TV's 'continue watching', favourites and last channel through a fake zono.be."""
import base64
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tests as helpers
import sync
from tests import fakes

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    DISPLAY = True
except Exception:
    DISPLAY = False

# made with the TV app's tweetnacl: key 00..1f, nonce 64..7b, message "Zono · verder kijken"
ORIGINAL_API = sync.API
VECTOR = bytes.fromhex("6465666768696a6b6c6d6e6f707172737475767778797a7b8be1bb58607cde319e73b24b9420abfc58d6f7a61a"
                       "7479c9c69851f052f6837357c053c28a")


class Store(BaseHTTPRequestHandler):
    """zono.be/api/sync.php: one locked package per id, written only with the current revision."""
    rows = {}

    def log_message(self, *args):
        pass

    def answer(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        sync_id = self.path.split("id=")[-1]
        rev, data = self.rows.get(sync_id, (0, ""))
        self.answer(200, {"rev": rev, "data": data})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        rev, data = self.rows.get(body["id"], (0, ""))
        if body["rev"] != rev:
            return self.answer(409, {"rev": rev, "data": data})
        self.rows[body["id"]] = (rev + 1, body["data"])
        self.answer(200, {"rev": rev + 1})


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Store)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Locking(unittest.TestCase):
    def test_opens_what_the_tv_locked(self):
        self.assertEqual(sync.unseal(VECTOR, bytes(range(32))).decode(), "Zono · verder kijken")

    def test_round_trip_and_tampering(self):
        key = os.urandom(32)
        box = sync.seal("héllo".encode(), key)
        self.assertEqual(sync.unseal(box, key).decode(), "héllo")
        changed = bytearray(box)
        changed[-1] ^= 1
        self.assertIsNone(sync.unseal(bytes(changed), key))
        self.assertIsNone(sync.unseal(box, os.urandom(32)))

    def test_same_id_as_the_tv(self):
        secret = sync.secret_for({"server": "HTTPS://Prov.example:8080/player_api.php", "user": " jan ", "password": "x"})
        self.assertEqual(secret, "xtream\nprov.example:8080\njan\nx")
        self.assertTrue(sync.derive(secret)[0].startswith("93c07b3fe1269220"))  # computed by js/sync.js
        self.assertEqual(sync.secret_for({"server": "", "user": "a", "password": "b"}), "")
        self.assertEqual(sync.link_secret("abcd-efgh"), "code\nABCDEFGH")
        self.assertEqual(len(sync.new_link_code()), 19)


class Merging(unittest.TestCase):
    def test_newest_change_wins(self):
        a = {"v": 1, "profiles": {"main": {"progress": {"m1": {"t": 5, "pos": 10}, "m2": {"t": 9, "pos": 3}},
                                           "fav": {"m3": {"t": 1, "on": True}}, "last": {"key": "l1", "t": 4}}}}
        b = {"v": 1, "profiles": {"main": {"progress": {"m1": {"t": 7, "pos": 60}, "m2": {"t": 2, "done": 1}},
                                           "fav": {"m3": {"t": 6, "on": False}}, "last": {"key": "l2", "t": 3}}}}
        part = sync.merge(a, b)["profiles"]["main"]
        self.assertEqual(part["progress"]["m1"]["pos"], 60)
        self.assertEqual(part["progress"]["m2"]["pos"], 3)
        self.assertFalse(part["fav"]["m3"]["on"])
        self.assertEqual(part["last"]["key"], "l1")

    def test_stays_small(self):
        many = {"v": 1, "profiles": {"main": {"progress": {f"m{i}": {"t": i} for i in range(1000)}, "fav": {}, "last": None}}}
        part = sync.merge(many, sync.empty())["profiles"]["main"]["progress"]
        self.assertEqual(len(part), sync.MAX_PROGRESS)
        self.assertIn("m999", part)

    def test_exchange_with_a_race(self):
        server = serve()
        try:
            sync.API = f"http://127.0.0.1:{server.server_address[1]}/api/sync.php"
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
            secret = sync.link_secret("AAAA-BBBB-CCCC-DDDD")
            tv = {"v": 1, "profiles": {"main": {"progress": {"m1": {"t": 1, "pos": 100}}, "fav": {}, "last": None}}}
            sync.exchange(secret, tv)
            # the pc saves with an old revision first (another device was quicker): it must merge, not overwrite
            sync_id, key = sync.derive(secret)
            rev, data = Store.rows[sync_id]
            Store.rows[sync_id] = (rev + 1, sync.lock(sync.merge(sync.open_package(data, key), {"v": 1, "profiles": {
                "main": {"progress": {"m2": {"t": 2, "pos": 5}}, "fav": {}, "last": None}}}), key))
            pc = {"v": 1, "profiles": {"main": {"progress": {"m3": {"t": 3, "pos": 7}}, "fav": {}, "last": None}}}
            merged = sync.exchange(secret, pc)
            self.assertEqual(set(merged["profiles"]["main"]["progress"]), {"m1", "m2", "m3"})
            stored = sync.open_package(Store.rows[sync_id][1], key)
            self.assertEqual(set(stored["profiles"]["main"]["progress"]), {"m1", "m2", "m3"})
            self.assertNotIn(b"m3", base64.b64decode(Store.rows[sync_id][1]))  # locked on the server
        finally:
            server.shutdown()
            sync.API = ORIGINAL_API


@unittest.skipUnless(DISPLAY, "no display (run under xvfb-run on Linux)")
class InTheApp(unittest.TestCase):
    """The real Windows app takes over what a TV did, and tells the TV what it did."""

    def test_continue_watching_from_the_tv(self):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        import urllib.request
        urllib.request._opener = None
        server = serve()
        sync.API = f"http://127.0.0.1:{server.server_address[1]}/api/sync.php"
        base = "http://prov.example"
        library = [{"id": f"{base}|live|2", "sid": "2", "kind": "live", "title": "VTM", "group": "BE", "image": "",
                    "url": f"{base}/live/u/p/2.m3u8"},
                   {"id": f"{base}|movie|100", "sid": "100", "kind": "movie", "title": "Noorderlicht", "group": "Drama",
                    "image": "", "url": f"{base}/movie/u/p/100.mkv"},
                   {"id": f"{base}|movie|101", "sid": "101", "kind": "movie", "title": "Orbit", "group": "Drama",
                    "image": "", "url": f"{base}/movie/u/p/101.mkv"}] + fakes.library(30)[3:]
        folder = helpers.TEMP / "Zono"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "library.json").write_text(json.dumps({"revision": "s", "library": library, "source": None,
                                                         "favorites": {}, "progress": {}}))
        (folder / "preferences.json").write_text(json.dumps({"sync_code": "ZONO-TEST-CODE-0001"}))
        secret = sync.link_secret("ZONO-TEST-CODE-0001")
        now = int(time.time() * 1000)
        sync.exchange(secret, {"v": 1, "profiles": {"main": {
            "progress": {"m100": {"t": now, "pos": 1500, "dur": 6000, "from": "lg", "kind": "movie", "title": "Noorderlicht"}},
            "fav": {"m101": {"t": now, "on": True, "kind": "movie", "title": "Orbit"}},
            "last": {"key": "l2", "t": now, "title": "VTM"}}}})
        import catalogue as data
        import app
        app.Player = fakes.FakePlayer
        app.webview.available = lambda: False
        helpers.fresh_ui()
        root = tk.Tk()
        try:
            app.configure_scale(root)
            root.geometry("1360x860+0+0")
            zono = app.Zono(root, data.load_profiles())
            zono.sync_now()
            deadline = time.time() + 15
            while time.time() < deadline and f"{base}|movie|100" not in zono.progress:
                root.update()
                time.sleep(0.05)
            entry = zono.progress.get(f"{base}|movie|100")
            self.assertIsNotNone(entry, "the TV's 'continue watching' arrived on the pc")
            self.assertEqual(entry["time"], 1500)
            self.assertEqual(entry["from"], "lg")
            self.assertIn(f"{base}|movie|101", zono.favorites)
            self.assertEqual(zono.preferences.get("last_channel"), f"{base}|live|2")
            # the pc removes the favourite: the TV gets to know
            zono.toggle(zono.favorites[f"{base}|movie|101"])
            zono.sync_now()
            deadline = time.time() + 15
            sync_id, key = sync.derive(secret)
            while time.time() < deadline:
                root.update()
                stored = sync.open_package(Store.rows[sync_id][1], key)
                if stored["profiles"]["main"]["fav"]["m101"]["on"] is False:
                    break
                time.sleep(0.05)
            self.assertFalse(stored["profiles"]["main"]["fav"]["m101"]["on"])
        finally:
            root.destroy()
            server.shutdown()
            sync.API = ORIGINAL_API
            (folder / "preferences.json").unlink(missing_ok=True)
