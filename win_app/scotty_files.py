"""Fork (Scotty): copied files across the edge, between the clipboard, the file channel and the app.

`FilesBridge` is what the sender and the receiver call as `files`: `outgoing(host)` gives the
`files` manifest for whatever is copied in Explorer, or None; `incoming(host, read)` fetches what a
manifest names into the drop folder in the background and puts it on the clipboard, so Ctrl+V in
Explorer pastes it. The app hears about it through `notify(event)`, called from worker threads with
a dict: {"state": "receiving"|"done"|"failed"|"cancelled"|"refused", "title", "message", and for
"receiving" "done_bytes" and "total_bytes"}.

No Qt here, so it is tested on any platform with a fake clipboard.
"""

import logging
import threading
import time

from core import filechannel, protocol
from core.i18n import tr

LOGGER = logging.getLogger(__name__)

PROGRESS_INTERVAL_SECONDS = 0.25


class FilesBridge:
    def __init__(self, settings, clipboard, notify, server_factory=filechannel.FileServer,
                 fetch=filechannel.fetch, port=protocol.FILES_PORT, clock=time.monotonic):
        self._settings = dict(settings)
        self._clipboard = clipboard
        self._notify = notify
        self._server_factory = server_factory
        self._fetch = fetch
        self._port = port
        self._clock = clock
        self._lock = threading.Lock()
        self._server = None
        self._offered = None            # (paths, change stamp, Offer) of the last offer
        self._cancel = None             # the running fetch's cancel event
        self._generation = 0

    # Settings and lifetime

    @property
    def settings(self) -> dict:
        with self._lock:
            return dict(self._settings)

    def update(self, settings) -> None:
        """New settings; turning files on starts the listener, off stops it and cancels a fetch."""
        with self._lock:
            was = self._settings.get("enabled")
            self._settings = dict(settings)
        if self._settings["enabled"] and not was:
            self.start()
        elif not self._settings["enabled"] and was:
            self.stop()

    def start(self) -> bool:
        """Listen for fetches, when files are on. False (and a notice) when the port is taken."""
        with self._lock:
            if not self._settings["enabled"] or self._server is not None:
                return self._server is not None
        try:
            server = self._server_factory(port=self._port).start()
        except OSError as exc:
            LOGGER.warning("Scotty could not listen on TCP %d: %s", self._port, exc)
            self._tell("refused", tr("Scotty cannot send files"),
                       tr("Port {port} is in use by another program, so copied files will not follow the pointer.").format(port=self._port))
            return False
        with self._lock:
            self._server = server
        return True

    def stop(self) -> None:
        with self._lock:
            server, self._server, self._offered = self._server, None, None
        if server is not None:
            server.close()
        self.cancel()

    @property
    def advertised(self) -> bool:
        """Whether `hello` and `welcome` should carry clipboard_files: files are on and listening."""
        with self._lock:
            return self._settings["enabled"] and self._server is not None

    # Sending: what the sender and the receiver call as a clipboard goes out

    def outgoing(self, host):
        """The `files` manifest for the files copied in Explorer, offered to `host` alone, or None
        when files are off or nothing is copied. Copying the same files again offers them again;
        crossing back and forth without copying reuses the listing rather than walking a big
        folder each time."""
        with self._lock:
            server = self._server
            enabled = self._settings["enabled"]
            limit = self._settings["max_bytes"]
        if not enabled or server is None:
            return None
        paths = self._clipboard.get_files()
        if not paths:
            return None
        stamp = _stamp(self._clipboard)
        with self._lock:
            offered = self._offered
        if (offered is not None and offered[0] == paths and offered[1] == stamp and offered[2].allowed_host == host
                and self._clock() - offered[2].made_at < filechannel.OFFER_SECONDS - 30):
            offer = offered[2]
        else:
            try:
                offer = server.offer(paths, allowed_host=host)
            except filechannel.TransferError as exc:
                self._tell("refused", tr("Copied files were not sent"), str(exc))
                return None
            except OSError:
                LOGGER.exception("Could not list the copied files")
                self._tell("refused", tr("Copied files were not sent"), tr("They could not be read on this PC."))
                return None
            with self._lock:
                self._offered = (paths, stamp, offer)
        if offer.total_bytes > limit:
            self._tell("refused", tr("Copied files were not sent"),
                       tr("{size} is over this PC's limit of {limit}. Raise it under Files on the Overview page.").format(
                           size=filechannel._size(offer.total_bytes), limit=filechannel._size(limit)))
            return None
        try:
            return server.manifest(offer)
        except ValueError:
            self._tell("refused", tr("Copied files were not sent"),
                       tr("Copy at most {count} items at once, or put them in one folder.").format(count=protocol.FILES_MAX_NAMES))
            return None

    # Receiving

    def incoming(self, host, read) -> None:
        """Fetch what the manifest `read` names from `host`, in the background. A newer manifest
        cancels an older fetch still running, as a newer copy replaces an older clipboard."""
        with self._lock:
            if not self._settings["enabled"] or not host:
                return
            if self._cancel is not None:
                self._cancel.set()
            cancel = self._cancel = threading.Event()
            self._generation += 1
            generation = self._generation
            settings = dict(self._settings)
        threading.Thread(target=self._receive, args=(host, read, settings, cancel, generation),
                         name="scotty-files-fetch", daemon=True).start()

    def cancel(self) -> None:
        with self._lock:
            cancel = self._cancel
        if cancel is not None:
            cancel.set()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._cancel is not None and not self._cancel.is_set()

    def _receive(self, host, read, settings, cancel, generation):
        what = _describe(read)
        last = [0.0]

        def progress(done, total, path):
            now = self._clock()
            if done < total and now - last[0] < PROGRESS_INTERVAL_SECONDS:
                return
            last[0] = now
            self._tell("receiving", tr("Receiving {what}").format(what=what), path or "", done_bytes=done, total_bytes=total)

        try:
            landed = self._fetch(host, read, settings["drop_folder"], settings["max_bytes"],
                                 progress=progress, cancel=cancel)
        except filechannel.TransferCancelled:
            if self._current(generation):
                self._tell("cancelled", tr("Transfer cancelled"), tr("{what} did not arrive; nothing was kept.").format(what=_first_upper(what)))
            return
        except filechannel.TransferError as exc:
            self._tell("failed", tr("{what} did not arrive").format(what=_first_upper(what)), str(exc))
            return
        except Exception:
            LOGGER.exception("The file transfer failed")
            self._tell("failed", tr("{what} did not arrive").format(what=_first_upper(what)), tr("Something went wrong; nothing was kept."))
            return
        finally:
            with self._lock:
                if self._generation == generation:
                    self._cancel = None
        if not self._current(generation):
            return
        if not self._clipboard.set_files(landed):
            self._tell("done", tr("{what} arrived").format(what=_first_upper(what)),
                       tr("They are in {folder}. They could not be put on the clipboard; open the folder to use them.").format(
                           folder=settings["drop_folder"]), folder=settings["drop_folder"])
            return
        self._tell("done", tr("{what} arrived").format(what=_first_upper(what)), tr("Press Ctrl+V in any folder to paste."),
                   folder=settings["drop_folder"])

    def _current(self, generation):
        with self._lock:
            return self._generation == generation

    def _tell(self, state, title, message, **extra):
        try:
            self._notify(dict(extra, state=state, title=title, message=message))
        except Exception:
            LOGGER.exception("The files notice could not be shown")


def _stamp(clipboard):
    try:
        return getattr(clipboard, "change_stamp", lambda: None)()
    except Exception:
        return None


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _describe(read) -> str:
    count, names = read["count"], read["names"]
    size = filechannel._size(read["total_bytes"])
    if len(names) == 1 and count <= 1:
        return tr("“{name}” ({size})").format(name=names[0], size=size)
    return (tr("1 file ({size})") if count == 1 else tr("{count} files ({size})")).format(count=f"{count:,}", size=size)
