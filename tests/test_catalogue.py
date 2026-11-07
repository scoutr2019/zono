import unittest

import catalogue as data

SOURCE = {"type": "xtream", "server": "http://host:8080", "user": "u", "password": "p"}


class Playlist(unittest.TestCase):
    def test_parse_m3u(self):
        raw = ('#EXTM3U\n#EXTINF:-1 tvg-id="a" tvg-logo="http://l/a.png" group-title="NL",NPO 1\nhttp://x/1.ts\n'
               '#EXTINF:-1 group-title="Films",Film A\nhttp://x/2.mp4\n')
        items = data.parse_m3u(raw)
        self.assertEqual([i["title"] for i in items], ["NPO 1", "Film A"])
        self.assertEqual(items[0]["kind"], "live")
        self.assertEqual(items[0]["image"], "http://l/a.png")
        self.assertEqual(items[1]["kind"], "movie")

    def test_empty_playlist(self):
        self.assertEqual(data.parse_m3u("#EXTM3U\n"), [])


class Links(unittest.TestCase):
    def test_only_http_links(self):
        self.assertEqual(data.check_url("http://a.b/c"), "http://a.b/c")
        for bad in ("ftp://x", "javascript:alert(1)", "", "file:///c:/windows"):
            with self.assertRaises(ValueError):
                data.check_url(bad)

    def test_stream_urls(self):
        self.assertEqual(data.stream_url(SOURCE, "movie", 5, "mkv"), "http://host:8080/movie/u/p/5.mkv")
        self.assertEqual(data.stream_url(SOURCE, "live", 7), "http://host:8080/live/u/p/7")


class Secrets(unittest.TestCase):
    def test_seal_hides_credentials_and_round_trips(self):
        url = "http://host:8080/movie/u/p/5.mkv"
        sealed = data.seal(url, SOURCE)
        self.assertNotIn("/u/p/", sealed)
        self.assertEqual(data.unseal(sealed, SOURCE), url)

    def test_pin_hash(self):
        stored = data.hash_pin("1234")
        self.assertNotIn("1234", stored)
        self.assertTrue(data.check_pin(stored, "1234"))
        self.assertFalse(data.check_pin(stored, "0000"))
        self.assertNotEqual(stored, data.hash_pin("1234"), "every hash gets its own salt")


class EpisodeRows(unittest.TestCase):
    def test_titles_are_cleaned_and_grouped(self):
        rows = data.episode_rows(SOURCE, {"episodes": {"1": [
            {"id": "9", "title": "[ALL] Show - S01E01 - Pilot", "episode_num": 1, "container_extension": "mkv",
             "info": {}}]}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Pilot")
        self.assertEqual(rows[0]["group"], "Seizoen 1")
        self.assertTrue(rows[0]["url"].endswith("/series/u/p/9.mkv"))


if __name__ == "__main__":
    unittest.main()
