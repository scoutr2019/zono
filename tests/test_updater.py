"""Automatic updates: finding the newest release, a checked download, replacing Zono.exe, cleaning up."""
import hashlib
import io
import json
import shutil
import unittest
from unittest import mock

import updater

PROGRAM = b"MZ" + b"\0" * 6_000_000  # looks like a Windows program


class FakeResponse(io.BytesIO):
    def __init__(self, body, url="https://objects.githubusercontent.com/zono"):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def release(tag="v2.3.0", digest=True, name="Zono.exe", draft=False):
    asset = {"name": name, "size": len(PROGRAM),
             "browser_download_url": f"https://github.com/scoutr2019/zono/releases/download/{tag}/{name}"}
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(PROGRAM).hexdigest()
    return {"tag_name": tag, "draft": draft, "prerelease": False, "assets": [asset], "body": "Nieuw"}


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.newer("2.2.10", "2.2.9"))
        self.assertTrue(updater.newer("v3.0.0", "2.9.9"))
        self.assertFalse(updater.newer("2.2.2", "2.2.2"))
        self.assertFalse(updater.newer("", "2.2.2"))
        self.assertFalse(updater.newer("2.2.1", "2.2.2"))


class Updates(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(updater.ROOT, ignore_errors=True)
        updater.ROOT.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(updater.ROOT, ignore_errors=True)

    def answer(self, *bodies):
        responses = [b if isinstance(b, FakeResponse) else
                     FakeResponse(json.dumps(b).encode()) if isinstance(b, dict) else FakeResponse(b) for b in bodies]
        return mock.patch.object(updater, "urlopen", side_effect=lambda *a, **k: responses.pop(0))

    def test_latest_release(self):
        with self.answer(release()):
            info = updater.latest()
        self.assertEqual(info["version"], "2.3.0")
        self.assertTrue(info["url"].endswith("/Zono.exe"))
        self.assertEqual(len(info["sha256"]), 64)

    def test_drafts_and_releases_without_program_are_ignored(self):
        with self.answer(release(draft=True)):
            self.assertIsNone(updater.latest())
        with self.answer(release(name="notes.txt")):
            self.assertIsNone(updater.latest())

    def test_tv_releases_marked_latest_are_skipped(self):
        tv = {"tag_name": "v2.3.7", "name": "Zono TV 2.3.7", "draft": False, "prerelease": False,
              "assets": [{"name": "Zono-TV.apk", "browser_download_url": "https://github.com/x/Zono-TV.apk"}]}
        old = release()
        old["tag_name"] = "v2.2.0"
        with self.answer(json.dumps([tv, release(), old]).encode()):
            info = updater.latest()
        self.assertEqual(info["version"], "2.3.0")
        with self.answer(json.dumps([tv]).encode()):
            self.assertIsNone(updater.latest())

    def test_notes_with_full_language_names(self):
        body = "### Nederlands\r\n- Nieuw\r\n\r\n### Français\r\n- Nouveau"
        self.assertEqual(updater.release_notes(body, "fr"), ["Nouveau"])
        self.assertEqual(updater.release_notes(body, "nl"), ["Nieuw"])

    def test_download_installs_and_remembers_version(self):
        with self.answer(release()):
            info = updater.latest()
        with self.answer(PROGRAM):
            path = updater.download(info)
        self.assertEqual(path.read_bytes(), PROGRAM)
        self.assertEqual(updater.installed_version(), "2.3.0")

    def test_wrong_checksum_is_refused(self):
        with self.answer(release()):
            info = updater.latest()
        info["sha256"] = "0" * 64
        with self.answer(PROGRAM), self.assertRaises(ValueError):
            updater.download(info)
        self.assertFalse(updater.INSTALLED.exists())
        self.assertFalse((updater.ROOT / "Zono.exe.part").exists())

    def test_not_a_program_is_refused(self):
        info = {"version": "2.3.0", "url": "https://github.com/scoutr2019/zono/x", "size": 0, "sha256": ""}
        with self.answer(b"<html>" + b"x" * 6_000_000), self.assertRaises(ValueError):
            updater.download(info)

    def test_only_github_links(self):
        info = {"version": "2.3.0", "url": "https://evil.example/Zono.exe", "size": 0, "sha256": ""}
        with self.assertRaises(ValueError):
            updater.download(info)
        info["url"] = "https://github.com/scoutr2019/zono/x"
        with self.answer(FakeResponse(PROGRAM, url="https://evil.example/x")), self.assertRaises(ValueError):
            updater.download(info)

    def test_running_exe_is_moved_aside(self):
        updater.INSTALLED.write_bytes(b"MZold")
        new = updater.ROOT / "new.exe"
        new.write_bytes(b"MZnew")
        updater.replace_installed(new)
        self.assertEqual(updater.INSTALLED.read_bytes(), b"MZnew")
        self.assertEqual((updater.ROOT / "Zono.old.exe").read_bytes(), b"MZold")

    def test_cleanup_removes_only_older_versions(self):
        for name in ("2.1.1", "2.2.1", "2.2.2", "2.3.0", "notes"):
            (updater.ROOT / "app" / name).mkdir(parents=True)
        (updater.ROOT / "Zono.old.exe").write_bytes(b"MZ")
        updater.cleanup(updater.ROOT / "app" / "2.2.2")
        left = sorted(p.name for p in (updater.ROOT / "app").iterdir())
        self.assertEqual(left, ["2.2.2", "2.3.0", "notes"])
        self.assertFalse((updater.ROOT / "Zono.old.exe").exists())


if __name__ == "__main__":
    unittest.main()


class Notes(unittest.TestCase):
    BODY = ("**Nieuw**\n### NL\n- 4K-zenders **eerst**\n- Volumemixer toont Zono\n### EN\n- 4K channels first\n"
            "### FR\n- Chaînes 4K en premier\n\nInstalleren: download Zono.zip")

    def test_language_sections(self):
        self.assertEqual(updater.release_notes(self.BODY, "nl"), ["4K-zenders eerst", "Volumemixer toont Zono"])
        self.assertEqual(updater.release_notes(self.BODY, "en"), ["4K channels first"])
        self.assertEqual(updater.release_notes(self.BODY, "de"), ["4K-zenders eerst", "Volumemixer toont Zono"])

    def test_plain_bullets_and_links(self):
        body = "Nieuw in 2.3.0\n- Automatische [updates](https://x.y)\n* Startmenu\nTekst zonder streepje"
        self.assertEqual(updater.release_notes(body, "fr"), ["Automatische updates", "Startmenu"])


class Adopt(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(updater.ROOT, ignore_errors=True)
        updater.ROOT.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(updater.ROOT, ignore_errors=True)

    def test_first_start_copies_the_launcher(self):
        downloads = updater.ROOT.parent / "Downloads"
        downloads.mkdir(exist_ok=True)
        (downloads / "Zono (1).exe").write_bytes(b"MZlauncher")
        updater.adopt(downloads / "Zono (1).exe", "2.3.2")
        self.assertEqual(updater.INSTALLED.read_bytes(), b"MZlauncher")
        self.assertEqual(updater.installed_version(), "2.3.2")
        shutil.rmtree(downloads)

    def test_started_from_the_installed_copy(self):
        updater.INSTALLED.write_bytes(b"MZ")
        updater.adopt(updater.INSTALLED, "2.3.2")
        self.assertEqual(updater.INSTALLED.read_bytes(), b"MZ")
        self.assertEqual(updater.installed_version(), "2.3.2")
