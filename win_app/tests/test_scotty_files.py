"""Fork (Scotty): the files bridge between the clipboard, the file channel and the app, with a fake
clipboard and a real file channel on loopback; and the hooks in the owner, the receiver and the
sender that carry the manifest."""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import scotty_files
from core import filechannel, owner as owner_module, protocol


class FakeClipboard:
    def __init__(self, files=None):
        self.files = files
        self.stamp = 1
        self.set = []

    def get_files(self):
        return self.files

    def set_files(self, paths, move=False):
        self.set.append(paths)
        self.moved = move
        return True

    def change_stamp(self):
        return self.stamp


def loopback_server(port):
    return filechannel.FileServer(host="127.0.0.1", port=0)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="scotty-bridge-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.source = os.path.join(self.base, "source")
        os.makedirs(os.path.join(self.source, "Folder"))
        with open(os.path.join(self.source, "Folder", "a.txt"), "wb") as out:
            out.write(b"hello")
        with open(os.path.join(self.source, "big.bin"), "wb") as out:
            out.write(os.urandom(3 * 1024 * 1024))
        self.drop = os.path.join(self.base, "drop")
        self.notices = []
        self.done = threading.Event()

    def bridge(self, clipboard, **settings):
        values = {"enabled": True, "drop_folder": self.drop, "max_bytes": 1024 ** 3}
        values.update(settings)

        def notify(event):
            self.notices.append(event)
            if event["state"] in ("done", "failed", "cancelled"):
                self.done.set()

        bridge = scotty_files.FilesBridge(values, clipboard, notify, server_factory=loopback_server)
        bridge.start()
        self.addCleanup(bridge.stop)
        return bridge

    def wire(self, manifest):
        return protocol.read_files(protocol.parse_message(protocol.dumps_message(manifest)))

    def test_copied_files_travel_and_land_on_the_receivers_clipboard(self):
        sender = self.bridge(FakeClipboard([os.path.join(self.source, "Folder"), os.path.join(self.source, "big.bin")]))
        receiver_clipboard = FakeClipboard()
        receiver = self.bridge(receiver_clipboard)
        manifest = sender.outgoing("127.0.0.1")
        self.assertEqual(manifest["type"], protocol.MSG_FILES)
        receiver.incoming("127.0.0.1", self.wire(manifest))
        self.assertTrue(self.done.wait(20))
        self.assertEqual(self.notices[-1]["state"], "done", self.notices[-1])
        self.assertIn("Ctrl+V", self.notices[-1]["message"])
        landed = receiver_clipboard.set[0]
        self.assertEqual([os.path.basename(path) for path in landed], ["Folder", "big.bin"])
        with open(os.path.join(landed[0], "a.txt"), "rb") as arrived:
            self.assertEqual(arrived.read(), b"hello")
        receiving = [notice for notice in self.notices if notice["state"] == "receiving"]
        self.assertTrue(receiving)
        self.assertEqual(receiving[-1]["done_bytes"], receiving[-1]["total_bytes"])

    def test_received_files_go_on_the_clipboard_as_cut_so_pasting_moves_them(self):
        sender = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]))
        receiver_clipboard = FakeClipboard()
        receiver = self.bridge(receiver_clipboard)
        receiver.incoming("127.0.0.1", self.wire(sender.outgoing("127.0.0.1")))
        self.assertTrue(self.done.wait(20))
        self.assertTrue(receiver_clipboard.moved)
        self.assertIn("move", self.notices[-1]["message"])

    def test_the_sending_pc_sees_progress_and_the_end(self):
        sender = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]))
        receiver = self.bridge(FakeClipboard())
        receiver.incoming("127.0.0.1", self.wire(sender.outgoing("127.0.0.1")))
        self.assertTrue(self.done.wait(20))
        for _ in range(100):
            if any(notice["state"] == "sent" for notice in self.notices):
                break
            threading.Event().wait(0.05)
        states = [notice["state"] for notice in self.notices]
        self.assertIn("sending", states)
        self.assertIn("sent", states)

    def test_a_used_up_offer_is_not_offered_again(self):
        clipboard = FakeClipboard([os.path.join(self.source, "Folder")])
        sender = self.bridge(clipboard)
        receiver = self.bridge(FakeClipboard())
        first = sender.outgoing("127.0.0.1")
        receiver.incoming("127.0.0.1", self.wire(first))
        self.assertTrue(self.done.wait(20))
        for _ in range(100):
            if not sender._server.has_offer(protocol.read_files(first)["transfer"]):
                break
            threading.Event().wait(0.05)
        self.assertNotEqual(first["data"]["transfer"], sender.outgoing("127.0.0.1")["data"]["transfer"])

    def test_an_unknown_peer_address_offers_nothing(self):
        # From the security review: an offer with no address would be served to anyone.
        bridge = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]))
        self.assertIsNone(bridge.outgoing(None))
        self.assertIsNone(bridge.outgoing(""))

    def test_a_flood_of_manifests_runs_one_fetch_at_a_time(self):
        started, release = [], threading.Event()

        def slow_fetch(host, read, *args, **kwargs):
            started.append(read["count"])
            release.wait(5)
            raise filechannel.TransferCancelled("stopped")

        bridge = self.bridge(FakeClipboard())
        bridge._fetch = slow_fetch
        manifest = {"count": 0, "names": ["x"], "total_bytes": 0}
        for count in range(50):
            bridge.incoming("127.0.0.1", dict(manifest, count=count))
        threading.Event().wait(0.3)
        release.set()
        for _ in range(100):
            if bridge._worker is None:
                break
            threading.Event().wait(0.05)
        self.assertLessEqual(len(started), 2)
        self.assertEqual(started[-1], 49)

    def test_cancel_also_stops_what_this_pc_is_sending(self):
        bridge = self.bridge(FakeClipboard())
        with mock.patch.object(bridge._server, "cancel_sends") as cancel_sends:
            bridge.cancel()
        cancel_sends.assert_called_once_with()

    def test_nothing_copied_or_files_off_sends_nothing(self):
        self.assertIsNone(self.bridge(FakeClipboard(None)).outgoing("127.0.0.1"))
        off = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]), enabled=False)
        self.assertIsNone(off.outgoing("127.0.0.1"))
        self.assertFalse(off.advertised)

    def test_over_the_senders_limit_is_refused_with_a_notice(self):
        bridge = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]), max_bytes=1024)
        self.assertIsNone(bridge.outgoing("127.0.0.1"))
        self.assertEqual(self.notices[-1]["state"], "refused")
        self.assertIn("Raise it", self.notices[-1]["message"])

    def test_crossing_again_without_copying_reuses_the_offer(self):
        clipboard = FakeClipboard([os.path.join(self.source, "Folder")])
        bridge = self.bridge(clipboard)
        first, second = bridge.outgoing("127.0.0.1"), bridge.outgoing("127.0.0.1")
        self.assertEqual(first["data"]["transfer"], second["data"]["transfer"])
        clipboard.stamp += 1
        self.assertNotEqual(first["data"]["transfer"], bridge.outgoing("127.0.0.1")["data"]["transfer"])

    def test_more_top_level_items_than_a_manifest_holds_is_refused_with_a_hint(self):
        paths = []
        for index in range(protocol.FILES_MAX_NAMES + 1):
            path = os.path.join(self.source, f"f{index}.txt")
            with open(path, "wb") as out:
                out.write(b"x")
            paths.append(path)
        self.assertIsNone(self.bridge(FakeClipboard(paths)).outgoing("127.0.0.1"))
        self.assertIn("one folder", self.notices[-1]["message"])

    def test_cancel_stops_the_fetch_and_says_so(self):
        sender = self.bridge(FakeClipboard([os.path.join(self.source, "big.bin")]))
        manifest = self.wire(sender.outgoing("127.0.0.1"))
        receiver_clipboard = FakeClipboard()
        receiver = self.bridge(receiver_clipboard)
        started = threading.Event()
        real_fetch = filechannel.fetch

        def slow_fetch(*args, **kwargs):
            def progress(done, total, path):
                started.set()
                kwargs["cancel"].wait(5)
            kwargs["progress"] = progress
            return real_fetch(*args, **kwargs)

        receiver._fetch = slow_fetch
        receiver.incoming("127.0.0.1", manifest)
        self.assertTrue(started.wait(10))
        receiver.cancel()
        self.assertTrue(self.done.wait(10))
        self.assertEqual(self.notices[-1]["state"], "cancelled")
        self.assertEqual(receiver_clipboard.set, [])
        self.assertFalse(os.path.exists(os.path.join(self.drop, filechannel.STAGING)))

    def test_a_port_in_use_is_reported_not_raised(self):
        def busy(port):
            raise OSError("in use")
        bridge = scotty_files.FilesBridge({"enabled": True, "drop_folder": self.drop, "max_bytes": 1},
                                          FakeClipboard(), self.notices.append, server_factory=busy)
        self.assertFalse(bridge.start())
        self.assertFalse(bridge.advertised)
        self.assertIn("in use", self.notices[-1]["message"])

    def test_turning_files_off_stops_listening(self):
        bridge = self.bridge(FakeClipboard())
        self.assertTrue(bridge.advertised)
        bridge.update(dict(bridge.settings, enabled=False))
        self.assertFalse(bridge.advertised)
        bridge.update(dict(bridge.settings, enabled=True))
        self.assertTrue(bridge.advertised)

    def test_a_name_keeps_its_capitals_in_notices(self):
        self.assertEqual(scotty_files._first_upper(scotty_files._describe(
            {"count": 1, "names": ["iPhone Backup.zip"], "total_bytes": 10})), "“iPhone Backup.zip” (10 bytes)")


