"""Fork (Scotty): sending a link to the other PC. Only safe http(s) links travel or open; a peer can
open at most one tab a second, and none while "Accept files and links" is off."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core import protocol  # noqa: E402
import scotty_links  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


class LinkShareTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clipboard = "  https://example.com/page?q=1  "
        self.sent, self.opened, self.notes = [], [], []
        self.peers = 1
        self.share = scotty_links.LinkShare(
            lambda: self.clipboard, lambda m: self.sent.append(m) or self.peers,
            lambda url: self.opened.append(url) or True, lambda kind, info: self.notes.append(kind),
            clock=self.clock)

    def test_hotkey_sends_the_clipboard_link_trimmed(self):
        self.assertTrue(self.share.send_clipboard())
        self.assertEqual(self.sent, [protocol.open_url_msg("https://example.com/page?q=1")])
        self.assertEqual(self.notes, ["sent"])

    def test_hotkey_refuses_anything_but_a_safe_link(self):
        for text in ("hello", "file:///C:/x", "javascript:alert(1)", "https://a:b@example.com", "", None):
            with self.subTest(text=text):
                self.clipboard = text
                self.assertFalse(self.share.send_clipboard())
        self.assertEqual(self.sent, [])
        self.assertEqual(set(self.notes), {"not_a_link"})

    def test_no_peer_says_so(self):
        self.peers = 0
        self.assertFalse(self.share.send_clipboard())
        self.assertEqual(self.notes, ["no_peer"])

    def test_peer_link_opens_once_a_second(self):
        message = protocol.open_url_msg("https://example.com/")
        self.assertTrue(self.share.peer_sent("LAPTOP-1", message))
        self.assertFalse(self.share.peer_sent("LAPTOP-1", message))
        self.clock.now += scotty_links.OPEN_GAP_SECONDS
        self.assertTrue(self.share.peer_sent("LAPTOP-1", message))
        self.assertEqual(len(self.opened), 2)

    def test_peer_link_needs_the_switch_and_a_valid_message(self):
        self.share.accept = False
        self.assertFalse(self.share.peer_sent("LAPTOP-1", protocol.open_url_msg("https://example.com/")))
        self.share.accept = True
        for url in ("file:///C:/Windows/System32/calc.exe", "ms-settings:", "https://u@example.com/", 7):
            with self.subTest(url=url):
                self.assertFalse(self.share.peer_sent("LAPTOP-1", {"type": protocol.MSG_OPEN_URL, "data": {"url": url}}))
        self.assertEqual(self.opened, [])

    def test_failures_are_contained(self):
        def boom(*_):
            raise OSError("no")
        share = scotty_links.LinkShare(boom, boom, boom, lambda kind, info: None, clock=self.clock)
        self.assertFalse(share.send_clipboard())
        self.assertFalse(share.peer_sent("X", protocol.open_url_msg("https://example.com/")))


if __name__ == "__main__":
    unittest.main()
