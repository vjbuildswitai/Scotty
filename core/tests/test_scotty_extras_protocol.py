"""Scotty's extra messages (WIRE.md section 12): lock, files_push, open_url, machine_info, and the
Wake-on-LAN packet. Everything a peer sends is untrusted: malformed or hostile input reads as None."""

import threading
import unittest
from unittest import mock

from core import link as link_module
from core import protocol, receiver
from core.link import _CAP_FOR


class GatingTests(unittest.TestCase):
    def test_every_extra_rides_one_capability(self):
        for kind in (protocol.MSG_LOCK, protocol.MSG_FILES_PUSH, protocol.MSG_OPEN_URL, protocol.MSG_MACHINE_INFO):
            self.assertEqual(_CAP_FOR[kind], protocol.CAP_SCOTTY_EXTRAS)


class LockTests(unittest.TestCase):
    def test_round_trip_and_other_types(self):
        self.assertTrue(protocol.read_lock(protocol.lock_msg()))
        self.assertFalse(protocol.read_lock({"type": "lock"}))           # no data object
        self.assertFalse(protocol.read_lock({"type": "unlock", "data": {}}))
        self.assertFalse(protocol.read_lock("lock"))


class FilesPushTests(unittest.TestCase):
    def test_same_rules_as_a_crossing_manifest(self):
        message = protocol.files_push_msg(bytes(16), bytes(32), 24822, ["a.txt"], 1, 5)
        self.assertEqual(message["type"], protocol.MSG_FILES_PUSH)
        read = protocol.read_files_push(message)
        self.assertEqual(read["names"], ["a.txt"])
        self.assertIsNone(protocol.read_files(message))  # not a crossing manifest
        bad = dict(message, data=dict(message["data"], names=["..", "x"]))
        self.assertIsNone(protocol.read_files_push(bad))
        with self.assertRaises(ValueError):
            protocol.files_push_msg(bytes(16), bytes(32), 24822, ["CON"], 1, 5)


class UrlTests(unittest.TestCase):
    def test_ordinary_links_pass(self):
        for url in ("https://example.com", "http://192.168.1.5:3000/page?q=1#top",
                    "https://localhost:5173/", "https://xn--fsq.example/a"):
            with self.subTest(url=url):
                self.assertTrue(protocol.safe_url(url))
                self.assertEqual(protocol.read_open_url(protocol.open_url_msg(url)), url)

    def test_anything_else_is_refused(self):
        for url in ("file:///C:/Windows/System32/cmd.exe", "javascript:alert(1)", "ms-settings:privacy",
                    "ftp://example.com", "https://user:pw@example.com/", "https://user@example.com/",
                    "https://exa mple.com", "https://example.com/\nX", "https://example.com/\u202e",
                    "https://", "https://example.com:99999/", "", None, 5,
                    "https://example.com/" + "a" * protocol.OPEN_URL_MAX_CHARS):
            with self.subTest(url=url):
                self.assertFalse(protocol.safe_url(url))
                self.assertIsNone(protocol.read_open_url({"type": protocol.MSG_OPEN_URL, "data": {"url": url}}))
        with self.assertRaises(ValueError):
            protocol.open_url_msg("file:///etc/passwd")


class MachineInfoTests(unittest.TestCase):
    def test_round_trip_lowercases(self):
        message = protocol.machine_info_msg(["AA:BB:CC:DD:EE:01"])
        self.assertEqual(protocol.read_machine_info(message), ["aa:bb:cc:dd:ee:01"])
        self.assertEqual(protocol.read_machine_info(protocol.machine_info_msg([])), [])

    def test_malformed_is_refused(self):
        for macs in ("aa:bb:cc:dd:ee:01", [1], ["aa-bb-cc-dd-ee-01"], ["AA:BB:CC:DD:EE:01"],
                     ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:01"], ["00:00:00:00:00:00"],
                     ["ff:ff:ff:ff:ff:ff"], ["aa:bb:cc:dd:ee:%02x" % i for i in range(9)]):
            with self.subTest(macs=macs):
                self.assertIsNone(protocol.read_machine_info({"type": protocol.MSG_MACHINE_INFO,
                                                             "data": {"macs": macs}}))

    def test_wake_packet_shape(self):
        packet = protocol.wake_packet("AA:BB:CC:DD:EE:01")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("aabbccddee01"))
        self.assertEqual(packet[6:], bytes.fromhex("aabbccddee01") * 16)
        with self.assertRaises(ValueError):
            protocol.wake_packet("not a mac")


