"""The file channel (fork: Scotty) end to end over loopback: real sockets, real files in temporary
folders, and the ways a transfer must fail without leaving anything behind."""

import datetime
import hashlib
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

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
            if name == filechannel.OURS_MARKER:
                continue
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

    def test_an_offer_is_used_up_once_everything_arrived(self):
        offer = self.server.offer(self.paths("report.pdf"))
        manifest = self.manifest(offer)
        self.fetch(manifest)
        self.assertFalse(self.server.has_offer(offer.transfer))
        with self.assertRaises(TransferError):
            self.fetch(manifest)

    def test_a_cancelled_fetch_can_be_tried_again_with_fresh_keys(self):
        offer = self.server.offer(self.paths("Holiday photos"))
        manifest = self.manifest(offer)
        cancel = threading.Event()
        with self.assertRaises(TransferCancelled):
            self.fetch(manifest, cancel=cancel, progress=lambda done, total, path: done and cancel.set())
        self.assertTrue(self.server.has_offer(offer.transfer))
        self.assertEqual(len(self.fetch(manifest)), 1)

    def test_a_peer_named_by_host_name_is_matched_by_its_address(self):
        manifest = self.manifest(self.server.offer(self.paths("report.pdf"), allowed_host="localhost"))
        self.assertTrue(self.fetch(manifest))

    def test_a_host_name_that_cannot_be_looked_up_is_refused_up_front(self):
        with self.assertRaisesRegex(TransferError, "could not be looked up"):
            self.server.offer(self.paths("report.pdf"), allowed_host="no-such-host.invalid")

    def test_ipv4_mapped_and_zoned_addresses_compare_as_the_machine(self):
        self.assertEqual(filechannel._plain_address("::ffff:192.168.1.20"), "192.168.1.20")
        self.assertEqual(filechannel._plain_address("fe80::1%12"), "fe80::1")
        self.assertEqual(filechannel._plain_address("192.168.1.20"), "192.168.1.20")

    def test_every_received_file_is_marked_before_it_moves_into_place(self):
        marked = []
        landed = self.fetch(self.manifest(self.server.offer(self.paths("Holiday photos", "report.pdf"))), mark=marked.append)
        self.assertEqual(len(marked), 4)
        self.assertTrue(all(os.path.basename(os.path.dirname(path)).endswith(".parts") for path in marked))
        self.assertEqual([os.path.basename(path) for path in landed], ["Holiday photos", "report.pdf"])

    def closed_at_once(self, sock):
        sock.settimeout(5)
        try:
            return sock.recv(1) == b""
        except ConnectionResetError:
            return True

    def test_an_address_with_nothing_on_offer_gets_no_connection_at_all(self):
        with socket.create_connection(("127.0.0.1", self.server.port)) as probe:
            self.assertTrue(self.closed_at_once(probe))

    def test_one_address_holds_at_most_two_connections(self):
        self.server.offer(self.paths("report.pdf"), allowed_host="127.0.0.1")
        held = [socket.create_connection(("127.0.0.1", self.server.port)) for _ in range(filechannel.PER_ADDRESS)]
        try:
            threading.Event().wait(0.2)
            with socket.create_connection(("127.0.0.1", self.server.port)) as extra:
                self.assertTrue(self.closed_at_once(extra))
        finally:
            for sock in held:
                sock.close()

    def test_a_connection_that_trickles_its_greeting_is_dropped_at_the_deadline(self):
        # The review's slowloris: one byte every so often used to hold a slot for minutes.
        self.server.offer(self.paths("report.pdf"), allowed_host="127.0.0.1")
        with mock.patch.object(filechannel, "HANDSHAKE_SECONDS", 1.0):
            with socket.create_connection(("127.0.0.1", self.server.port)) as slow:
                started = time.monotonic()
                closed = False
                for _ in range(20):
                    try:
                        slow.sendall(b"S")
                    except OSError:
                        closed = True
                        break
                    slow.settimeout(0.4)
                    try:
                        if slow.recv(1) == b"":
                            closed = True
                            break
                    except socket.timeout:
                        pass
                    except OSError:
                        closed = True
                        break
                self.assertTrue(closed)
                self.assertLess(time.monotonic() - started, 4)

    def test_a_newer_copy_withdraws_the_older_one(self):
        older = self.manifest(self.server.offer(self.paths("report.pdf"), allowed_host="127.0.0.1"))
        self.server.offer(self.paths("Holiday photos"), allowed_host="127.0.0.1")
        with self.assertRaises(TransferError):
            self.fetch(older)
        self.assertNothingLeft()

    def test_a_listed_name_ending_in_part_never_loses_a_file(self):
        # The review's collision: "d/a.part" arriving before "d/a" used to be overwritten.
        write(os.path.join(self.source, "d", "a"), b"AAAA")
        write(os.path.join(self.source, "d", "a.part"), b"PPPP")
        offer = self.server.offer(self.paths("d"))
        offer.entries.sort(key=lambda entry: (not entry.is_dir, not entry.path.endswith(".part")))
        landed = self.fetch(self.manifest(offer))
        self.assertEqual(tree(landed[0]), {"a": b"AAAA", "a.part": b"PPPP"})

    def test_nested_json_from_the_other_end_is_a_clean_error(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        key_a, key_b = bytes(range(32)), bytes(range(32, 64))
        sender, receiver = filechannel._Channel(left, key_a, key_b), filechannel._Channel(right, key_b, key_a)
        writer = threading.Thread(target=sender.send, args=(filechannel.KIND_CONTROL, b"[" * 200000 + b"]" * 200000))
        writer.start()
        with self.assertRaises(TransferError):
            receiver.recv()
        writer.join(5)

    def test_the_sender_hears_progress_and_the_end(self):
        events = []
        self.server.on_progress = lambda offer, state, sent: events.append((state, sent))
        offer = self.server.offer(self.paths("Holiday photos"))
        self.fetch(self.manifest(offer))
        self.assertEqual(events[-1], ("sent", offer.total_bytes))
        self.assertIn("sending", [state for state, _ in events])

    def test_the_sender_can_cancel_what_it_is_sending(self):
        events, started = [], threading.Event()

        def heard(offer, state, sent):
            events.append(state)
            if state == "sending":
                started.set()
                self.server.cancel_sends()

        self.server.on_progress = heard
        offer = self.server.offer(self.paths("Holiday photos"))
        with self.assertRaises(TransferError):
            self.fetch(self.manifest(offer))
        self.assertTrue(started.is_set())
        self.assertEqual(events[-1], "stopped")
        self.assertFalse(self.server.has_offer(offer.transfer))
        self.assertNothingLeft()

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
        with self.assertRaises(TransferError):
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


class DropFolderCleaningTests(unittest.TestCase):
    """What was received and never pasted goes after `keep_days`; nothing else is ever touched."""

    def setUp(self):
        self.drop = tempfile.mkdtemp(prefix="scotty-clean-")
        self.addCleanup(shutil.rmtree, self.drop, True)

    def day(self, name, files=("a.txt",), ours=True):
        folder = os.path.join(self.drop, name)
        for file_name in files:
            write(os.path.join(folder, file_name), b"x")
        os.makedirs(folder, exist_ok=True)
        if ours:
            filechannel._mark_as_ours(folder)
        return folder

    def test_a_dated_folder_scotty_did_not_make_is_never_touched(self):
        # The review's case: the drop folder pointed at Downloads, which has its own 2026-10-01.
        self.day("2026-10-01", files=("holiday.jpg",), ours=False)
        self.day("2026-10-02", files=(), ours=False)
        filechannel.clean_drop_folder(self.drop, 7, today=DAY)
        self.assertEqual(sorted(os.listdir(self.drop)), ["2026-10-01", "2026-10-02"])

    def test_what_arrives_goes_in_a_folder_marked_as_scottys(self):
        filechannel._place(tempfile.mkdtemp(dir=self.drop), [], self.drop, DAY)
        self.assertTrue(os.path.isfile(os.path.join(self.drop, DAY.isoformat(), filechannel.OURS_MARKER)))

    def test_old_unpasted_files_go_and_recent_ones_stay(self):
        self.day("2026-11-01")
        self.day("2026-11-15")
        self.assertEqual(filechannel.clean_drop_folder(self.drop, 7, today=DAY), 1)
        self.assertEqual(sorted(os.listdir(self.drop)), ["2026-11-15"])

    def test_empty_dated_folders_go_once_their_day_is_over(self):
        self.day("2026-11-17", files=())
        self.day("2026-11-18", files=())
        filechannel.clean_drop_folder(self.drop, 7, today=DAY)
        self.assertEqual(os.listdir(self.drop), ["2026-11-18"])

    def test_nothing_but_scottys_own_dated_folders_is_touched(self):
        write(os.path.join(self.drop, "my notes.txt"), b"keep")
        write(os.path.join(self.drop, "2020-01-01 trip", "photo.jpg"), b"keep")
        write(os.path.join(self.drop, "Old", "2020-01-01", "x.txt"), b"keep")
        filechannel.clean_drop_folder(self.drop, 1, today=DAY)
        self.assertEqual(sorted(os.listdir(self.drop)), ["2020-01-01 trip", "Old", "my notes.txt"])

    def test_zero_days_keeps_everything(self):
        self.day("2020-01-01")
        filechannel.clean_drop_folder(self.drop, 0, today=DAY)
        self.assertEqual(os.listdir(self.drop), ["2020-01-01"])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks here")
    def test_a_link_named_like_a_day_is_never_followed(self):
        outside = tempfile.mkdtemp(prefix="scotty-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        write(os.path.join(outside, "precious.txt"), b"keep")
        try:
            os.symlink(outside, os.path.join(self.drop, "2020-01-01"), target_is_directory=True)
        except OSError:
            self.skipTest("cannot create symlinks here")
        filechannel.clean_drop_folder(self.drop, 1, today=DAY)
        self.assertTrue(os.path.exists(os.path.join(outside, "precious.txt")))

    def test_a_missing_drop_folder_is_fine(self):
        self.assertEqual(filechannel.clean_drop_folder(os.path.join(self.drop, "gone"), 7), 0)

    @unittest.skipUnless(os.name == "nt", "the mark of the web is an NTFS stream")
    def test_the_mark_of_the_web_is_written_on_windows(self):
        path = os.path.join(self.drop, "tool.exe")
        write(path, b"MZ")
        self.assertTrue(filechannel.mark_from_another_computer(path))
        with open(path + ":Zone.Identifier", encoding="ascii") as stream:
            self.assertIn("ZoneId=3", stream.read())
