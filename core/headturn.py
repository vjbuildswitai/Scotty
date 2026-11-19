"""Which screen the person faces, from one head reading per camera frame (Scotty, head turn).

Pure Python: no camera, no Qt, no network, so every rule here is covered by unittest on any OS.
The camera side (win_app/headturn_win.py) turns each frame into face landmarks and hands this
module one `Reading`; this module says when to move input and where.

A reading is two numbers taken from five face landmarks (eyes and nose; YuNet's order):
`yaw` is how far the nose sits left or right of the point between the eyes, `pitch` how far below,
both measured in eye-widths so the distance to the camera cancels out. They are not angles, and
need not be: calibration records them while the person looks at each screen, and switching only
compares a reading with those records.

Rules, in the order `Tracker.feed` applies them:
- No face, or a face looking well below every screen (at the keyboard): hold where input is.
- Smooth the yaw so one noisy frame never decides anything.
- The faced screen is the calibrated one nearest the smoothed yaw, but leaving the current screen
  needs the yaw past the midpoint by `margin` of the gap (hysteresis), so a reading on the line
  does not flicker.
- The new screen must be faced for `dwell` seconds, the last switch at least `cooldown` ago, no key
  or button held and no key pressed for `typing_quiet` seconds: head turn never steals typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

HOME = "self"  # the target meaning "this PC"; any other target is a peer id as text

MAX_SCREENS = 8
MIN_SAMPLES = 8            # frames per screen during calibration (about half a second)
MIN_SEPARATION = 0.08      # eye-widths between neighbouring screens; closer cannot be told apart
DEFAULT_MARGIN = 0.15      # of the gap between two screens, past the midpoint, to leave one
DEFAULT_DWELL = 0.4        # seconds a new screen must be faced
DEFAULT_COOLDOWN = 1.0     # seconds after a switch before the next
DEFAULT_TYPING_QUIET = 0.8 # seconds after the last key press
DEFAULT_SMOOTHING = 0.35   # weight of the newest yaw in the running average
LOOK_DOWN = 0.18           # eye-widths below the lowest calibrated pitch counts as the keyboard
LOST_RESET = 0.5           # seconds without a face after which smoothing starts afresh
_LIMIT = 5.0               # any coordinate beyond this many eye-widths is not a face


class CalibrationError(ValueError):
    """Calibration cannot be used; `reason` is one of "screens", "samples", "close", "value"."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Reading:
    yaw: float
    pitch: float


