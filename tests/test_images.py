"""Posters must load even from picky picture servers."""
import io
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

import app

PNG = io.BytesIO()
Image.new("RGB", (40, 60), (200, 30, 30)).save(PNG, "PNG")
PNG = PNG.getvalue()


class PickyServer(BaseHTTPRequestHandler):
    """Like some IPTV picture hosts: refuses programs that do not look like a browser."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if "Mozilla" not in self.headers.get("User-Agent", "") or self.path != "/poster.png":
            self.send_response(403 if self.path == "/poster.png" else 404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)


class Images(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        urllib.request._opener = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PickyServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_loads_from_picky_server(self):
        image = app.download_image(self.base + "/poster.png")
        self.assertEqual(image.size, (40, 60))

    def test_cover_is_cut_to_size(self):
        self.assertEqual(app.cover(self.base + "/poster.png", (100, 150)).size, (100, 150))

    def test_missing_picture_fails_quickly(self):
        with self.assertRaises(Exception):
            app.download_image(self.base + "/missing.png")
        self.assertIsNone(app.safe(app.cover, self.base + "/missing.png", (10, 10)))

    def test_only_web_links(self):
        with self.assertRaises(ValueError):
            app.download_image("file:///c:/windows/win.ini")


if __name__ == "__main__":
    unittest.main()


class SparePictures(unittest.TestCase):
    """The provider's poster server does not exist (as in a real log: getaddrinfo failed): Zono uses the pictures
    from the provider's detail info instead, and remembers which one worked."""

    @classmethod
    def setUpClass(cls):
        Images.setUpClass()
        cls.base = Images.base
        import catalogue as data
        cls.data = data
        cls.asked = []

        def details(source, item):
            cls.asked.append(item["id"])
            return {"movie_image": cls.base + "/poster.png", "backdrop_path": [cls.base + "/missing.png"]}, []
        cls.saved = data.details
        data.details = details

    @classmethod
    def tearDownClass(cls):
        cls.data.details = cls.saved
        Images.tearDownClass()

    def make(self):
        import threading
        zono = object.__new__(app.Zono)
        zono.art_fix, zono.art_fix_dirty, zono.art_fix_saved = {}, False, 0
        zono.art_lock = threading.BoundedSemaphore(3)
        zono.source = {"server": "http://x", "user": "u", "password": "p"}
        zono.preferences = {}
        return zono

    def test_dead_server_falls_back_to_detail_pictures(self):
        zono = self.make()
        item = {"id": "m1", "kind": "movie", "sid": "1", "title": "Film",
                "image": "http://cover.dead-host.invalid/1.jpg"}
        image = zono.picture(item, lambda url: app.cover(url, (20, 30)))
        self.assertIsNotNone(image)
        self.assertEqual(image.size, (20, 30))
        self.assertEqual(self.asked.count("m1"), 1)
        zono.picture(item, lambda url: app.cover(url, (20, 30)))
        self.assertEqual(self.asked.count("m1"), 1, "the provider is asked only once per title")
        self.assertIn("cover.dead-host.invalid", app._dead_hosts, "a server that does not exist is skipped")

    def test_wide_pictures_first_for_the_banner(self):
        zono = self.make()
        item = {"id": "m2", "kind": "movie", "sid": "2", "title": "Film", "image": ""}
        self.assertEqual(zono.spare_pictures(item, wide=True)[0], self.base + "/missing.png")
        self.assertEqual(zono.spare_pictures(item)[0], self.base + "/poster.png")

    def test_channels_need_no_spares(self):
        self.assertEqual(self.make().spare_pictures({"id": "l1", "kind": "live"}), [])
