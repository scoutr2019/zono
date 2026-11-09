import unittest

import countries


class CleanTitle(unittest.TestCase):
    def test_strips_provider_prefixes_and_year(self):
        self.assertEqual(countries.clean_title("[ALL] NL: The Matrix (1999)"), "The Matrix")
        self.assertEqual(countries.clean_title("NL - Breaking Bad"), "Breaking Bad")
        self.assertEqual(countries.clean_title("[TR] Uzak Şehir"), "Uzak Şehir")

    def test_removes_superscript_quality_marks(self):
        self.assertNotIn("ᵁᴴᴰ", countries.clean_title("NPO 2ᵁᴴᴰ"))

    def test_keeps_title_that_would_become_empty(self):
        self.assertEqual(countries.clean_title("(2020)"), "(2020)")
        self.assertEqual(countries.clean_title("Normal"), "Normal")


class CleanName(unittest.TestCase):
    def test_channel_names(self):
        self.assertEqual(countries.clean_name("4K | VRT 1 HD"), "VRT 1")
        self.assertEqual(countries.clean_name("16K NPO 2ᵁᴴᴰ"), "NPO 2")
        self.assertEqual(countries.clean_name("BE: VTM 2 FHD"), "VTM 2")

    def test_never_empty(self):
        for text in ("HD", "4K", "|", "x"):
            self.assertTrue(countries.clean_name(text))


class Separators(unittest.TestCase):
    def test_detects_decorative_lines(self):
        self.assertTrue(countries.is_separator("##### NL #####"))
        self.assertTrue(countries.is_separator("♦♦♦ WELCOME ♦♦♦"))

    def test_normal_channels_are_not_separators(self):
        for text in ("NPO 1", "VRT 1 HD", "4K | VRT 1 HD", "RTL 4"):
            self.assertFalse(countries.is_separator(text), text)


class Episodes(unittest.TestCase):
    def test_episode_name_after_code(self):
        self.assertEqual(countries.clean_episode("[ALL] Dead-End Job (2026) - S01E01 - Convenience Store Rules"),
                         "Convenience Store Rules")

    def test_generic_names_become_aflevering(self):
        self.assertEqual(countries.clean_episode("Show - S01E02 - Episode 2"), "Aflevering 2")
        self.assertEqual(countries.clean_episode("Show S02E05"), "Aflevering 5")

    def test_provider_number_wins(self):
        self.assertEqual(countries.clean_episode("", 7), "Aflevering 7")


class Detect(unittest.TestCase):
    def test_detects_country_from_prefix_and_group(self):
        self.assertEqual(countries.detect_text("NL - Breaking Bad"), "NL")
        self.assertEqual(countries.detect({"title": "NL: RTL 4", "group": "Nederland"}), "NL")

    def test_names_are_dutch(self):
        self.assertEqual(countries.name("NL"), "Nederland")
        self.assertEqual(countries.name("BE"), "België")


if __name__ == "__main__":
    unittest.main()


class FourK(unittest.TestCase):
    def test_detects_4k_channels(self):
        import app
        for title in ("4K | VRT 1 HD", "NPO 1 UHD", "NPO 2ᵁᴴᴰ", "BE: Eén 2160p"):
            self.assertTrue(app.is_uhd({"raw_title": title}), title)
        self.assertTrue(app.is_uhd({"title": "VRT 1", "group": "BE | 4K"}))
        for title in ("VRT 1 HD", "NPO 1 FHD", "Canvas", "K4 Kids"):
            self.assertFalse(app.is_uhd({"title": title}), title)
