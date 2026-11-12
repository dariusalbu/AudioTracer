"""
app/ui/main_window.py
=====================
Primary application window for AudioTracer.

Implements a modern dark-themed interface using PyQt6 with:
- URL / file-path input with a Browse button for local audio.
- Animated progress bar and descriptive status label.
- QTabWidget showing the AI-generated Markdown summary and the raw transcript.
- "Save as Markdown" export button.
- Full integration with TranscriptionWorker (all heavy work runs off-thread).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.worker import TranscriptionWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme — Catppuccin Mocha palette
# ---------------------------------------------------------------------------

_PALETTE = {
    "base":     "#1e1e2e",   # darkest background
    "mantle":   "#181825",   # deeper than base
    "surface0": "#313244",   # card / panel background
    "surface1": "#45475a",   # borders, separators
    "surface2": "#585b70",   # subtle elements
    "overlay0": "#6c7086",   # muted text
    "text":     "#cdd6f4",   # primary text
    "subtext":  "#a6adc8",   # secondary text
    "blue":     "#89b4fa",   # primary accent
    "sapphire": "#74c7ec",   # secondary accent
    "green":    "#a6e3a1",   # success
    "red":      "#f38ba8",   # error / danger
    "yellow":   "#f9e2af",   # warning
    "peach":    "#fab387",   # highlight
}

_STYLESHEET = f"""
/* ── Global ── */
QMainWindow, QWidget {{
    background-color: {_PALETTE['base']};
    color: {_PALETTE['text']};
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}

/* ── Labels ── */
QLabel {{
    color: {_PALETTE['subtext']};
    background: transparent;
}}
QLabel#title_label {{
    color: {_PALETTE['blue']};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#subtitle_label {{
    color: {_PALETTE['overlay0']};
    font-size: 11px;
}}
QLabel#status_label {{
    color: {_PALETTE['subtext']};
    font-size: 12px;
    padding: 2px 0;
}}

/* ── Input ── */
QLineEdit {{
    background-color: {_PALETTE['surface0']};
    color: {_PALETTE['text']};
    border: 1px solid {_PALETTE['surface1']};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {_PALETTE['blue']};
    selection-color: {_PALETTE['base']};
}}
QLineEdit:focus {{
    border: 1px solid {_PALETTE['blue']};
}}
QLineEdit:disabled {{
    background-color: {_PALETTE['mantle']};
    color: {_PALETTE['overlay0']};
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {_PALETTE['surface0']};
    color: {_PALETTE['text']};
    border: 1px solid {_PALETTE['surface1']};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {_PALETTE['surface1']};
    border-color: {_PALETTE['blue']};
}}
QPushButton:pressed {{
    background-color: {_PALETTE['surface2']};
}}
QPushButton:disabled {{
    color: {_PALETTE['overlay0']};
    background-color: {_PALETTE['mantle']};
    border-color: {_PALETTE['surface0']};
}}
QPushButton#start_btn {{
    background-color: {_PALETTE['blue']};
    color: {_PALETTE['base']};
    font-weight: 700;
    border: none;
    min-width: 150px;
}}
QPushButton#start_btn:hover {{
    background-color: {_PALETTE['sapphire']};
}}
QPushButton#start_btn:disabled {{
    background-color: {_PALETTE['surface1']};
    color: {_PALETTE['overlay0']};
}}
QPushButton#save_btn {{
    background-color: transparent;
    color: {_PALETTE['green']};
    border: 1px solid {_PALETTE['green']};
    min-width: 160px;
}}
QPushButton#save_btn:hover {{
    background-color: rgba(166, 227, 161, 0.12);
}}
QPushButton#save_btn:disabled {{
    color: {_PALETTE['overlay0']};
    border-color: {_PALETTE['surface1']};
    background-color: transparent;
}}
QPushButton#clear_btn {{
    background-color: transparent;
    color: {_PALETTE['overlay0']};
    border: 1px solid {_PALETTE['surface1']};
}}
QPushButton#clear_btn:hover {{
    color: {_PALETTE['red']};
    border-color: {_PALETTE['red']};
}}

/* ── Progress bar ── */
QProgressBar {{
    background-color: {_PALETTE['surface0']};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {_PALETTE['sapphire']},
        stop:1 {_PALETTE['blue']}
    );
    border-radius: 4px;
}}

