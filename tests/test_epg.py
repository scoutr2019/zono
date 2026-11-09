"""XMLTV guide: reading, finding channels, searching, the playlist's own guide link."""
import gzip
import io
import tempfile
import time
import unittest
from pathlib import Path

import epg

NOW = 1_800_000_000  # a fixed moment for the tests


def stamp(offset):
    return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(NOW + offset))


XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="npo1.nl"><display-name>NPO 1 HD</display-name></channel>
  <channel id="een.be"><display-name>Eén</display-name></channel>
  <programme start="{stamp(-3600)}" stop="{stamp(1800)}" channel="npo1.nl"><title>NOS Journaal</title><desc>Nieuws</desc></programme>
  <programme start="{stamp(1800)}" stop="{stamp(7200)}" channel="npo1.nl"><title>Studio Voetbal</title></programme>
  <programme start="{stamp(86400)}" stop="{stamp(90000)}" channel="een.be"><title>Voetbal: Rode Duivels</title></programme>
  <programme start="{stamp(-10 * 86400)}" stop="{stamp(-10 * 86400 + 600)}" channel="een.be"><title>Te oud</title></programme>
  <programme start="{stamp(3600)}" stop="{stamp(7200)}" channel="other"><title>Voetbal elders</title></programme>
</tv>"""


class Times(unittest.TestCase):
    def test_parse_with_zone(self):
        self.assertEqual(epg.parse_time("20261109150000 +0100"), epg.parse_time("20261109140000 +0000"))
        self.assertEqual(epg.parse_time("202611091400"), epg.parse_time("20261109140000 +0000"))
        self.assertIsNone(epg.parse_time("morgen"))


class Reading(unittest.TestCase):
    def setUp(self):
        self.guide = epg.Guide.read(io.BytesIO(XML.encode()), now=NOW)

    def test_keeps_only_the_window(self):
        self.assertEqual(len(self.guide.programs["npo1.nl"]), 2)
        self.assertEqual([p[2] for p in self.guide.programs["een.be"]], ["Voetbal: Rode Duivels"])

    def test_finds_channels_by_id_or_name(self):
        self.assertEqual(self.guide.channel_for({"epg": "npo1.nl", "title": "x"}), "npo1.nl")
        self.assertEqual(self.guide.channel_for({"title": "NPO 1", "raw_title": "NL | NPO 1 FHD"}), "npo1.nl")
        self.assertEqual(self.guide.channel_for({"title": "Eén"}), "een.be")
        self.assertIsNone(self.guide.channel_for({"title": "Canvas"}))

    def test_rows(self):
        rows = self.guide.rows({"title": "NPO 1"})
        self.assertEqual(rows[0]["title"], "NOS Journaal")
        self.assertEqual(rows[0]["description"], "Nieuws")

    def test_search_only_my_channels_and_not_past(self):
        channels = [{"title": "NPO 1", "epg": "npo1.nl"}, {"title": "Eén"}]
        found = self.guide.search("voetbal", channels, now=NOW)
        self.assertEqual([p["title"] for _, p in found], ["Studio Voetbal", "Voetbal: Rode Duivels"])
        self.assertEqual(self.guide.search("journaal", channels, now=NOW + 3600), [])

    def test_keep_and_limit(self):
        small = epg.Guide.read(io.BytesIO(XML.encode()), now=NOW, keep={"een.be"})
        self.assertEqual(list(small.programs), ["een.be"])
        capped = epg.Guide.read(io.BytesIO(XML.encode()), now=NOW, limit=1)
        self.assertEqual(len(capped), 1)

    def test_gzip_file(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "guide.xml"
        path.write_bytes(gzip.compress(XML.encode()))
        self.assertEqual(len(epg.Guide.load(path, now=NOW)), 4)


class Playlist(unittest.TestCase):
    def test_guide_link_in_header(self):
        self.assertEqual(epg.m3u_guide_url('#EXTM3U url-tvg="http://epg.example/a.xml.gz,http://b"\n#EXTINF:-1,X'),
                         "http://epg.example/a.xml.gz")
        self.assertEqual(epg.m3u_guide_url('#EXTM3U x-tvg-url="https://g.example/g.xml"'), "https://g.example/g.xml")
        self.assertEqual(epg.m3u_guide_url("#EXTM3U\n#EXTINF:-1,X"), "")

    def test_tvg_id_is_kept(self):
        import catalogue
        items = catalogue.parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="npo1.nl" tvg-name="NPO 1",NPO 1 HD\nhttp://x/1.ts\n')
        self.assertEqual(items[0]["epg"], "npo1.nl")
        self.assertEqual(items[0]["tvg_name"], "NPO 1")


class Download(unittest.TestCase):
    def test_download_and_cache(self):
        calls = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        def opener(request, timeout=0):
            calls.append(request.full_url)
            return Response(XML.encode())
        folder = Path(tempfile.mkdtemp())
        first = epg.download("http://epg.example/g.xml", folder, opener=opener)
        second = epg.download("http://epg.example/g.xml", folder, opener=opener)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1, "a fresh guide is not downloaded again")


if __name__ == "__main__":
    unittest.main()
