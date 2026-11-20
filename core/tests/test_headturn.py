"""Head turn decisions from synthetic head readings (core/headturn.py); no camera."""

import math
import unittest

from core import headturn
from core.headturn import HOME, Calibration, CalibrationError, Reading, Screen, Tracker

PEER = "a1b2c3d4"
FPS = 15


def calibration(*extra):
    return Calibration([Screen(HOME, 0.0, 0.30), Screen(PEER, 0.32, 0.31), *extra])


def run(tracker, readings, start=0.0, fps=FPS):
    """Feed readings at `fps`; return (time, target) for every switch and the end time."""
    switches, now = [], start
    for reading in readings:
        target = tracker.feed(reading, now)
        if target is not None:
            switches.append((round(now, 3), target))
        now += 1 / fps
    return switches, now


def hold(yaw, seconds, pitch=0.30, fps=FPS):
    return [Reading(yaw, pitch)] * int(round(seconds * fps))


class LandmarksTests(unittest.TestCase):
    def test_frontal_face_reads_near_zero_and_turn_reads_sideways(self):
        frontal = headturn.reading_from_landmarks((100, 100), (160, 100), (130, 130))
        self.assertAlmostEqual(frontal.yaw, 0.0)
        self.assertAlmostEqual(frontal.pitch, 0.5)
        turned = headturn.reading_from_landmarks((100, 100), (160, 100), (148, 130))
        self.assertAlmostEqual(turned.yaw, 0.3)

    def test_distance_to_camera_cancels_out(self):
        near = headturn.reading_from_landmarks((100, 100), (200, 100), (170, 150))
        far = headturn.reading_from_landmarks((100, 100), (150, 100), (135, 125))
        self.assertAlmostEqual(near.yaw, far.yaw)
        self.assertAlmostEqual(near.pitch, far.pitch)

    def test_landmarks_that_are_not_a_face_give_nothing(self):
        for right, left, nose in [((100, 100), (100.2, 100), (100, 120)),   # eyes on top of each other
                                  ((math.nan, 1), (2, 1), (1, 2)),
                                  ((0, 0), (10, 0), (500, 0)),               # nose far outside the face
                                  ((0,), (10, 0), (5, 5)),
                                  (None, (10, 0), (5, 5))]:
            with self.subTest(right=right, left=left, nose=nose):
                self.assertIsNone(headturn.reading_from_landmarks(right, left, nose))


class CalibrationTests(unittest.TestCase):
    def test_medians_ignore_a_stray_frame(self):
        samples = {HOME: [Reading(0.01, 0.3)] * 9 + [Reading(2.0, 0.3)],
                   PEER: [Reading(0.30, 0.31)] * 10}
        result = Calibration.from_samples(samples)
        self.assertEqual(result.targets, (HOME, PEER))
        self.assertAlmostEqual(result.screens[0].yaw, 0.01)

    def test_too_few_frames_screens_too_close_or_too_many_are_refused(self):
        with self.assertRaises(CalibrationError) as few:
            Calibration.from_samples({HOME: [Reading(0, 0.3)] * 3, PEER: [Reading(0.3, 0.3)] * 10})
        self.assertEqual(few.exception.reason, "samples")
        with self.assertRaises(CalibrationError) as close:
            Calibration([Screen(HOME, 0.0, 0.3), Screen(PEER, 0.05, 0.3)])
        self.assertEqual(close.exception.reason, "close")
        with self.assertRaises(CalibrationError) as one:
            Calibration([Screen(HOME, 0.0, 0.3)])
        self.assertEqual(one.exception.reason, "screens")
        with self.assertRaises(CalibrationError):
            Calibration([Screen(str(i), i * 0.2, 0.3) for i in range(headturn.MAX_SCREENS + 1)])
        with self.assertRaises(CalibrationError):
            Calibration([Screen(HOME, 0.0, 0.3), Screen(HOME, 0.4, 0.3)])

    def test_saved_calibration_round_trips_and_junk_loads_as_none(self):
        saved = calibration().to_json()
        self.assertEqual(Calibration.from_json(saved).to_json(), saved)
        for junk in (None, "x", {}, [1, 2], [{"target": HOME, "yaw": "nan", "pitch": 0}],
                     [{"target": HOME, "yaw": 0, "pitch": 0}, {"target": PEER, "yaw": 1e9, "pitch": 0}],
                     [{"target": "", "yaw": 0, "pitch": 0}, {"target": PEER, "yaw": 1, "pitch": 0}],
                     [{"target": str(i), "yaw": i, "pitch": 0} for i in range(20)]):
            with self.subTest(junk=junk):
                self.assertIsNone(Calibration.from_json(junk))

    def test_hysteresis_needs_the_midpoint_plus_margin_to_leave(self):
        cal = calibration()
        midpoint, gap = 0.16, 0.32
        self.assertEqual(cal.faced(midpoint + 0.01, HOME), HOME)
        self.assertEqual(cal.faced(midpoint + 0.15 * gap + 0.001, HOME), PEER)
        self.assertEqual(cal.faced(midpoint - 0.01, PEER), PEER)
        self.assertEqual(cal.faced(midpoint - 0.15 * gap - 0.001, PEER), HOME)