class LinkGateTests(unittest.TestCase):
    """Stock Beamer, the Mac app and Scotty 1.0 never list scotty_extras, so they never get these."""

    def _inbound(self, caps):
        link = receiver._Link.__new__(receiver._Link)
        link.cond = threading.Condition()
        link.closed = threading.Event()
        link.caps = frozenset(caps)
        link.outbox = []
        return link

    def _outbound(self, caps):
        link = link_module.OutboundLink.__new__(link_module.OutboundLink)
        link._live = True
        link._secure_endpoint = False
        link._caps = frozenset(caps)
        link.queued = []
        link._enqueue = lambda message, seq: link.queued.append(message) or True
        return link

    def test_both_directions_send_only_to_a_capable_peer(self):
        for make, sent in ((self._inbound, "outbox"), (self._outbound, "queued")):
            stock = make({"clipboard", protocol.CAP_CLIPBOARD_FILES})
            self.assertTrue(stock.post(protocol.lock_msg()))
            self.assertEqual(getattr(stock, sent), [])
            fork = make({protocol.CAP_SCOTTY_EXTRAS})
            self.assertTrue(fork.post(protocol.lock_msg()))
            self.assertEqual([m["type"] for m in getattr(fork, sent)], [protocol.MSG_LOCK])

    def test_fifteen_caps_fit_in_hello(self):
        caps = ["clipboard", "clipboard_image", "gestures", "media_keys", "text", "settings", "design_sync", "layout",
                "profiles", "displays", "identify_screens", "ping_rtt", "motion_path", protocol.CAP_CLIPBOARD_FILES,
                protocol.CAP_SCOTTY_EXTRAS]
        self.assertLessEqual(len(caps), protocol.MAX_CAPS)
        hello = protocol.hello_v6(bytes(range(16)), "VIJAYARAJ-DEV", "windows", "1.5.21", caps, 24820)
        read = protocol.read_hello(protocol.parse_message(protocol.dumps_message(hello)))
        self.assertIn(protocol.CAP_SCOTTY_EXTRAS, read["caps"])


class ReceiverExtrasTests(unittest.TestCase):
    def setUp(self):
        self.responder = receiver.LinkResponder.__new__(receiver.LinkResponder)
        self.responder._lock = threading.RLock()
        self.got = []
        self.responder.extras_callback = lambda peer, message: self.got.append((peer, message["type"]))
        caps = frozenset({protocol.CAP_SCOTTY_EXTRAS})
        self.link = mock.Mock(caps=caps, own_caps=caps, peer_id=b"\x01" * 16)

    def test_passed_on_when_both_ends_list_the_capability(self):
        self.responder._on_extras(self.link, protocol.lock_msg())
        self.assertEqual(self.got, [(b"\x01" * 16, protocol.MSG_LOCK)])

    def test_dropped_without_the_capability_on_either_end(self):
        self.link.caps = frozenset({"clipboard"})
        self.responder._on_extras(self.link, protocol.lock_msg())
        self.link.caps, self.link.own_caps = self.link.own_caps, frozenset()
        self.responder._on_extras(self.link, protocol.lock_msg())
        self.assertEqual(self.got, [])

    def test_post_extras_reaches_only_capable_links(self):
        capable = mock.Mock(caps=frozenset({protocol.CAP_SCOTTY_EXTRAS}), own_caps=frozenset({protocol.CAP_SCOTTY_EXTRAS}))
        capable.post.return_value = True
        stock = mock.Mock(caps=frozenset({"clipboard"}), own_caps=frozenset({protocol.CAP_SCOTTY_EXTRAS}))
        self.responder._links = {b"a": capable, b"b": stock}
        self.assertEqual(self.responder.post_extras(protocol.lock_msg()), 1)
        stock.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
