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