class TrackerTests(unittest.TestCase):
    def test_a_deliberate_turn_switches_once_within_a_second_and_turning_back_returns(self):
        tracker = Tracker(calibration())
        switches, now = run(tracker, hold(0.0, 1.5) + hold(0.32, 1.5))
        self.assertEqual([target for _, target in switches], [PEER])
        self.assertLess(switches[0][0] - 1.5, 1.0)
        back, _ = run(tracker, hold(0.0, 2.0), start=now)
        self.assertEqual([target for _, target in back], [HOME])

    def test_a_glance_shorter_than_the_dwell_does_nothing(self):
        tracker = Tracker(calibration())
        switches, _ = run(tracker, hold(0.0, 1.0) + hold(0.32, 0.2) + hold(0.0, 1.0))
        self.assertEqual(switches, [])

    def test_jitter_around_the_midpoint_never_flickers(self):
        tracker = Tracker(calibration())
        noisy = [Reading(0.16 + (0.03 if i % 2 else -0.03), 0.3) for i in range(FPS * 5)]
        switches, _ = run(tracker, noisy)
        self.assertEqual(switches, [])

    def test_never_switches_while_typing_and_switches_once_typing_stops(self):
        tracker = Tracker(calibration())
        now = last_key = 0.0
        switches = []
        for i in range(FPS * 3):
            if i % 3 == 0:  # a key press every 0.2 s for 3 s while looking at the other screen
                tracker.note_input(now, held=False, pressed=True)
                last_key = now
            target = tracker.feed(Reading(0.32, 0.3), now)
            if target:
                switches.append(target)
            now += 1 / FPS
        self.assertEqual(switches, [])
        later, _ = run(tracker, hold(0.32, 1.5), start=now)
        self.assertEqual([target for _, target in later], [PEER])
        self.assertGreaterEqual(later[0][0] - last_key, headturn.DEFAULT_TYPING_QUIET - 1e-9)

    def test_a_held_key_or_button_blocks_the_switch(self):
        tracker = Tracker(calibration())
        tracker.note_input(0.0, held=True)
        switches, now = run(tracker, hold(0.32, 3.0))
        self.assertEqual(switches, [])
        tracker.note_input(now, held=False)
        later, _ = run(tracker, hold(0.32, 0.2), start=now)
        self.assertEqual([target for _, target in later], [PEER])

    def test_looking_down_at_the_keyboard_or_losing_the_face_holds(self):
        tracker = Tracker(calibration())
        down = hold(0.32, 2.0, pitch=0.31 + headturn.LOOK_DOWN + 0.05)
        switches, now = run(tracker, hold(0.0, 1.0) + down + [None] * (FPS * 2))
        self.assertEqual(switches, [])
        self.assertEqual(tracker.current, HOME)
        self.assertIsNone(tracker.faced)

    def test_cooldown_spaces_switches(self):
        tracker = Tracker(calibration(), cooldown=2.0, dwell=0.1)
        switches, _ = run(tracker, hold(0.32, 0.5) + hold(0.0, 0.5) + hold(0.32, 3.0))
        times = [time for time, _ in switches]
        self.assertTrue(all(b - a >= 2.0 - 1e-9 for a, b in zip(times, times[1:])), times)

    def test_input_moved_by_the_pointer_is_followed_not_fought(self):
        tracker = Tracker(calibration())
        tracker.moved_to(PEER, 0.0)  # the pointer crossed while the person still faces home
        switches, _ = run(tracker, hold(0.0, 0.5))
        self.assertEqual(switches, [])  # within the cooldown: not yanked back
        self.assertEqual(tracker.current, PEER)

    def test_three_screens_go_to_the_one_faced(self):
        third = "f00d"
        tracker = Tracker(calibration(Screen(third, -0.3, 0.3)))
        switches, now = run(tracker, hold(0.0, 1.0) + hold(-0.3, 1.5) + hold(0.32, 2.0))
        self.assertEqual([target for _, target in switches], [third, PEER])


if __name__ == "__main__":
    unittest.main()
