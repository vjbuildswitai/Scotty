"""Fork (Scotty): the small panel in the corner while files arrive, with a progress bar and Cancel,
then where they went and an Open folder button. It stays on top without taking focus, so typing
into whatever is in front is never interrupted, and closes by itself a few seconds after the end."""

import os

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from core.i18n import tr
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

CLOSE_AFTER_MS = 7000
MARGIN = 16
WIDTH = 360


def percent(done, total) -> int:
    if not total:
        return 100
    return max(0, min(100, int(done * 100 / total)))


class TransferToast(QWidget):
    def __init__(self, on_cancel):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("scottyToast")
        self.setStyleSheet(
            "#scottyToast { background: palette(window); border: 1px solid palette(mid); border-radius: 8px; }"
            "QLabel#title { font-weight: 600; }")
        self.setFixedWidth(WIDTH)
        self._folder = None
        self._on_cancel = on_cancel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_button = QPushButton(tr("Open folder"))
        self.open_button.clicked.connect(self._open_folder)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.hide)
        for button in (self.open_button, self.cancel_button, self.close_button):
            buttons.addWidget(button)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addWidget(self.bar)
        layout.addLayout(buttons)
        self._closer = QTimer(self)
        self._closer.setSingleShot(True)
        self._closer.timeout.connect(self.hide)

    def show_event(self, event: dict) -> None:
        """Show `event` (FilesBridge's notice dict)."""
        state = event.get("state")
        self.title.setText(event.get("title", ""))
        receiving = state == "receiving"
        message = event.get("message", "")
        if receiving and message:
            message = os.path.basename(message.replace("/", os.sep)) or message
        self.message.setText(message)
        self.bar.setVisible(receiving or state == "done")
        self.bar.setValue(percent(event.get("done_bytes", 0), event.get("total_bytes", 0)) if receiving else 100)
        self.cancel_button.setVisible(receiving)
        self._folder = event.get("folder")
        self.open_button.setVisible(state == "done" and bool(self._folder))
        self.close_button.setVisible(not receiving)
        if receiving:
            self._closer.stop()
        else:
            self._closer.start(CLOSE_AFTER_MS)
        self.adjustSize()
        self._place()
        if not self.isVisible():
            self.show()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - MARGIN, area.bottom() - self.height() - MARGIN)

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        try:
            self._on_cancel()
        finally:
            self.cancel_button.setEnabled(True)

    def _open_folder(self) -> None:
        if self._folder:
            os.makedirs(self._folder, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))
