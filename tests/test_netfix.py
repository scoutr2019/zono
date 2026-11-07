"""Pictures from a server whose name the computer's DNS cannot find (blocked by the internet provider)."""
import os
import socket
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import netfix


class Picture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"picture for " + self.headers.get("Host", "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DnsFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
        urllib.request._opener = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Picture)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.asked = []
        cls.saved = netfix._ask
        netfix._ask = lambda host: cls.asked.append(host) or (["127.0.0.1"] if host == "covers.blocked.invalid" else [])
        netfix.enable()

    @classmethod
    def tearDownClass(cls):
        netfix._ask = cls.saved
        netfix._enabled = False
        socket.getaddrinfo = netfix._original
        cls.server.shutdown()
        cls.server.server_close()

    def test_blocked_name_still_loads(self):
        port = self.server.server_address[1]
        with urllib.request.urlopen(f"http://covers.blocked.invalid:{port}/p.jpg", timeout=5) as response:
            self.assertEqual(response.read(), f"picture for covers.blocked.invalid:{port}".encode())
        self.assertIn("covers.blocked.invalid", self.asked)

    def test_unknown_name_still_fails(self):
        with self.assertRaises(OSError):
            urllib.request.urlopen("http://does-not-exist.invalid/p.jpg", timeout=5)

    def test_addresses_are_not_looked_up(self):
        before = len(self.asked)
        socket.getaddrinfo("127.0.0.1", 80)
        self.assertEqual(len(self.asked), before)

    def test_answers_are_remembered(self):
        netfix._cache.pop("covers.blocked.invalid", None)
        socket.getaddrinfo("covers.blocked.invalid", 80)
        count = self.asked.count("covers.blocked.invalid")
        socket.getaddrinfo("covers.blocked.invalid", 80)
        self.assertEqual(self.asked.count("covers.blocked.invalid"), count)


if __name__ == "__main__":
    unittest.main()
