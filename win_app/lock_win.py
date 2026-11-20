"""Fork (Scotty): lock together. When this PC locks (Win+L, lid, idle timeout), the paired PCs that
have the setting on lock too, and a lock from a paired PC locks this one. Unlock never travels: a
peer can only ever cause what the user undoes with their own password (SECURITY.md).

`LockTogether` is the policy (setting, rate limit, no echo) and runs anywhere; `SessionWatcher`
hears Windows' session-lock notification through a Qt native event filter."""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Callable

from core import protocol

LOGGER = logging.getLogger(__name__)

RATE_SECONDS = 5.0  # at most one lock taken, and one sent, per this many seconds
ECHO_SECONDS = 5.0  # a lock a peer caused is not sent back out

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
NOTIFY_FOR_THIS_SESSION = 0


class LockTogether:
    def __init__(self, send_all: Callable[[dict], int], lock_station: Callable[[], bool],
                 enabled: bool = True, clock: Callable[[], float] = time.monotonic) -> None:
        self._send_all = send_all
        self._lock_station = lock_station
        self._clock = clock
        self.enabled = bool(enabled)
        self._sent_at = float("-inf")
        self._taken_at = float("-inf")
        self._guard = threading.Lock()

    def local_locked(self) -> bool:
        """This PC just locked: tell the peers, unless a peer caused it or one was told just now."""
        if not self.enabled:
            return False
        with self._guard:
            now = self._clock()
            if now - self._taken_at < ECHO_SECONDS or now - self._sent_at < RATE_SECONDS:
                return False
            self._sent_at = now
        try:
            self._send_all(protocol.lock_msg())
        except Exception:
            LOGGER.exception("Could not tell the other PCs to lock")
            return False
        return True

    def peer_asked(self, message) -> bool:
        """A paired PC sent `lock`: lock this one, at most once per RATE_SECONDS."""
        if not self.enabled or not protocol.read_lock(message):
            return False
        with self._guard:
            now = self._clock()
            if now - self._taken_at < RATE_SECONDS:
                return False
            self._taken_at = now
        try:
            return bool(self._lock_station())
        except Exception:
            LOGGER.exception("Could not lock this PC")
            return False


def lock_workstation() -> bool:
    """Locks this session (the same as Win+L). False off Windows or when Windows refuses."""
    try:
        return bool(ctypes.windll.user32.LockWorkStation())
    except (AttributeError, OSError):
        return False


try:  # pragma: no cover - Windows and Qt only
    from PySide6.QtCore import QAbstractNativeEventFilter
    from ctypes import wintypes

    class SessionWatcher(QAbstractNativeEventFilter):
        """Calls `on_lock` on the Qt thread when this session locks. `start(hwnd)` registers the
        window for session notifications; `stop()` undoes it."""

        def __init__(self, on_lock: Callable[[], None]) -> None:
            super().__init__()
            self._on_lock = on_lock
            self._hwnd = None

        def start(self, hwnd: int) -> bool:
            try:
                ok = bool(ctypes.windll.wtsapi32.WTSRegisterSessionNotification(wintypes.HWND(hwnd), NOTIFY_FOR_THIS_SESSION))
            except (AttributeError, OSError):
                ok = False
            self._hwnd = hwnd if ok else None
            return ok

        def stop(self) -> None:
            if self._hwnd is not None:
                try:
                    ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(wintypes.HWND(self._hwnd))
                except (AttributeError, OSError):
                    pass
                self._hwnd = None

        def nativeEventFilter(self, event_type, message):
            try:
                if self._hwnd is not None and bytes(event_type) == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_WTSSESSION_CHANGE and msg.wParam == WTS_SESSION_LOCK:
                        self._on_lock()
            except Exception:
                LOGGER.exception("Session notification failed")
            return False, 0
except (ImportError, ValueError):  # pragma: no cover - modules load off Windows and without Qt
    SessionWatcher = None
