"""Live pause/rewind: the combined playlist over all saved parts (no VLC needed for this part)."""
import tempfile

import unittest
from pathlib import Path

import player


def write_part(folder, first, count, seconds=4.0):
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:4"]
    for number in range(first, first + count):
        name = f"seg-{number:08d}.ts"
        (folder / name).write_bytes(bytes([number % 256]) * 10)
        lines += [f"#EXTINF:{seconds:.3f},", name]
    (folder / "index.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")


class LiveBufferIndex(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zono-buffer-"))
        self.buffer = player.LiveBuffer("http://example/live.ts", self.root / "b", seconds=40)

    def tearDown(self):
        self.buffer.close()

    def index(self):
        return (self.root / "b" / "index.m3u8").read_text(encoding="utf-8")

    def test_merges_parts_with_discontinuity(self):
        self.buffer.display_chain()
        write_part(self.buffer.parts[0], 1, 3)
        self.buffer._new_part()
        write_part(self.buffer.parts[1], 1, 2)
        with self.buffer.lock:
            self.assertTrue(self.buffer.write_index())
        text = self.index()
        self.assertEqual(text.count("#EXTINF"), 5)
        self.assertEqual(text.count("#EXT-X-DISCONTINUITY\n"), 1)
        self.assertIn("p0/seg-00000001.ts", text)
        self.assertIn("p1/seg-00000002.ts", text)
        self.assertEqual(self.buffer.seconds_kept(), 20)

    def test_window_drops_and_deletes_old_pieces(self):
        self.buffer.display_chain()
        write_part(self.buffer.parts[0], 1, 15)  # 60 s saved, window is 40 s
        with self.buffer.lock:
            self.buffer.write_index()
        text = self.index()
        self.assertEqual(text.count("#EXTINF"), 10)
        self.assertNotIn("seg-00000001.ts", text)
        self.assertFalse((self.buffer.parts[0] / "seg-00000001.ts").exists(), "old pieces free disk space")
        self.assertTrue((self.buffer.parts[0] / "seg-00000015.ts").exists())

    def test_media_sequence_keeps_counting(self):
        self.buffer.display_chain()
        write_part(self.buffer.parts[0], 1, 12)
        with self.buffer.lock:
            self.buffer.write_index()
        first = int(self.index().split("#EXT-X-MEDIA-SEQUENCE:")[1].split()[0])
        write_part(self.buffer.parts[0], 1, 14)
        with self.buffer.lock:
            self.buffer.write_index()
        second = int(self.index().split("#EXT-X-MEDIA-SEQUENCE:")[1].split()[0])
        self.assertEqual(second, first + 2)

    def test_keep_parts_survives_player_stop(self):
        self.buffer.display_chain()
        write_part(self.buffer.parts[0], 1, 3)
        self.buffer.keep_parts()
        for file in (self.root / "b" / "p0").glob("seg-*.ts"):  # VLC deletes its pieces when it stops
            file.unlink()
        self.assertEqual(self.buffer.parts[0].name, "p0k")
        self.assertEqual(len(self.buffer.entries()), 3)
        self.assertIn("p0k/seg-00000003.ts", self.index())

    def test_tap_appends_only_new_pieces(self):
        self.buffer.display_chain()
        write_part(self.buffer.parts[0], 1, 2)
        target = self.root / "rec.ts"
        tap = player.BufferTap(self.buffer, target)
        write_part(self.buffer.parts[0], 1, 4)
        tap.close()
        self.assertEqual(target.read_bytes(), bytes([3]) * 10 + bytes([4]) * 10)

    def test_chains(self):
        chain = player.buffer_chain("C:/tmp/x", 120)
        self.assertIn("numsegs=30", chain)
        self.assertTrue(chain.startswith("#duplicate{dst=display"))
        self.assertEqual(chain.count("{"), chain.count("}"))


if __name__ == "__main__":
    unittest.main()
