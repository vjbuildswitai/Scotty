"""Copied files on the Windows clipboard (fork: Scotty): the CF_HDROP block codec, and reading and
writing it over upstream's fake user32/kernel32, whose handles are real ctypes buffers."""

import os
import struct
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import clipboard_win
from clipboard_win import CF_HDROP, CF_UNICODETEXT, build_hdrop, parse_hdrop
from test_clipboard_win import FakeMem32, FakeWin32

PATHS = [r"C:\Users\Vijayaraj-Dev\Documents\report.pdf", r"D:\Projects\Holiday photos", "D:\\தமிழ் பாடல்கள்",
         r"\\NAS\share\video.mp4"]


def ansi_block(paths):
    return struct.pack("<IiiII", 20, 0, 0, 0, 0) + ("\x00".join(paths) + "\x00\x00").encode("cp1252")


class SequencedWin32(FakeWin32):
    sequence = 7

    def GetClipboardSequenceNumber(self):
        return self.sequence


class HdropCodecTests(unittest.TestCase):
    def test_round_trip_keeps_order_and_unicode(self):
        self.assertEqual(parse_hdrop(build_hdrop(PATHS)), PATHS)

    def test_the_block_is_what_explorer_writes(self):
        block = build_hdrop([r"C:\a"])
        self.assertEqual(struct.unpack_from("<IiiII", block), (20, 0, 0, 0, 1))
        self.assertEqual(block[20:], "C:\\a\x00\x00".encode("utf-16-le"))

    def test_an_ansi_list_from_an_older_app_is_read(self):
        self.assertEqual(parse_hdrop(ansi_block([r"C:\old app\caf\u00e9.txt"])), [r"C:\old app\caf\u00e9.txt"])

    def test_a_list_after_padding_is_found_by_its_offset(self):
        block = struct.pack("<IiiII", 24, 5, 6, 0, 1) + b"\xff" * 4 + "C:\\x\x00\x00".encode("utf-16-le")
        self.assertEqual(parse_hdrop(block), [r"C:\x"])

    def test_trailing_bytes_after_the_double_nul_are_ignored(self):
        self.assertEqual(parse_hdrop(build_hdrop([r"C:\x"]) + b"\x00\x00junk"), [r"C:\x"])

    def test_junk_is_refused_without_raising(self):
        wide = struct.pack("<IiiII", 20, 0, 0, 0, 1)
        for junk in (
            b"",
            b"\x14\x00\x00\x00",
            wide,
            wide + "C:\\x".encode("utf-16-le"),
            wide + "\x00\x00".encode("utf-16-le"),
            wide + "relative\\path\x00\x00".encode("utf-16-le"),
            struct.pack("<IiiII", 4, 0, 0, 0, 1) + "C:\\x\x00\x00".encode("utf-16-le"),
            struct.pack("<IiiII", 999, 0, 0, 0, 1) + "C:\\x\x00\x00".encode("utf-16-le"),
            wide + b"\x00\xd8\x00\x00\x00\x00",
        ):
            with self.subTest(junk=junk):
                self.assertIsNone(parse_hdrop(junk))

    def test_too_many_paths_are_refused(self):
        many = [rf"C:\f{i}" for i in range(clipboard_win.HDROP_MAX_PATHS + 1)]
        with self.assertRaises(ValueError):
            build_hdrop(many)
        block = struct.pack("<IiiII", 20, 0, 0, 0, 1) + ("\x00".join(many) + "\x00\x00").encode("utf-16-le")
        self.assertIsNone(parse_hdrop(block))

    def test_build_refuses_what_parse_would_refuse(self):
        for bad in ([], ["relative"], ["C:"], [r"C:\a" + "\x00"], [None]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_hdrop(bad)


class FilesClipboardTests(unittest.TestCase):
    def setUp(self):
        self.mem32 = FakeMem32()

    def windows(self, win32):
        return mock.patch.multiple(clipboard_win, _IS_WINDOWS=True, user32=win32, kernel32=self.mem32)

    def test_get_files_reads_explorers_copy(self):
        win32 = SequencedWin32(self.mem32, {CF_HDROP: self.mem32.handle_for(build_hdrop(PATHS))})
        with self.windows(win32):
            self.assertEqual(clipboard_win.get_files(), PATHS)

    def test_no_copied_files_is_none_and_does_not_open_the_clipboard(self):
        win32 = SequencedWin32(self.mem32, {CF_UNICODETEXT: self.mem32.handle_for("just text")})
        win32.OpenClipboard = mock.Mock(side_effect=AssertionError("opened"))
        with self.windows(win32):
            self.assertIsNone(clipboard_win.get_files())

    def test_contention_gives_none_rather_than_raising(self):
        win32 = SequencedWin32(self.mem32, {CF_HDROP: self.mem32.handle_for(build_hdrop(PATHS))})
        with self.windows(win32), mock.patch.object(clipboard_win, "_open_clipboard", return_value=False):
            self.assertIsNone(clipboard_win.get_files())

    def test_a_broken_block_is_none(self):
        win32 = SequencedWin32(self.mem32, {CF_HDROP: self.mem32.handle_for(b"\x14\x00\x00\x00junk")})
        with self.windows(win32):
            self.assertIsNone(clipboard_win.get_files())

    def test_set_files_puts_one_hdrop_on_an_emptied_clipboard_it_owns(self):
        win32 = SequencedWin32(self.mem32, {CF_UNICODETEXT: self.mem32.handle_for("old")})
        with self.windows(win32):
            self.assertTrue(clipboard_win.set_files(PATHS))
        self.assertEqual(win32.emptied, 1)
        self.assertEqual(win32.open_owner, 123)
        self.assertEqual(win32.destroyed, [123])
        self.assertEqual(set(win32.formats), {CF_HDROP})
        self.assertEqual(parse_hdrop(self.mem32.contents(win32.formats[CF_HDROP])), PATHS)

    def test_received_files_count_as_written_from_the_peer(self):
        win32 = SequencedWin32(self.mem32)
        with self.windows(win32), mock.patch.multiple(clipboard_win, _synced_sequence=None, _written_sequence=None):
            clipboard_win.set_files(PATHS)
            self.assertEqual(clipboard_win.write_stamp(), 7)
            self.assertEqual(clipboard_win._synced_sequence, 7)

    def test_set_then_get_round_trips(self):
        win32 = SequencedWin32(self.mem32)
        with self.windows(win32):
            self.assertTrue(clipboard_win.set_files(PATHS))
            self.assertEqual(clipboard_win.get_files(), PATHS)

    def test_a_failed_empty_writes_nothing(self):
        win32 = SequencedWin32(self.mem32)
        win32.EmptyClipboard = lambda: 0
        with self.windows(win32):
            self.assertFalse(clipboard_win.set_files(PATHS))
        self.assertEqual(win32.formats, {})
        self.assertEqual(win32.destroyed, [123])

    def test_bad_paths_never_raise(self):
        with self.windows(SequencedWin32(self.mem32)):
            self.assertFalse(clipboard_win.set_files(["relative"]))

    def test_off_windows_both_are_inert(self):
        with mock.patch.object(clipboard_win, "_IS_WINDOWS", False):
            self.assertIsNone(clipboard_win.get_files())
            self.assertFalse(clipboard_win.set_files(PATHS))


if __name__ == "__main__":
    unittest.main()