class OwnerFilesRuleTests(unittest.TestCase):
    def owner(self, clock):
        owner = owner_module.Owner.__new__(owner_module.Owner)
        owner._clock = lambda: clock[0]
        owner._files_let_go = {}
        owner._let_go = {}
        owner._pressed = {}
        owner._swallow = set()
        owner.route = 1
        return owner

    def test_only_a_machine_just_let_go_may_send_files_and_only_once(self):
        clock = [100.0]
        owner = self.owner(clock)
        self.assertFalse(owner.files_arrived(b"B", 100.0))
        owner._let_go_of(b"B", b"A")
        self.assertTrue(owner.files_arrived(b"B", 101.0))
        self.assertFalse(owner.files_arrived(b"B", 101.5))

    def test_files_and_clipboard_of_one_let_go_do_not_use_up_each_other(self):
        clock = [100.0]
        owner = self.owner(clock)
        owner._let_go_of(b"B", b"A")
        owner._let_go.pop(b"B")
        self.assertTrue(owner.files_arrived(b"B", 100.5))

    def test_too_late_is_refused(self):
        clock = [100.0]
        owner = self.owner(clock)
        owner._let_go_of(b"B", b"A")
        self.assertFalse(owner.files_arrived(b"B", 100.0 + owner_module.CLIPBOARD_AFTER + 1))