/* ── Tab widget ── */
QTabWidget::pane {{
    border: 1px solid {_PALETTE['surface1']};
    border-radius: 6px;
    background-color: {_PALETTE['surface0']};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {_PALETTE['mantle']};
    color: {_PALETTE['subtext']};
    border: 1px solid {_PALETTE['surface1']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 20px;
    margin-right: 2px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background-color: {_PALETTE['surface0']};
    color: {_PALETTE['blue']};
    font-weight: 600;
    border-bottom: 2px solid {_PALETTE['blue']};
}}
QTabBar::tab:hover:!selected {{
    background-color: {_PALETTE['surface1']};
    color: {_PALETTE['text']};
}}

/* ── Text editors ── */
QTextEdit {{
    background-color: {_PALETTE['surface0']};
    color: {_PALETTE['text']};
    border: none;
    border-radius: 4px;
    padding: 12px;
    font-size: 13px;
    line-height: 1.6;
    selection-background-color: {_PALETTE['blue']};
    selection-color: {_PALETTE['base']};
}}

/* ── Status bar ── */
QStatusBar {{
    background-color: {_PALETTE['mantle']};
    color: {_PALETTE['overlay0']};
    font-size: 11px;
    border-top: 1px solid {_PALETTE['surface0']};
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: {_PALETTE['surface0']};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_PALETTE['surface2']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_PALETTE['blue']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {_PALETTE['surface0']};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {_PALETTE['surface2']};
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """The primary application window.

    Owns a single :class:`~app.ui.worker.TranscriptionWorker` at a time.
    The worker is re-created for each job and auto-cleaned up on completion.
    """

    # Whisper / backend defaults — could be loaded from config in a future
    # iteration; kept as class-level constants for now.
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE: str = "int8"
    NOTE_BACKEND: str = "mock"

    def __init__(self) -> None:
        super().__init__()
        self._worker: TranscriptionWorker | None = None
        self._last_result: dict | None = None

        self._build_ui()
        self._apply_theme()
        self._connect_signals()
        self._set_idle_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct and arrange all widgets."""
        self.setWindowTitle("AudioTracer")
        self.setMinimumSize(860, 640)
        self.resize(1020, 720)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 20, 24, 16)
        root_layout.setSpacing(14)

        root_layout.addLayout(self._build_header())
        root_layout.addLayout(self._build_input_row())
        root_layout.addLayout(self._build_progress_row())
        root_layout.addWidget(self._build_tab_widget(), stretch=1)
        root_layout.addLayout(self._build_action_row())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

    def _build_header(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(2)

        title = QLabel("🎙 AudioTracer")
        title.setObjectName("title_label")

        subtitle = QLabel(
            "Download · Transcribe · Summarise — entirely on your machine"
        )
        subtitle.setObjectName("subtitle_label")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return layout

    def _build_input_row(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(6)

        lbl = QLabel("YouTube URL or local audio file path:")
        layout.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "https://www.youtube.com/watch?v=…  or  C:\\path\\to\\audio.mp3"
        )
        self.url_input.setClearButtonEnabled(True)
        row.addWidget(self.url_input, stretch=1)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setToolTip("Open a local audio file")
        row.addWidget(self.browse_btn)

        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Select Whisper model size (tiny is fastest, base is balanced)")
        self.model_combo.addItems(["tiny (Ultra Fast)", "base (Balanced)", "small (High Accuracy)"])
        self.model_combo.setCurrentIndex(0)  # default to tiny for high speed
        row.addWidget(self.model_combo)

        self.start_btn = QPushButton("▶  Start Transcription")
        self.start_btn.setObjectName("start_btn")
        row.addWidget(self.start_btn)

        layout.addLayout(row)
        return layout

    def _build_progress_row(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(4)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("status_label")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        return layout

    def _build_tab_widget(self) -> QTabWidget:
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # ── Tab 0: AI Summary ──────────────────────────────────────────
        self.summary_edit = QTextEdit()
        self.summary_edit.setReadOnly(True)
        self.summary_edit.setPlaceholderText(
            "The AI-generated Markdown summary will appear here after processing."
        )
        mono = QFont("Cascadia Code", 12)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.summary_edit.setFont(mono)
        self.tab_widget.addTab(self.summary_edit, "✨  AI Summary")

        # ── Tab 1: Raw Transcript ──────────────────────────────────────
        self.transcript_edit = QTextEdit()
        self.transcript_edit.setReadOnly(True)
        self.transcript_edit.setPlaceholderText(
            "The raw Whisper transcript will appear here after processing."
        )
        self.transcript_edit.setFont(mono)
        self.tab_widget.addTab(self.transcript_edit, "📄  Raw Transcript")

        return self.tab_widget

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.save_btn = QPushButton("💾  Save as Markdown")
        self.save_btn.setObjectName("save_btn")
        self.save_btn.setToolTip("Export the AI Summary to a .md file")

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("clear_btn")

        row.addWidget(self.save_btn)
        row.addStretch()
        row.addWidget(self.clear_btn)
        return row

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        self.setStyleSheet(_STYLESHEET)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        # Allow pressing Enter in the URL field to start
        self.url_input.returnPressed.connect(self._on_start_clicked)

    # ------------------------------------------------------------------
    # UI state helpers
    # ------------------------------------------------------------------

    def _set_idle_state(self) -> None:
        """Restore the UI to its pre-job idle state."""
        self.start_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.url_input.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.save_btn.setEnabled(self._last_result is not None)
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready.")
        self._status_bar.showMessage("Idle", 3000)

    def _set_busy_state(self) -> None:
        """Lock interactive elements while a job is running."""
        self.start_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.url_input.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        """Validate input and launch the TranscriptionWorker."""
        source = self.url_input.text().strip()
        if not source:
            QMessageBox.warning(
                self,
                "No Input",
                "Please enter a YouTube URL or select a local audio file.",
            )
            return

        # Guard: only one job at a time
        if self._worker is not None and self._worker.isRunning():
            return

        # Clear previous results
        self.summary_edit.clear()
        self.transcript_edit.clear()
        self._last_result = None

        self._set_busy_state()
        self.status_label.setText("Initialising …")

        chosen_label = self.model_combo.currentText().split()[0]
        model_size = chosen_label if chosen_label in ("tiny", "base", "small") else self.WHISPER_MODEL

        self._worker = TranscriptionWorker(
            url_or_path=source,
            model_size=model_size,
            device=self.WHISPER_DEVICE,
            compute_type=self.WHISPER_COMPUTE,
            backend=self.NOTE_BACKEND,
            parent=self,
        )
        self._worker.progress_update.connect(self._on_progress_update)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        # Auto-delete C++ object when thread finishes
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

        logger.info("Worker started for source: %s", source)
        self._status_bar.showMessage("Processing …")

    def _on_browse_clicked(self) -> None:
        """Open a file dialog to select a local audio file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            str(Path.home()),
            "Audio Files (*.mp3 *.wav *.m4a *.ogg *.flac);;All Files (*)",
        )
        if path:
            self.url_input.setText(path)

    def _on_save_clicked(self) -> None:
        """Export the AI summary to a Markdown file chosen by the user."""
        if self._last_result is None:
            return

        default_name = "AudioTracer_Notes.md"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Markdown Notes",
            str(Path.home() / default_name),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )

        if not save_path:
            return

        try:
            Path(save_path).write_text(
                self._last_result["summary"], encoding="utf-8"
            )
            self._status_bar.showMessage(f"Saved → {save_path}", 5000)
            logger.info("Markdown notes saved to: %s", save_path)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Could not write to '{save_path}':\n{exc}",
            )

    def _on_clear_clicked(self) -> None:
        """Reset the UI to its initial blank state."""
        self.url_input.clear()
        self.summary_edit.clear()
        self.transcript_edit.clear()
        self._last_result = None
        self._set_idle_state()

    # ------------------------------------------------------------------
    # Worker signal handlers (always called on the main thread via Qt queues)
    # ------------------------------------------------------------------

    def _on_progress_update(self, message: str, percent: int) -> None:
        """Update the progress bar and status label from the worker signal."""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_worker_finished(self, result: dict) -> None:
        """Populate the UI with the completed pipeline result."""
        self._last_result = result

        # ── AI Summary tab ────────────────────────────────────────────
        self.summary_edit.setPlainText(result.get("summary", ""))
        self.summary_edit.moveCursor(QTextCursor.MoveOperation.Start)

        # ── Raw Transcript tab ────────────────────────────────────────
        segments: list[dict] = result.get("segments", [])
        if segments:
            lines = []
            for seg in segments:
                start = _format_timestamp(seg["start"])
                end = _format_timestamp(seg["end"])
                lines.append(f"[{start} → {end}]  {seg['text']}")
            self.transcript_edit.setPlainText("\n".join(lines))
        else:
            self.transcript_edit.setPlainText(result.get("full_text", ""))
        self.transcript_edit.moveCursor(QTextCursor.MoveOperation.Start)

        # Switch to summary tab so the user sees the result immediately
        self.tab_widget.setCurrentIndex(0)

        lang = result.get("language", "?")
        word_count = len(result.get("full_text", "").split())
        self._status_bar.showMessage(
            f"✓ Completed  |  Language: {lang}  |  {word_count:,} words transcribed",
            0,  # 0 = show until next message
        )
        self._set_idle_state()
        logger.info("Worker finished — %d words, language: %s", word_count, lang)

    def _on_worker_error(self, message: str) -> None:
        """Display an error dialog and restore the idle state."""
        logger.error("Worker error: %s", message)
        self.progress_bar.setValue(0)
        self.status_label.setText("Error — see dialog for details.")

        QMessageBox.critical(
            self,
            "AudioTracer — Pipeline Error",
            f"An error occurred during processing:\n\n{message}\n\n"
            "Check that ffmpeg is installed and the URL is valid.",
        )
        self._set_idle_state()
        self._status_bar.showMessage("Error — processing failed.", 8000)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        """Cleanly stop any running worker before closing."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            if not self._worker.wait(3000):
                self._worker.terminate()
        event.accept()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _format_timestamp(seconds: float) -> str:
    """Convert *seconds* to ``MM:SS`` or ``H:MM:SS`` display string."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
