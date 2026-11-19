"""Scotty's name over upstream's strings: shown as Scotty where it means this app, kept as Beamer
where it means upstream's program on some machine."""

import unittest

from core import brand
from core.i18n import tr, trn


class RebrandTests(unittest.TestCase):
    def test_this_apps_name_becomes_scotty(self):
        self.assertEqual(tr("Quit Beamer"), "Quit Scotty")
        self.assertEqual(tr("About Beamer"), "About Scotty")
        self.assertEqual(tr("Beamer {version} is available."), "Scotty {version} is available.")
        self.assertEqual(brand.rebrand("x", "Beamer's window"), "Scotty's window")

    def test_upstream_beamer_keeps_its_name(self):
        for message in (
            "{name} runs an older Beamer. Update Beamer on it to 1.5.0, then pair again.",
            "{name} was paired on Beamer 1.4. Pair the two again to link them on 1.5.0.",
            "macOS 27 blocked direct LAN access. Open /Applications/Beamer Tunnel.command.",
            "Update Beamer on {name}: it is older than this one",
            "Older Beamer versions share known Crossing and Design settings without group choices.",
        ):
            self.assertEqual(brand.rebrand(message, message), message)

    def test_only_the_whole_word_changes(self):
        self.assertEqual(brand.rebrand("x", "BeamerSecureDesktop and Beamer"), "BeamerSecureDesktop and Scotty")

    def test_the_credit_names_upstream(self):
        credit = ("Copied files and folders follow the pointer between Windows PCs. Based on Beamer {upstream} by "
                  "{author}, free software under the GNU GPL version 3.")
        self.assertIn("Based on Beamer", brand.rebrand(credit, credit))

    def test_plural_and_empty_are_safe(self):
        self.assertEqual(brand.rebrand("x", ""), "")
        self.assertIsNone(brand.rebrand("x", None))
        self.assertNotIn("Beamer", trn("Beamer machine", "Beamer machines", 2))

    def test_scotty_has_its_own_version_and_home(self):
        self.assertRegex(brand.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertTrue(brand.REPOSITORY_URL.startswith("https://github.com/"))


if __name__ == "__main__":
    unittest.main()