def reading_from_landmarks(right_eye: Sequence[float], left_eye: Sequence[float],
                           nose: Sequence[float]) -> Optional[Reading]:
    """A reading from three landmarks in image pixels, or None when they do not make a face
    (eyes on top of each other, numbers that are not finite)."""
    try:
        rx, ry = float(right_eye[0]), float(right_eye[1])
        lx, ly = float(left_eye[0]), float(left_eye[1])
        nx, ny = float(nose[0]), float(nose[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(v) for v in (rx, ry, lx, ly, nx, ny)):
        return None
    width = math.hypot(lx - rx, ly - ry)
    if width < 1.0:
        return None
    mid_x, mid_y = (rx + lx) / 2, (ry + ly) / 2
    yaw, pitch = (nx - mid_x) / width, (ny - mid_y) / width
    if abs(yaw) > _LIMIT or abs(pitch) > _LIMIT:
        return None
    return Reading(yaw, pitch)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class Screen:
    target: str
    yaw: float
    pitch: float


class Calibration:
    """The calibrated screens, ordered by yaw."""

    def __init__(self, screens: Iterable[Screen]) -> None:
        screens = sorted(screens, key=lambda screen: screen.yaw)
        targets = [screen.target for screen in screens]
        if not 2 <= len(screens) <= MAX_SCREENS or len(set(targets)) != len(targets):
            raise CalibrationError("screens", "Calibrate between 2 and 8 different screens.")
        for screen in screens:
            if (not isinstance(screen.target, str) or not screen.target
                    or not all(math.isfinite(v) and abs(v) <= _LIMIT for v in (screen.yaw, screen.pitch))):
                raise CalibrationError("value", "A calibrated screen is not usable.")
        for first, second in zip(screens, screens[1:]):
            if second.yaw - first.yaw < MIN_SEPARATION:
                raise CalibrationError("close", "Two screens are too close together to tell apart by head turn.")
        self.screens = tuple(screens)

    @classmethod
    def from_samples(cls, samples: Mapping[str, Sequence[Reading]]) -> "Calibration":
        """Median reading per screen from the frames recorded while the person looked at it."""
        screens = []
        for target, readings in samples.items():
            readings = [reading for reading in readings if reading is not None]
            if len(readings) < MIN_SAMPLES:
                raise CalibrationError("samples", "Scotty could not see your face clearly enough.")
            screens.append(Screen(target, _median([r.yaw for r in readings]), _median([r.pitch for r in readings])))
        return cls(screens)

    def to_json(self) -> list:
        return [{"target": s.target, "yaw": round(s.yaw, 4), "pitch": round(s.pitch, 4)} for s in self.screens]

    @classmethod
    def from_json(cls, value) -> Optional["Calibration"]:
        """None for anything that is not a usable saved calibration (a hand-edited settings file
        must not stop Scotty starting)."""
        if not isinstance(value, list) or len(value) > MAX_SCREENS:
            return None
        try:
            return cls(Screen(item["target"], float(item["yaw"]), float(item["pitch"]))
                       for item in value if isinstance(item, dict))
        except (CalibrationError, KeyError, TypeError, ValueError):
            return None

    @property
    def targets(self) -> tuple:
        return tuple(screen.target for screen in self.screens)

    def looking_down(self, pitch: float) -> bool:
        return pitch > max(screen.pitch for screen in self.screens) + LOOK_DOWN

    def faced(self, yaw: float, current: Optional[str], margin: float = DEFAULT_MARGIN) -> str:
        """The screen faced at `yaw`. Leaving `current` needs the yaw past the midpoint towards a
        neighbour by `margin` of their gap."""
        nearest = min(self.screens, key=lambda screen: abs(screen.yaw - yaw))
        if current is None or current not in self.targets or nearest.target == current:
            return nearest.target
        here = next(screen for screen in self.screens if screen.target == current)
        gap = abs(nearest.yaw - here.yaw)
        midpoint = (nearest.yaw + here.yaw) / 2
        past = (yaw - midpoint) if nearest.yaw > here.yaw else (midpoint - yaw)
        return nearest.target if past >= margin * gap else current


class Tracker:
    """Feeds readings, says when to switch. Not thread-safe: one camera thread owns it; input
    notes arrive through `note_input`, which only stores two numbers."""

    def __init__(self, calibration: Calibration, current: str = HOME, *,
                 dwell: float = DEFAULT_DWELL, cooldown: float = DEFAULT_COOLDOWN,
                 typing_quiet: float = DEFAULT_TYPING_QUIET, margin: float = DEFAULT_MARGIN,
                 smoothing: float = DEFAULT_SMOOTHING) -> None:
        self.calibration = calibration
        self.current = current
        self.dwell, self.cooldown, self.typing_quiet = dwell, cooldown, typing_quiet
        self.margin = margin
        self.smoothing = min(1.0, max(0.05, smoothing))
        self._yaw: Optional[float] = None
        self._lost_at: Optional[float] = None
        self._pending: Optional[str] = None
        self._pending_since = 0.0
        self._last_switch = -math.inf
        self._last_key = -math.inf
        self._held = False
        self.faced: Optional[str] = None  # what the person faces now, for the settings card

    def note_input(self, now: float, held: bool, pressed: bool = False,
                   last_key: Optional[float] = None) -> None:
        """Keyboard and mouse state from the input hooks: `held` while any key or button is down;
        a key press either as `pressed` (now) or as `last_key`, the time of the latest one."""
        self._held = held
        if pressed:
            self._last_key = max(self._last_key, now)
        if last_key is not None:
            self._last_key = max(self._last_key, last_key)

    def moved_to(self, target: str, now: float) -> None:
        """Input moved some other way (the pointer crossed an edge, a shortcut): follow it, and
        give the person the cooldown before head turn acts again."""
        self.current = target
        self._pending = None
        self._last_switch = now

    def feed(self, reading: Optional[Reading], now: float) -> Optional[str]:
        """One frame. Returns the target to move input to, or None to leave it where it is."""
        if reading is None or self.calibration.looking_down(reading.pitch):
            if self._lost_at is None:
                self._lost_at = now
            elif now - self._lost_at >= LOST_RESET:
                self._yaw = None
            self._pending = None
            self.faced = None
            return None
        self._lost_at = None
        self._yaw = reading.yaw if self._yaw is None else (
            self.smoothing * reading.yaw + (1 - self.smoothing) * self._yaw)
        faced = self.calibration.faced(self._yaw, self.current, self.margin)
        self.faced = faced
        if faced == self.current:
            self._pending = None
            return None
        if faced != self._pending:
            self._pending, self._pending_since = faced, now
        if now - self._pending_since < self.dwell or now - self._last_switch < self.cooldown:
            return None
        if self._held or now - self._last_key < self.typing_quiet:
            return None
        self.current, self._pending, self._last_switch = faced, None, now
        return faced
