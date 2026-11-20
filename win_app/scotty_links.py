"""Fork (Scotty): send a link to the other PC. The link hotkey (Ctrl+Alt+L by default) sends the
URL on this PC's clipboard; a paired PC with "Accept files and links sent from my other PCs" on
opens it in its default browser. Only what core.protocol.safe_url allows ever opens (http or https,
a host, no credentials, at most 2,000 characters); anything else shows a note instead."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from core import protocol

LOGGER = logging.getLogger(__name__)

OPEN_GAP_SECONDS = 1.0  # a peer cannot open more than one tab a second here


class LinkShare:
    def __init__(self, read_text: Callable[[], Optional[str]], send_all: Callable[[dict], int],
                 open_url: Callable[[str], bool], notify: Callable[[str, dict], None],
                 accept: bool = True, clock: Callable[[], float] = time.monotonic) -> None:
        self._read_text = read_text
        self._send_all = send_all
        self._open_url = open_url
        self._notify = notify
        self._clock = clock
        self.accept = bool(accept)
        self._opened_at = float("-inf")
        self._guard = threading.Lock()

    def send_clipboard(self) -> bool:
        """The hotkey: the clipboard's URL to every paired PC that takes it."""
        try:
            text = self._read_text()
        except Exception:
            LOGGER.exception("Could not read the clipboard")
            text = None
        url = text.strip() if isinstance(text, str) else ""
        if not protocol.safe_url(url):
            self._notify("not_a_link", {})
            return False
        try:
            sent = self._send_all(protocol.open_url_msg(url))
        except Exception:
            LOGGER.exception("Could not send the link")
            sent = 0
        self._notify("sent" if sent else "no_peer", {"url": url})
        return bool(sent)

    def peer_sent(self, peer_name: str, message) -> bool:
        """A paired PC sent `open_url`: open it if allowed, at most once a second."""
        if not self.accept:
            return False
        url = protocol.read_open_url(message)
        if url is None:
            return False
        with self._guard:
            now = self._clock()
            if now - self._opened_at < OPEN_GAP_SECONDS:
                return False
            self._opened_at = now
        try:
            opened = bool(self._open_url(url))
        except Exception:
            LOGGER.exception("Could not open a link from %s", peer_name)
            opened = False
        if opened:
            self._notify("opened", {"url": url, "peer": peer_name})
        return opened


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_L = 0x4C
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5C07  # Scotty's link hotkey; any id unique to this window will do


try:  # pragma: no cover - Windows and Qt only
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import QAbstractNativeEventFilter

    class LinkHotKey(QAbstractNativeEventFilter):
        """Ctrl+Alt+L on this PC, real or injected by the PC driving it, calls `on_press` on the Qt
        thread. `start(hwnd)` is False when another app already holds the combination."""

        def __init__(self, on_press: Callable[[], None], modifiers: int = MOD_CONTROL | MOD_ALT,
                     vk: int = VK_L) -> None:
            super().__init__()
            self._on_press = on_press
            self._modifiers = modifiers
            self._vk = vk
            self._hwnd = None

        def start(self, hwnd: int) -> bool:
            try:
                ok = bool(ctypes.windll.user32.RegisterHotKey(wintypes.HWND(hwnd), HOTKEY_ID,
                                                              self._modifiers | MOD_NOREPEAT, self._vk))
            except (AttributeError, OSError):
                ok = False
            self._hwnd = hwnd if ok else None
            return ok

        def stop(self) -> None:
            if self._hwnd is not None:
                try:
                    ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(self._hwnd), HOTKEY_ID)
                except (AttributeError, OSError):
                    pass
                self._hwnd = None

        def nativeEventFilter(self, event_type, message):
            try:
                if self._hwnd is not None and bytes(event_type) == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        self._on_press()
                        return True, 0
            except Exception:
                LOGGER.exception("Link hotkey failed")
            return False, 0
except (ImportError, ValueError):  # pragma: no cover - modules load off Windows and without Qt
    LinkHotKey = None
