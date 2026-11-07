"""Four languages: every text has a translation, with the same placeholders."""
import json
import re
import subprocess
import sys
import unittest

import i18n
from tests import ROOT, SRC

PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class Translations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dump = subprocess.run([sys.executable, str(ROOT / "tools" / "strings.py"), "--dump"], capture_output=True,
                              text=True, check=True)
        cls.texts = json.loads(dump.stdout)
        cls.tables = {code: json.loads((SRC / "locale" / f"{code}.json").read_text(encoding="utf-8"))
                      for code in ("en", "fr", "de")}

    def test_there_are_many_texts(self):
        self.assertGreater(len(self.texts), 400)

    def test_every_text_is_translated(self):
        for code, table in self.tables.items():
            missing = [t for t in self.texts if not table.get(t)]
            self.assertEqual(missing, [], f"{code}: {len(missing)} texts without translation")

    def test_placeholders_match(self):
        for code, table in self.tables.items():
            for text in self.texts:
                self.assertEqual(PLACEHOLDER.findall(text), PLACEHOLDER.findall(table[text]), f"{code}: {text!r}")
                self.assertEqual(text.count("\n"), table[text].count("\n"), f"{code}: {text!r}")

    def test_format_works(self):
        for code, table in self.tables.items():
            for text in self.texts:
                count = len(PLACEHOLDER.findall(text))
                if count and not any(":" in p for p in PLACEHOLDER.findall(text)):
                    table[text].format(*range(count))

    def test_four_languages(self):
        self.assertEqual(list(i18n.LANGUAGES), ["nl", "fr", "en", "de"])

    def test_dutch_is_the_source(self):
        self.assertEqual(i18n.CODE, "nl")
        self.assertEqual(i18n.T("Instellingen"), "Instellingen")
        self.assertEqual(i18n.T("Afspelen||instellingen"), "Afspelen")
        self.assertEqual(i18n.shown("Seizoen 2"), "Seizoen 2")

    def test_shown_translates_names_zono_makes(self):
        saved = i18n.CODE, i18n._TABLE
        try:
            i18n.CODE, i18n._TABLE = "en", self.tables["en"]
            self.assertEqual(i18n.shown("Seizoen 3"), "Season 3")
            self.assertEqual(i18n.shown("Aflevering 12"), "Episode 12")
            self.assertEqual(i18n.shown("Overige"), "Other")
            self.assertEqual(i18n.shown("Breaking Bad"), "Breaking Bad")
        finally:
            i18n.CODE, i18n._TABLE = saved


if __name__ == "__main__":
    unittest.main()
