"""Files across the edge (fork, WIRE.md section 11): the `files` manifest, the name rules that keep
a received file inside its drop folder, and the `clipboard_files` gate on both ends of a link.
"""

import threading
import unittest

from core import link as link_module
from core import protocol
from core import receiver

TRANSFER = bytes(range(16))
TICKET = bytes(range(100, 132))


def manifest(**changes):
    data = {
        "transfer": protocol.id_text(TRANSFER),
        "ticket": protocol.id_text(TICKET),
        "port": protocol.FILES_PORT,
        "names": ["Holiday photos", "report.pdf"],
        "count": 42,
        "total_bytes": 3 * 1024 ** 3,
    }
    data.update(changes)
    return {"type": protocol.MSG_FILES, "data": data}


class FileNameTests(unittest.TestCase):
    def test_ordinary_names_are_valid(self):
        for name in ("report.pdf", "Holiday photos", "தமிழ்.txt", ".gitignore", "a" * 255, "CONSOLE"):
            self.assertTrue(protocol.valid_file_name(name), name)

    def test_names_that_could_escape_or_break_on_windows_are_refused(self):
        for name in ("", ".", "..", "a/b", "a\\b", "C:", "x:y", "a*", "q?", "<a>", 'say"hi"', "pipe|", "tab\tname",
                     "nul\x00", "trailing.", "trailing ", "CON", "con.txt", "con.tents.txt", "Nul", "COM1", "lpt9.log", "COM\u00b9",
                     "a" * 256, "\ud800", None, 5):
            self.assertFalse(protocol.valid_file_name(name), repr(name))

    def test_names_that_disguise_themselves_are_refused(self):
        # From the security review: a right-to-left override shows "report‮fdp.exe" as
        # "reportexe.pdf"; zero-width marks hide characters; Windows ignores spaces before an
        # extension when it looks for device names; NTFS counts UTF-16 units, not characters.
        for name in ("report‮fdp.exe", "inv​oice.pdf", "a⁦b", "﻿bom.txt", "CON .txt", "nul  .log",
                     "\U0001f600" * 128):
            self.assertFalse(protocol.valid_file_name(name), repr(name))
        self.assertTrue(protocol.valid_file_name("a" * 255))
        self.assertTrue(protocol.valid_file_name("\U0001f600" * 127))
        self.assertTrue(protocol.valid_file_name("ICONS.txt"))

    def test_relative_paths_stay_inside(self):
        self.assertTrue(protocol.valid_relative_path("Holiday photos/day 1/IMG_0001.jpg"))
        for path in ("", "/abs", "a//b", "a/../b", "../a", "a/", "C:/x", "a\\b", "a/./b", None):
            self.assertFalse(protocol.valid_relative_path(path), repr(path))


