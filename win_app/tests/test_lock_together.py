"""Fork (Scotty): lock together. A peer can lock this PC (rate-limited, only when the setting is on),
never unlock it; a lock a peer caused is not echoed back."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core import protocol  # noqa: E402
import lock_win  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class LockTogetherTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sent = []
        self.locks = []
        self.policy = lock_win.LockTogether(lambda m: self.sent.append(m) or 1,
                                            lambda: self.locks.append(self.clock.now) or True,
                                            clock=self.clock)

    def test_local_lock_is_sent_once_per_window(self):
        self.assertTrue(self.policy.local_locked())
        self.assertEqual(self.sent, [protocol.lock_msg()])
        self.clock.now += 1
        self.assertFalse(self.policy.local_locked())
        self.clock.now += lock_win.RATE_SECONDS
        self.assertTrue(self.policy.local_locked())
        self.assertEqual(len(self.sent), 2)

    def test_peer_lock_locks_and_is_rate_limited(self):
        self.assertTrue(self.policy.peer_asked(protocol.lock_msg()))
        self.clock.now += 1
        self.assertFalse(self.policy.peer_asked(protocol.lock_msg()))
        self.assertEqual(len(self.locks), 1)
        self.clock.now += lock_win.RATE_SECONDS
        self.assertTrue(self.policy.peer_asked(protocol.lock_msg()))

    def test_lock_caused_by_a_peer_is_not_echoed(self):
        self.policy.peer_asked(protocol.lock_msg())
        self.clock.now += 0.5
        self.assertFalse(self.policy.local_locked())
        self.assertEqual(self.sent, [])

    def test_setting_off_neither_sends_nor_locks(self):
        self.policy.enabled = False
        self.assertFalse(self.policy.local_locked())
        self.assertFalse(self.policy.peer_asked(protocol.lock_msg()))
        self.assertEqual((self.sent, self.locks), ([], []))

    def test_malformed_or_other_messages_do_nothing(self):
        for message in ({"type": "lock"}, {"type": "unlock", "data": {}}, None, "lock", {"type": "lock", "data": 1}):
            with self.subTest(message=message):
                self.assertFalse(self.policy.peer_asked(message))
        self.assertEqual(self.locks, [])

    def test_failures_are_contained(self):
        def boom(*_):
            raise OSError("no")
        policy = lock_win.LockTogether(boom, boom, clock=self.clock)
        self.assertFalse(policy.local_locked())
        self.assertFalse(policy.peer_asked(protocol.lock_msg()))


if __name__ == "__main__":
    unittest.main()
