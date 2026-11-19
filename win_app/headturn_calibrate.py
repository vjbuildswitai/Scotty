"""Head turn calibration (Scotty): a full-screen window on this PC that asks the person to face
each screen in turn while win_app/headturn_win.HeadTurn records two seconds of head readings.

Nothing is shown on the other PC (no new wire message): for a peer's screen the window says
"Now turn to <name>" and the person turns as they would to use it.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import theme
import widgets
from core import headturn
from core.i18n import tr

COUNTDOWN = 3  # seconds to settle before each sample


class CalibrationWindow(QDialog):
    """`screens` = [(target, name)], this PC first. `head` is the running HeadTurn. On success
    `on_done(calibration)` is called with the new core.headturn.Calibration."""

    def __init__(self, head, screens: List[Tuple[str, str]], on_done: Callable, parent=None) -> None:
        super().__init__(parent)
        self.head = head
        self.screens = screens
        self.on_done = on_done
        self.index = -1
        self.remaining = 0
        self.setWindowTitle(tr("Head turn calibration"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(True)
        column = QVBoxLayout(self)
        column.setContentsMargins(48, 40, 48, 48)
        column.setSpacing(18)
        top = QHBoxLayout()
        self.privacy = widgets.label(tr("Camera on. Nothing is saved or sent."), "note")
        top.addWidget(self.privacy, 1)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        top.addWidget(self.cancel_button)
        column.addLayout(top)
        column.addStretch(1)
        self.count = QLabel("")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setFont(theme.mono_font(48, 700))
        column.addWidget(self.count)
        self.step = widgets.label("", "note")
        self.step.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.step)
        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(theme.font(32, 700))
        self.title.setWordWrap(True)
        column.addWidget(self.title)
        self.detail = widgets.label("", "body", wrap=True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.detail)
        self.again = QPushButton(tr("Try again"))
        self.again.clicked.connect(self.restart)
        self.again.setVisible(False)
        column.addWidget(self.again, 0, Qt.AlignmentFlag.AlignCenter)
        column.addStretch(2)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.showFullScreen()
        self.restart()

    def restart(self) -> None:
        self.again.setVisible(False)
        self.index = -1
        self._next()

    def _next(self) -> None:
        self.index += 1
        if self.index >= len(self.screens):
            self._finish()
            return
        target, name = self.screens[self.index]
        self.step.setText(tr("Screen {index} of {count}").format(index=self.index + 1, count=len(self.screens)))
        if target == headturn.HOME:
            self.title.setText(tr("Look at this screen"))
            self.detail.setText(tr("Sit as you normally do and look at the number."))
        else:
            self.title.setText(tr("Now turn to {name}").format(name=name))
            self.detail.setText(tr("Face {name}'s screen as you would to use it, and hold still until this "
                                   "screen says done.").format(name=name))
        self.remaining = COUNTDOWN
        self.count.setText(str(self.remaining))
        self.timer.start()

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining > 0:
            self.count.setText(str(self.remaining))
            return
        self.timer.stop()
        self.count.setText("…")
        self.head.begin_sample(self.screens[self.index][0])

    def on_calibrated(self, target: str, ok: bool) -> None:
        """From the app, on the GUI thread, when one sample ends."""
        if self.index < 0 or self.index >= len(self.screens) or self.screens[self.index][0] != target:
            return
        if ok:
            self._next()
        else:
            self._failed(tr("Scotty could not see your face. Check the camera is not covered and the room is lit."))

    def _failed(self, message: str) -> None:
        self.timer.stop()
        self.count.setText("!")
        self.title.setText(tr("That didn't work"))
        self.detail.setText(message)
        self.again.setVisible(True)

    def _finish(self) -> None:
        try:
            calibration = self.head.finish_calibration()
        except headturn.CalibrationError as error:
            reasons = {
                "close": tr("The screens are too close together to tell apart by turning your head. Angle the "
                            "laptops further apart, or keep using the pointer."),
                "samples": tr("Scotty could not see your face. Check the camera is not covered and the room is lit."),
            }
            self._failed(reasons.get(error.reason, str(error)))
            return
        self.count.setText("✓")
        self.title.setText(tr("Calibrated"))
        self.detail.setText(tr("Turn your head to switch. Typing, holding a key or looking at the keyboard never "
                               "switches."))
        self.cancel_button.setText(tr("Done"))
        self.on_done(calibration)

    def reject(self) -> None:
        self.timer.stop()
        super().reject()