class ReceiverHookTests(unittest.TestCase):
    """The machine being driven takes a manifest only from the machine driving it, and only when
    both ends announced clipboard_files."""

    def setUp(self):
        from core import receiver
        self.responder = receiver.LinkResponder.__new__(receiver.LinkResponder)
        self.responder._lock = threading.RLock()
        self.taken = []
        self.responder.files = mock.Mock(incoming=lambda host, read: self.taken.append((host, read)))
        caps = frozenset({protocol.CAP_CLIPBOARD_FILES})
        self.link = mock.Mock(caps=caps, own_caps=caps, host="192.168.1.20")
        self.link.name = "Laptop A"
        self.message = protocol.files_msg(bytes(16), bytes(range(32)), protocol.FILES_PORT, ["a.txt"], 1, 1)

    def test_taken_from_the_owner(self):
        self.responder._owner = self.link
        self.responder._on_files(self.link, self.message)
        self.assertEqual([host for host, _ in self.taken], ["192.168.1.20"])

    def test_ignored_from_a_machine_that_does_not_own_this_one(self):
        self.responder._owner = None
        self.responder._on_files(self.link, self.message)
        self.responder._owner = mock.Mock()
        self.responder._on_files(self.link, self.message)
        self.assertEqual(self.taken, [])

    def test_ignored_without_the_capability_on_either_end(self):
        self.responder._owner = self.link
        self.link.caps = frozenset({"clipboard"})
        self.responder._on_files(self.link, self.message)
        self.link.caps, self.link.own_caps = self.link.own_caps, frozenset()
        self.responder._on_files(self.link, self.message)
        self.assertEqual(self.taken, [])

    def test_a_malformed_manifest_is_ignored(self):
        self.responder._owner = self.link
        self.responder._on_files(self.link, {"type": protocol.MSG_FILES, "data": {"names": ["../x"]}})
        self.assertEqual(self.taken, [])


class FilesSettingsTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="scotty-settings-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.path = app_config.files_settings_path(app_config.Path(self.base) / "settings.json")

    def test_defaults_when_there_is_no_file(self):
        settings = app_config.load_files_settings(self.path)
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["max_bytes"], 2 * 1024 ** 3)
        self.assertTrue(settings["drop_folder"].endswith(os.path.join("Downloads", "Scotty Drop")))

    def test_saved_values_come_back_and_the_limit_can_go_far_past_2_gb(self):
        settings = dict(app_config.load_files_settings(self.path), enabled=False, max_bytes=500 * 1024 ** 3,
                        drop_folder=os.path.join(self.base, "Elsewhere"))
        app_config.save_files_settings(self.path, settings)
        self.assertEqual(app_config.load_files_settings(self.path), settings)
        self.assertEqual(os.listdir(self.base), ["scotty.json"])

    def test_bad_values_fall_back_one_by_one(self):
        with open(self.path, "w", encoding="utf-8") as out:
            out.write('{"files": {"enabled": "yes", "drop_folder": "relative", "max_bytes": 0}}')
        self.assertEqual(app_config.load_files_settings(self.path), app_config.files_defaults())
        with open(self.path, "w", encoding="utf-8") as out:
            out.write("not json")
        self.assertEqual(app_config.load_files_settings(self.path), app_config.files_defaults())


if __name__ == "__main__":
    unittest.main()
