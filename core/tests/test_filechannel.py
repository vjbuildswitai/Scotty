"""The file channel (fork: Scotty) end to end over loopback: real sockets, real files in temporary
folders, and the ways a transfer must fail without leaving anything behind."""

import datetime
import hashlib
import os
import shutil
import socket
import tempfile
import threading
import unittest

from core import filechannel, protocol
from core.filechannel import FileServer, TransferCancelled, TransferError, fetch, list_paths

DAY = datetime.date(2026, 11, 18)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as out:
        out.write(data)


def tree(root):
    """{relative path: bytes, or None for a folder} under root."""
    found = {}
    for folder, dirs, files in os.walk(root):
        for name in dirs:
            found[os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")] = None
        for name in files:
            with open(os.path.join(folder, name), "rb") as source:
                found[os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")] = source.read()
    return found


class FileChannelTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="scotty-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.source = os.path.join(self.base, "source")
        self.drop = os.path.join(self.base, "Beamer Drop")
        self.big = os.urandom(3 * filechannel.CHUNK_BYTES + 12345)
        write(os.path.join(self.source, "report.pdf"), b"%PDF report")
        write(os.path.join(self.source, "Holiday photos", "day 1", "IMG_0001.jpg"), self.big)
        write(os.path.join(self.source, "Holiday photos", "தமிழ் notes.txt"), "வணக்கம்".encode("utf-8"))
        write(os.path.join(self.source, "Holiday photos", "empty.txt"), b"")
        os.makedirs(os.path.join(self.source, "Holiday photos", "empty folder"))
        self.server = FileServer(host="127.0.0.1", port=0).start()
        self.addCleanup(self.server.close)

    def paths(self, *names):
        return [os.path.join(self.source, name) for name in names]

    def manifest(self, offer):
        return protocol.read_files(protocol.parse_message(protocol.dumps_message(self.server.manifest(offer))))

    def fetch(self, manifest, **kwargs):
        kwargs.setdefault("max_bytes", 2 * 1024 ** 3)
        kwargs.setdefault("today", DAY)
        return fetch("127.0.0.1", manifest, self.drop, **kwargs)

    def assertNothingLeft(self):
        self.assertFalse(os.path.exists(os.path.join(self.drop, filechannel.STAGING)))
        self.assertFalse(os.path.exists(os.path.join(self.drop, DAY.isoformat())))

    def test_files_and_folders_arrive_whole_under_a_dated_folder(self):
        offer = self.server.offer(self.paths("Holiday photos", "report.pdf"))
        manifest = self.manifest(offer)
        self.assertEqual(manifest["names"], ["Holiday photos", "report.pdf"])
        self.assertEqual(manifest["count"], 4)
        self.assertEqual(manifest["total_bytes"], len(self.big) + len("வணக்கம்".encode("utf-8")) + len(b"%PDF report"))
        seen = []
        landed = self.fetch(manifest, progress=lambda done, total, path: seen.append((done, total)))
        day = os.path.join(self.drop, DAY.isoformat())
        self.assertEqual(landed, [os.path.join(day, "Holiday photos"), os.path.join(day, "report.pdf")])
        self.assertEqual(tree(day), {f"Holiday photos/{k}" if k else "Holiday photos": v
                                     for k, v in tree(os.path.join(self.source, "Holiday photos")).items()}
                         | {"Holiday photos": None, "report.pdf": b"%PDF report"})
        self.assertEqual(seen[-1], (manifest["total_bytes"], manifest["total_bytes"]))
        self.assertEqual([done for done, _ in seen], sorted(done for done, _ in seen))
        self.assertFalse(os.path.exists(os.path.join(self.drop, filechannel.STAGING)))

    def test_a_taken_name_gets_a_number_and_nothing_is_overwritten(self):
        day = os.path.join(self.drop, DAY.isoformat())
        write(os.path.join(day, "report.pdf"), b"older")
        os.makedirs(os.path.join(day, "Holiday photos"))
        landed = self.fetch(self.manifest(self.server.offer(self.paths("report.pdf", "Holiday photos"))))
        self.assertEqual([os.path.basename(path) for path in landed], ["report (2).pdf", "Holiday photos (2)"])
        with open(os.path.join(day, "report.pdf"), "rb") as kept:
            self.assertEqual(kept.read(), b"older")

    def test_the_same_offer_can_be_fetched_twice_with_fresh_keys(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf")))
        first, second = self.fetch(manifest), self.fetch(manifest)
        self.assertNotEqual(first, second)

    def test_over_the_limit_nothing_is_fetched(self):
        manifest = self.manifest(self.server.offer(self.paths("Holiday photos")))
        with self.assertRaisesRegex(TransferError, "over this PC's limit"):
            self.fetch(manifest, max_bytes=1024, connect=lambda *a, **k: self.fail("connected"))
        self.assertNothingLeft()

    def test_a_wrong_ticket_cannot_open_the_channel(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf")))
        manifest["ticket"] = bytes(32)
        with self.assertRaises(TransferError):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_an_unknown_or_expired_transfer_is_refused(self):
        clock = [1000.0]
        self.server._clock = lambda: clock[0]
        offer = self.server.offer(self.paths("report.pdf"))
        manifest = self.manifest(offer)
        clock[0] += filechannel.OFFER_SECONDS + 1
        with self.assertRaisesRegex(TransferError, "closed the file connection"):
            self.fetch(manifest)
        manifest["transfer"] = bytes(16)
        with self.assertRaises(TransferError):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_only_the_peer_it_was_offered_to_may_fetch(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf"), allowed_host="192.0.2.7"))
        with self.assertRaises(TransferError):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_files_changed_after_copying_fail_cleanly(self):
        manifest = self.manifest(self.server.offer(self.paths("Holiday photos")))
        write(os.path.join(self.source, "Holiday photos", "day 1", "IMG_0001.jpg"), b"shorter now")
        with self.assertRaisesRegex(TransferError, "changed"):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_a_file_that_grows_after_copying_is_not_sent_cut_short(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf")))
        write(os.path.join(self.source, "report.pdf"), b"%PDF report, now longer")
        with self.assertRaisesRegex(TransferError, "changed after it was copied"):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_a_file_that_shrinks_mid_transfer_fails_cleanly(self):
        offer = self.server.offer(self.paths("report.pdf"))
        manifest = self.manifest(offer)
        write(os.path.join(self.source, "report.pdf"), b"%PDF")
        offer.entries[0].size = len(b"%PDF report")
        offer.entries[0].mtime_ns = None
        with self.assertRaisesRegex(TransferError, "changed after it was copied|got shorter"):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_a_listing_that_climbs_out_of_the_drop_folder_is_refused(self):
        for bad in ("Holiday photos/../../escape.txt", "report.pdf", "C:/Windows/evil.dll", "Holiday photos//x"):
            with self.subTest(bad=bad):
                offer = self.server.offer(self.paths("Holiday photos"))
                offer.entries[1].path = bad
                with self.assertRaisesRegex(TransferError, "outside what it offered"):
                    self.fetch(self.manifest(offer))
                self.assertNothingLeft()
        self.assertFalse(os.path.exists(os.path.join(self.base, "escape.txt")))

    def test_cancel_mid_transfer_leaves_nothing(self):
        manifest = self.manifest(self.server.offer(self.paths("Holiday photos")))
        cancel = threading.Event()

        def progress(done, total, path):
            if done >= filechannel.CHUNK_BYTES:
                cancel.set()

        with self.assertRaises(TransferCancelled):
            self.fetch(manifest, progress=progress, cancel=cancel)
        self.assertNothingLeft()

    def test_a_finished_transfer_does_not_touch_the_callers_cancel(self):
        cancel = threading.Event()
        self.fetch(self.manifest(self.server.offer(self.paths("report.pdf"))), cancel=cancel)
        self.assertFalse(cancel.is_set())

    def test_an_unreachable_sender_says_what_to_check(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf")))
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        manifest["port"] = probe.getsockname()[1]
        probe.close()
        with self.assertRaisesRegex(TransferError, "firewall allows TCP"):
            self.fetch(manifest)
        self.assertNothingLeft()

    def test_garbage_on_the_port_does_not_hurt_the_server(self):
        with socket.create_connection(("127.0.0.1", self.server.port)) as junk:
            junk.sendall(b"GET / HTTP/1.1\r\n\r\n" + b"x" * 100)
        self.assertTrue(self.fetch(self.manifest(self.server.offer(self.paths("report.pdf")))))

    def test_hashes_match_for_a_multi_chunk_file(self):
        landed = self.fetch(self.manifest(self.server.offer(self.paths("Holiday photos"))))
        with open(os.path.join(landed[0], "day 1", "IMG_0001.jpg"), "rb") as arrived:
            self.assertEqual(hashlib.sha256(arrived.read()).digest(), hashlib.sha256(self.big).digest())


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="scotty-list-")
        self.addCleanup(shutil.rmtree, self.base, True)

    @unittest.skipIf(os.name == "nt", "Windows cannot create such a name; a colon makes an alternate data stream")
    def test_names_windows_cannot_create_are_refused_up_front(self):
        write(os.path.join(self.base, "folder", "bad:name.txt"), b"x")
        with self.assertRaisesRegex(TransferError, "not allowed on Windows"):
            list_paths([os.path.join(self.base, "folder")])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks here")
    def test_symbolic_links_are_skipped_so_a_loop_cannot_run_forever(self):
        folder = os.path.join(self.base, "folder")
        write(os.path.join(folder, "real.txt"), b"x")
        try:
            os.symlink(folder, os.path.join(folder, "loop"), target_is_directory=True)
        except OSError:
            self.skipTest("cannot create symlinks here")
        names, entries = list_paths([folder])
        self.assertEqual([entry.path for entry in entries], ["folder", "folder/real.txt"])

    def test_two_copied_items_with_one_name_are_refused(self):
        write(os.path.join(self.base, "a", "same.txt"), b"1")
        write(os.path.join(self.base, "b", "SAME.txt"), b"2")
        with self.assertRaisesRegex(TransferError, "both called"):
            list_paths([os.path.join(self.base, "a", "same.txt"), os.path.join(self.base, "b", "SAME.txt")])

    def test_something_deleted_since_copying_is_reported(self):
        with self.assertRaisesRegex(TransferError, "no longer there"):
            list_paths([os.path.join(self.base, "gone.txt")])


if __name__ == "__main__":
    unittest.main()
