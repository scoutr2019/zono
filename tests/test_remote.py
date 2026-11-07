"""The phone remote: a small web server on the PC that relays provider streams to a phone on the same Wi-Fi."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import remote

OPEN = build_opener(ProxyHandler({})).open  # talk to the local test servers directly


class FakeProvider(BaseHTTPRequestHandler):
    """Answers like an IPTV provider: a playlist, a video file, a refused and a missing stream."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/live/index.m3u8":
            body, kind = b"#EXTM3U\n#EXTINF:4.0,\nseg-1.ts\n#EXTINF:4.0,\nhttp://cdn.example/seg-2.ts\n", \
                "application/vnd.apple.mpegurl"
        elif self.path == "/movie.mp4":
            body, kind = b"\x00" * 200_000, "video/mp4"
        elif self.path == "/busy":
            self.send_response(403)
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import urllib.request
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"  # the fake provider is local
        urllib.request._opener = None
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
        threading.Thread(target=cls.provider.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.provider.server_address[1]}"
        library = [{"kind": "live", "title": "NPO 1", "group": "NL", "url": cls.base + "/live/index.m3u8"},
                   {"kind": "movie", "title": "Film", "group": "Films", "url": cls.base + "/movie.mp4"},
                   {"kind": "series", "title": "Serie", "group": "Series", "sid": "5"}]
        cls.stopped = []
        cls.server = remote.RemoteServer(lambda: ("Test", library, None), lambda: "secret",
                                         stop_pc=lambda: cls.stopped.append(True))
        cls.server.start()
        cls.local = f"http://127.0.0.1:{cls.server.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.provider.shutdown()
        cls.provider.server_close()

    def get(self, path):
        with OPEN(self.local + path, timeout=10) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()

    def test_needs_token(self):
        with self.assertRaises(HTTPError) as caught:
            OPEN(self.local + "/api/library?t=wrong", timeout=10)
        self.assertEqual(caught.exception.code, 403)

    def test_library(self):
        status, _, body = self.get("/api/library?t=secret")
        found = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(found["profile"], "Test")
        self.assertEqual([i["n"] for i in found["live"]], ["NPO 1"])
        self.assertTrue(found["movie"][0]["u"].startswith("/s/"))
        self.assertNotIn(self.base, json.dumps(found), "provider links never reach the phone directly")

    def test_relay_round_trip(self):
        url = self.base + "/movie.mp4?x=1&y=é"
        code = self.server.relay(url)[3:].split("?")[0]
        self.assertEqual(remote.RemoteServer.unrelay(code), url)

    def test_relay_refuses_other_schemes(self):
        import base64
        code = base64.urlsafe_b64encode(b"file:///etc/passwd").decode().rstrip("=")
        with self.assertRaises(ValueError):
            remote.RemoteServer.unrelay(code)
        with self.assertRaises(HTTPError) as caught:
            OPEN(f"{self.local}/s/{code}?t=secret", timeout=10)
        self.assertEqual(caught.exception.code, 400)

    def test_streams_a_file(self):
        status, kind, body = self.get(self.server.relay(self.base + "/movie.mp4"))
        self.assertEqual((status, kind, len(body)), (200, "video/mp4", 200_000))

    def test_rewrites_playlists(self):
        status, kind, body = self.get(self.server.relay(self.base + "/live/index.m3u8"))
        text = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("mpegurl", kind)
        links = [line for line in text.splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(links), 2)
        self.assertTrue(all(line.startswith("/s/") for line in links), text)
        self.assertEqual(remote.RemoteServer.unrelay(links[0][3:].split("?")[0]), self.base + "/live/seg-1.ts")

    def test_check_explains_failures(self):
        def reason(path):
            code = self.server.relay(self.base + path)[3:].split("?")[0]
            return json.loads(self.get(f"/api/check?t=secret&c={code}")[2])["reason"]
        self.assertEqual(reason("/movie.mp4"), "ok")
        self.assertEqual(reason("/busy"), "limit")
        self.assertEqual(reason("/nothing"), "gone")

    def test_stop_pc(self):
        self.get("/api/stop-pc?t=secret")
        self.assertTrue(self.stopped)


if __name__ == "__main__":
    unittest.main()
