"""Head turn on Windows (Scotty): the webcam thread between core.headturn and the sender.

Off by default. While off, the camera is never opened and OpenCV is never imported. While on, one
daemon thread reads frames at about 15 per second, finds the face with OpenCV's YuNet detector at
320 px wide, turns its eyes and nose into a `core.headturn.Reading` and drops the frame. Nothing
is written, logged or sent; only the decision reaches the sender, as a jump-shortcut move
(`Sender.look_at`), so peers cannot tell a head turn from a shortcut press.

`HeadTurn` is Qt-free: it reports to the app through `on_event(dict)` from its own thread, and the
app moves that to the GUI thread. Events:
    {"state": "running" | "stopped" | "blocked" | "no_camera" | "error"}
    {"faced": target-or-None}           when what the person faces changes (for the settings card)
    {"switched": target}                when input moved because of a head turn
    {"calibrated": target, "ok": bool}  at the end of one calibration sample
Targets are `core.headturn.HOME` or a peer id as text.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional

from core import headturn, protocol

try:  # pragma: no cover - Windows only
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

LOGGER = logging.getLogger(__name__)

FPS = 15
DETECT_WIDTH = 320
SCORE_THRESHOLD = 0.8
CALIBRATION_SECONDS = 2.0
MODEL_NAME = "face_detection_yunet_2023mar.onnx"
_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


def model_path() -> str:
    import theme
    return os.path.join(theme.assets_dir(), "models", MODEL_NAME)


def camera_blocked() -> bool:
    """True when Windows privacy settings stop desktop apps using the camera."""
    if winreg is None:
        return False
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, _CONSENT), (winreg.HKEY_CURRENT_USER, _CONSENT),
                      (winreg.HKEY_CURRENT_USER, _CONSENT + r"\NonPackaged")):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, "Value")
        except OSError:
            continue
        if str(value).lower() == "deny":
            return True
    return False


class CvCamera:
    """The webcam through OpenCV: DirectShow first (opens on more laptops), then Media Foundation."""

    def __init__(self, index: int = 0) -> None:
        import cv2
        self._cv2 = cv2
        self._capture = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            capture = cv2.VideoCapture(index, backend)
            if capture.isOpened():
                self._capture = capture
                break
            capture.release()
        if self._capture is None:
            raise OSError("no camera")
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def read(self):
        got, frame = self._capture.read()
        return frame if got else None

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class YuNetFaces:
    """The most confident face in a frame as a Reading, or None."""

    def __init__(self, path: Optional[str] = None) -> None:
        import cv2
        self._cv2 = cv2
        self._path = path or model_path()
        if not os.path.isfile(self._path):
            raise OSError("face model missing")
        self._detector = None
        self._size = None

    def reading(self, frame) -> Optional[headturn.Reading]:
        if frame is None:
            return None
        height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return None
        size = (DETECT_WIDTH, max(1, int(height * DETECT_WIDTH / width)))
        small = self._cv2.resize(frame, size)
        if self._detector is None or self._size != size:
            self._detector = self._cv2.FaceDetectorYN.create(self._path, "", size, SCORE_THRESHOLD)
            self._size = size
        _count, faces = self._detector.detect(small)
        if faces is None or not len(faces):
            return None
        best = max(faces, key=lambda face: float(face[14]))
        # YuNet: box (4), right eye, left eye, nose, mouth corners (2 each), score.
        return headturn.reading_from_landmarks(best[4:6], best[6:8], best[8:10])


class HeadTurn:
    """Owns the camera thread and the Tracker; moves input through the sender."""

    def __init__(self, sender, on_event: Callable[[dict], None], *, calibration=None,
                 camera_index: int = 0, settings: Optional[dict] = None,
                 camera_factory: Optional[Callable] = None, faces_factory: Optional[Callable] = None,
                 blocked: Callable[[], bool] = camera_blocked, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sender = sender
        self.on_event = on_event
        self.camera_index = camera_index
        self.settings = dict(settings or {})
        self._camera_factory = camera_factory or CvCamera
        self._faces_factory = faces_factory or YuNetFaces
        self._blocked = blocked
        self._sleep = sleep
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._collect_for: Optional[str] = None
        self._collect_until = 0.0
        self._samples: Dict[str, List[headturn.Reading]] = {}
        self._faced: object = object()
        self.calibration = calibration
        self.tracker: Optional[headturn.Tracker] = None
        self._new_tracker()

    # -- lifetime -------------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return True
        if self._blocked():
            self._emit({"state": "blocked"})
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Scotty-head-turn", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    # -- calibration ----------------------------------------------------------

    def begin_sample(self, target: str) -> None:
        """Record readings for `target` for CALIBRATION_SECONDS (the camera must be running)."""
        with self._lock:
            self._samples[target] = []
            self._collect_for = target
            self._collect_until = self.sender.now() + CALIBRATION_SECONDS

    def finish_calibration(self) -> headturn.Calibration:
        """The calibration from every sample taken; raises CalibrationError when unusable."""
        with self._lock:
            samples = dict(self._samples)
            self._samples = {}
            self._collect_for = None
        calibration = headturn.Calibration.from_samples(samples)
        self.calibration = calibration
        self._new_tracker()
        return calibration

    def set_calibration(self, calibration) -> None:
        self.calibration = calibration
        self._new_tracker()

    def _new_tracker(self) -> None:
        self.tracker = None
        if self.calibration is not None:
            options = {key: float(self.settings[key]) for key in ("dwell", "cooldown", "margin")
                       if isinstance(self.settings.get(key), (int, float))}
            self.tracker = headturn.Tracker(self.calibration, self._where_input_is(), **options)

    # -- the thread -----------------------------------------------------------

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:  # an app callback must never kill the camera thread
            LOGGER.exception("Head turn event handler failed")

    def _where_input_is(self) -> str:
        owner = self.sender.owner
        return headturn.HOME if owner is None else protocol.id_text(owner)

    def _run(self) -> None:
        camera = faces = None
        try:
            try:
                camera = self._camera_factory(self.camera_index)
                faces = self._faces_factory()
            except OSError as exc:
                LOGGER.info("Head turn cannot start: %s", exc)
                self._emit({"state": "no_camera"})
                return
            except ImportError:
                LOGGER.exception("Head turn: OpenCV missing")
                self._emit({"state": "error"})
                return
            self._emit({"state": "running"})
            period = 1.0 / FPS
            while not self._stop.is_set():
                started = time.monotonic()
                frame = camera.read()
                reading = faces.reading(frame) if frame is not None else None
                frame = None  # dropped: nothing outlives one detection
                self.step(reading)
                rest = period - (time.monotonic() - started)
                if rest > 0:
                    self._sleep(rest)
        except Exception:
            LOGGER.exception("Head turn stopped")
            self._emit({"state": "error"})
        finally:
            if camera is not None:
                camera.close()
            if not self._stop.is_set():
                self._stop.set()
            self._emit({"state": "stopped"})

    def step(self, reading: Optional[headturn.Reading]) -> Optional[str]:
        """One frame's reading (the thread's body, separate so tests drive it directly)."""
        now = self.sender.now()
        with self._lock:
            collecting = self._collect_for
            if collecting is not None:
                if reading is not None:
                    self._samples[collecting].append(reading)
                if now >= self._collect_until:
                    self._collect_for = None
                    ok = len(self._samples[collecting]) >= headturn.MIN_SAMPLES
                    self._emit({"calibrated": collecting, "ok": ok})
                return None
        tracker = self.tracker
        if tracker is None:
            return None
        if self.sender.driven():
            return None  # another PC drives this one: its keyboard is not here to move
        actual = self._where_input_is()
        if actual != tracker.current:
            tracker.moved_to(actual, now)
        tracker.note_input(now, self.sender.input_busy(), last_key=self.sender.last_key_at)
        target = tracker.feed(reading, now)
        if tracker.faced != self._faced:
            self._faced = tracker.faced
            self._emit({"faced": tracker.faced})
        if target is None:
            return None
        peer = None if target == headturn.HOME else protocol.read_id(target)
        if target != headturn.HOME and peer is None:
            return None
        if self.sender.look_at(peer):
            self._emit({"switched": target})
            return target
        tracker.moved_to(self._where_input_is(), now)
        return None
