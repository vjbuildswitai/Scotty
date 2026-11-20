"""Head turn's camera thread and its moves through the sender, with a fake camera (no webcam)."""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2])]

import headturn_win
from core import headturn, protocol
from core.headturn import HOME, Calibration, Reading, Screen

PEER = bytes(range(16))
PEER_TEXT = protocol.id_text(PEER)


class FakeSender:
    def __init__(self):
        self.clock = 0.0
        self.owner = None
        self.moves = []
        self.busy = False
        self.last_key_at = float("-inf")
        self.driven = lambda: False

    def now(self):
        return self.clock

    def input_busy(self):
        return self.busy

    def look_at(self, peer):
        if peer == self.owner:
            return False
        self.moves.append(peer)
        self.owner = peer
        return True


def calibration():
    return Calibration([Screen(HOME, 0.0, 0.3), Screen(PEER_TEXT, 0.32, 0.3)])


def drive(head, sender, yaw, seconds, fps=15):
    for _ in range(int(seconds * fps)):
        head.step(Reading(yaw, 0.3) if yaw is not None else None)
        sender.clock += 1 / fps


class StepTests(unittest.TestCase):
    def setUp(self):
        self.sender = FakeSender()
        self.events = []
        self.head = headturn_win.HeadTurn(self.sender, self.events.append, calibration=calibration(),
                                          blocked=lambda: False)

    def test_turning_to_the_other_screen_moves_input_there_and_back(self):
        drive(self.head, self.sender, 0.0, 1.0)
        drive(self.head, self.sender, 0.32, 1.5)
        self.assertEqual(self.sender.moves, [PEER])
        self.assertIn({"switched": PEER_TEXT}, self.events)
        drive(self.head, self.sender, 0.0, 2.0)
        self.assertEqual(self.sender.moves, [PEER, None])

    def test_typing_on_the_sender_blocks_the_move(self):
        for _ in range(45):
            self.sender.last_key_at = self.sender.clock
            self.head.step(Reading(0.32, 0.3))
            self.sender.clock += 1 / 15
        self.assertEqual(self.sender.moves, [])

    def test_a_pc_being_driven_by_another_never_moves_input(self):
        self.sender.driven = lambda: True
        drive(self.head, self.sender, 0.32, 3.0)
        self.assertEqual(self.sender.moves, [])

    def test_input_moved_by_the_pointer_is_followed(self):
        self.sender.owner = PEER  # crossed an edge while the person still faces home
        drive(self.head, self.sender, 0.0, 0.5)
        self.assertEqual(self.sender.moves, [])
        self.assertEqual(self.head.tracker.current, PEER_TEXT)

    def test_without_calibration_nothing_moves(self):
        head = headturn_win.HeadTurn(self.sender, self.events.append, blocked=lambda: False)
        drive(head, self.sender, 0.32, 3.0)
        self.assertEqual(self.sender.moves, [])

    def test_faced_changes_are_reported_once_each(self):
        drive(self.head, self.sender, 0.0, 1.0)
        drive(self.head, self.sender, None, 1.0)
        faced = [event["faced"] for event in self.events if "faced" in event]
        self.assertEqual(faced, [HOME, None])

    def test_calibration_samples_each_screen_then_builds_a_tracker(self):
        head = headturn_win.HeadTurn(self.sender, self.events.append, blocked=lambda: False)
        head.begin_sample(HOME)
        drive(head, self.sender, 0.01, headturn_win.CALIBRATION_SECONDS + 0.2)
        head.begin_sample(PEER_TEXT)
        drive(head, self.sender, 0.30, headturn_win.CALIBRATION_SECONDS + 0.2)
        self.assertIn({"calibrated": HOME, "ok": True}, self.events)
        self.assertIn({"calibrated": PEER_TEXT, "ok": True}, self.events)
        result = head.finish_calibration()
        self.assertEqual(result.targets, (HOME, PEER_TEXT))
        self.assertIsNotNone(head.tracker)

    def test_calibrating_without_a_face_fails_cleanly(self):
        head = headturn_win.HeadTurn(self.sender, self.events.append, blocked=lambda: False)
        head.begin_sample(HOME)
        drive(head, self.sender, None, headturn_win.CALIBRATION_SECONDS + 0.2)
        self.assertIn({"calibrated": HOME, "ok": False}, self.events)
        with self.assertRaises(headturn.CalibrationError):
            head.finish_calibration()


class FakeCamera:
    opened = 0
    closed = 0

    def __init__(self, index):
        FakeCamera.opened += 1

    def read(self):
        return object()

    def close(self):
        FakeCamera.closed += 1


class FakeFaces:
    def reading(self, frame):
        return Reading(0.0, 0.3)


class ThreadTests(unittest.TestCase):
    def test_blocked_camera_never_starts_the_thread(self):
        events = []
        head = headturn_win.HeadTurn(FakeSender(), events.append, blocked=lambda: True,
                                     camera_factory=lambda index: self.fail("camera opened"))
        self.assertFalse(head.start())
        self.assertEqual(events, [{"state": "blocked"}])
        self.assertFalse(head.running)

    def test_no_camera_reports_and_stops(self):
        events = []

        def missing(index):
            raise OSError("no camera")

        head = headturn_win.HeadTurn(FakeSender(), events.append, blocked=lambda: False,
                                     camera_factory=missing, faces_factory=FakeFaces)
        head.start()
        head._thread.join(timeout=2)
        self.assertEqual([e for e in events if "state" in e], [{"state": "no_camera"}, {"state": "stopped"}])

    def test_start_then_stop_opens_and_releases_the_camera(self):
        FakeCamera.opened = FakeCamera.closed = 0
        events = []
        seen = threading.Event()

        def on_event(event):
            events.append(event)
            if event.get("state") == "running":
                seen.set()

        head = headturn_win.HeadTurn(FakeSender(), on_event, calibration=calibration(), blocked=lambda: False,
                                     camera_factory=FakeCamera, faces_factory=FakeFaces)
        self.assertTrue(head.start())
        self.assertTrue(seen.wait(2))
        time.sleep(0.2)
        head.stop()
        self.assertFalse(head.running)
        self.assertEqual((FakeCamera.opened, FakeCamera.closed), (1, 1))
        self.assertEqual(events[-1], {"state": "stopped"})

    def test_an_app_callback_that_raises_does_not_kill_the_thread(self):
        def bad(event):
            raise RuntimeError("boom")

        head = headturn_win.HeadTurn(FakeSender(), bad, calibration=calibration(), blocked=lambda: False,
                                     camera_factory=FakeCamera, faces_factory=FakeFaces)
        head.start()
        time.sleep(0.3)
        self.assertTrue(head.running)
        head.stop()


class ModelTests(unittest.TestCase):
    def test_the_face_model_ships_with_its_licence(self):
        path = Path(headturn_win.model_path())
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 100_000)
        self.assertTrue((path.parent / "face_detection_yunet-LICENSE.txt").is_file())

    def test_importing_the_module_does_not_import_opencv(self):
        self.assertNotIn("cv2", sys.modules.get("headturn_win").__dict__)


if __name__ == "__main__":
    unittest.main()
