"""Statistics and problem reports: what leaves the PC, once a day, and never a login."""
import io
import json
import shutil
import unittest

import telemetry


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Capture:
    def __init__(self, answer=None):
        self.sent, self.answer = [], answer or {"ok": True, "number": 7}

    def __call__(self, request, timeout=0):
        self.sent.append((request.full_url, json.loads(request.data)))
        return Response(json.dumps(self.answer).encode())


class Statistics(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(telemetry.ROOT, ignore_errors=True)

    def test_once_a_day_with_only_these_fields(self):
        capture = Capture({"ok": True})
        self.assertTrue(telemetry.ping("2.4.0", "nl", opener=capture, now=1_800_000_000))
        self.assertFalse(telemetry.ping("2.4.0", "nl", opener=capture, now=1_800_000_100))
        self.assertTrue(telemetry.ping("2.4.0", "nl", opener=capture, now=1_800_000_000 + 86400))
        url, body = capture.sent[0]
        self.assertEqual(url, "https://zono.be/api/ping.php")
        self.assertEqual(sorted(body), ["id", "language", "version", "windows"])
        self.assertRegex(body["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(capture.sent[1][1]["id"], body["id"], "the same random number every day")

    def test_switched_off(self):
        telemetry.set_sharing(False)
        capture = Capture()
        self.assertFalse(telemetry.ping("2.4.0", "nl", opener=capture))
        self.assertEqual(capture.sent, [])


class Reports(unittest.TestCase):
    def test_log_without_logins_or_user_name(self):
        log = ("HTTPError http://host:8080/live/lode/geheim99/123.ts\n"
               "http://host/player_api.php?username=lode&password=geheim99\n"
               'File "C:\\Users\\hendr\\AppData\\Local\\Zono\\app\\2.2.1\\app.py"')
        cleaned = telemetry.clean_log(log)
        for secret in ("geheim99", "lode", "hendr"):
            self.assertNotIn(secret, cleaned)
        self.assertIn("/live/***/***/123.ts", cleaned)

    def test_report(self):
        capture = Capture()
        number = telemetry.report("2.4.0", "nl", "Escape werkt niet", "a@b.be", "log", opener=capture)
        self.assertEqual(number, 7)
        self.assertEqual(capture.sent[0][1]["message"], "Escape werkt niet")

    def test_refused(self):
        with self.assertRaises(ValueError):
            telemetry.report("2.4.0", "nl", "x", opener=Capture({"error": "too many reports"}))


if __name__ == "__main__":
    unittest.main()