class ManifestTests(unittest.TestCase):
    def test_round_trip(self):
        message = protocol.files_msg(TRANSFER, TICKET, protocol.FILES_PORT, ["Holiday photos", "report.pdf"], 42, 7)
        read = protocol.read_files(protocol.parse_message(protocol.dumps_message(message)))
        self.assertEqual(read, {"transfer": TRANSFER, "ticket": TICKET, "port": protocol.FILES_PORT,
                                "names": ["Holiday photos", "report.pdf"], "count": 42, "total_bytes": 7})

    def test_the_manifest_stays_small_enough_never_to_be_a_large_frame(self):
        names = [f"{i:02d}" + "த" * 80 for i in range(protocol.FILES_MAX_NAMES)]
        names = names[: protocol.FILES_NAMES_MAX_BYTES // len(names[0].encode("utf-8"))]
        message = protocol.files_msg(TRANSFER, TICKET, 1, names, protocol.FILES_MAX_COUNT, protocol.MAX_SAFE_INTEGER)
        self.assertLess(len(protocol.dumps_message(message)), protocol.SMALL_MESSAGE_BYTES)

    def test_builder_refuses_what_the_reader_would_drop(self):
        with self.assertRaises(ValueError):
            protocol.files_msg(TRANSFER, TICKET, 0, ["a"], 1, 1)
        with self.assertRaises(ValueError):
            protocol.files_msg(TRANSFER, TICKET, 1, ["../a"], 1, 1)

    def test_malformed_manifests_are_dropped_whole(self):
        bad = [
            manifest(transfer="short"),
            manifest(ticket=protocol.id_text(bytes(16))),
            manifest(ticket=protocol.id_text(TICKET) + "="),
            manifest(port=0),
            manifest(port=65536),
            manifest(port="24822"),
            manifest(names=[]),
            manifest(names="report.pdf"),
            manifest(names=["ok", "../escape"]),
            manifest(names=["Report.pdf", "report.PDF"]),
            manifest(names=[f"n{i}" for i in range(protocol.FILES_MAX_NAMES + 1)]),
            manifest(names=[f"{i:02d}" + "த" * 250 for i in range(30)]),
            manifest(count=-1),
            manifest(count=protocol.FILES_MAX_COUNT + 1),
            manifest(count=True),
            manifest(total_bytes=1.5),
            manifest(total_bytes=protocol.MAX_SAFE_INTEGER + 1),
            {"type": protocol.MSG_CLIPBOARD, "data": manifest()["data"]},
            {"type": protocol.MSG_FILES},
        ]
        for message in bad:
            self.assertIsNone(protocol.read_files(message), message)
        self.assertIsNotNone(protocol.read_files(manifest()))

    def test_a_duplicate_key_makes_it_malformed(self):
        plain = protocol.dumps_message(manifest()).replace(b'"count":42', b'"count":42,"count":43')
        self.assertIsNone(protocol.read_files(protocol.parse_message(plain)))


class GateTests(unittest.TestCase):
    """Stock Beamer and the Mac app never announce `clipboard_files`, so they never get a manifest."""

    def _outbound(self, caps):
        link = link_module.OutboundLink.__new__(link_module.OutboundLink)
        link._live = True
        link._secure_endpoint = False
        link._caps = frozenset(caps)
        link.queued = []
        link._enqueue = lambda message, seq: link.queued.append(message) or True
        return link

    def _inbound(self, caps):
        link = receiver._Link.__new__(receiver._Link)
        link.cond = threading.Condition()
        link.closed = threading.Event()
        link.caps = frozenset(caps)
        link.outbox = []
        return link

    def test_initiator_sends_only_to_a_capable_peer(self):
        stock = self._outbound({"clipboard", "clipboard_image"})
        self.assertTrue(stock.post(manifest()))
        self.assertEqual(stock.queued, [])
        fork = self._outbound({"clipboard", protocol.CAP_CLIPBOARD_FILES})
        self.assertTrue(fork.post(manifest()))
        self.assertEqual([m["type"] for m in fork.queued], [protocol.MSG_FILES])

    def test_responder_sends_only_to_a_capable_peer(self):
        stock = self._inbound({"clipboard"})
        self.assertTrue(stock.post(manifest()))
        self.assertEqual(stock.outbox, [])
        fork = self._inbound({protocol.CAP_CLIPBOARD_FILES})
        self.assertTrue(fork.post(manifest()))
        self.assertEqual([m["type"] for m in fork.outbox], [protocol.MSG_FILES])

    def test_the_capability_fits_in_hello(self):
        caps = ["clipboard", "clipboard_image", "gestures", "media_keys", "text", "settings", "design_sync", "layout",
                "profiles", "displays", "identify_screens", "ping_rtt", "motion_path", protocol.CAP_CLIPBOARD_FILES]
        self.assertLessEqual(len(caps), protocol.MAX_CAPS)
        hello = protocol.hello_v6(TRANSFER, "VIJAYARAJ-DEV", "windows", "1.5.21", caps, 24820)
        self.assertIn(protocol.CAP_CLIPBOARD_FILES, protocol.read_hello(protocol.parse_message(protocol.dumps_message(hello)))["caps"])


if __name__ == "__main__":
    unittest.main()
