"""OpenSubtitles: searching and downloading, without the network."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

import subtitles


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Fake:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request, timeout=0):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer if isinstance(answer, bytes) else json.dumps(answer).encode())


SEARCH = {"data": [
    {"attributes": {"language": "nl", "download_count": 900, "release": "The.Matrix.1999.1080p",
                    "files": [{"file_id": 111, "file_name": "matrix.srt"}]}},
    {"attributes": {"language": "nl", "files": []}},
]}


class Search(unittest.TestCase):
    def test_film(self):
        fake = Fake(SEARCH)
        found = subtitles.search("KEY", "[ALL] NL: The Matrix (1999) 4K", "nl", year="1999", opener=fake)
        self.assertEqual(found, [{"file_id": 111, "name": "The.Matrix.1999.1080p", "language": "nl", "downloads": 900}])
        request = fake.requests[0]
        self.assertIn("query=The+Matrix", request.full_url)
        self.assertIn("year=1999", request.full_url)
        self.assertEqual(request.get_header("Api-key"), "KEY")

    def test_episode(self):
        fake = Fake({"data": []})
        subtitles.search("KEY", "Thuis", "nl", season=30, episode=12, opener=fake)
        self.assertIn("season_number=30", fake.requests[0].full_url)
        self.assertIn("episode_number=12", fake.requests[0].full_url)

    def test_episode_numbers(self):
        self.assertEqual(subtitles.episode_numbers("[ALL] Show - S02E05 - Naam"), (2, 5))
        self.assertEqual(subtitles.episode_numbers("Film"), (None, None))


class Download(unittest.TestCase):
    def test_download_saves_srt(self):
        fake = Fake({"link": "https://dl.example/x.srt", "remaining": 4}, b"1\n00:00:01,000 --> 00:00:02,000\nHallo\n")
        folder = Path(tempfile.mkdtemp())
        path = subtitles.download("KEY", {"file_id": 111, "language": "nl"}, folder, opener=fake)
        self.assertTrue(path.read_text().endswith("Hallo\n"))
        self.assertEqual(json.loads(fake.requests[0].data)["file_id"], 111)

    def test_daily_limit(self):
        fake = Fake(HTTPError("u", 406, "limit", {}, None))
        with self.assertRaises(subtitles.LimitReached):
            subtitles.download("KEY", {"file_id": 1}, tempfile.mkdtemp(), opener=fake)


if __name__ == "__main__":
    unittest.main()
