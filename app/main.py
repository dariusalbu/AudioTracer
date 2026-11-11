"""
app/main.py
===========
Application entry point for AudioTracer.

Responsibilities
----------------
1. Bootstrap the Python logging system so all modules log to both the console
   and a rotating file from the very first import.
2. Enable Qt's high-DPI scaling and set application-level metadata.
3. Instantiate ``QApplication`` and ``MainWindow``.
4. Start the Qt event loop and propagate the exit code to the OS.

Usage
-----
Run from the project root::

    python app/main.py

Or, if you install the package, the ``[project.scripts]`` entry point calls
``app.main:main`` directly.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
# Ensure the project root (the folder that *contains* `app/`) is on sys.path
# regardless of how this script is invoked:
#   python app/main.py        ← sys.path gets app/ by default; fix needed
#   python -m app.main        ← project root already on sys.path; no-op
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# Logging bootstrap
# ---------------------------------------------------------------------------
# Must be configured *before* any other app import so that every
# ``logging.getLogger(__name__)`` call in the codebase picks up handlers.

def _configure_logging() -> None:
    """Set up console + rotating-file logging for the entire application."""
    log_dir = Path.home() / "AudioTracer" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audiotracer.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # ── Console handler (INFO and above) ──────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    # ── Rotating file handler (DEBUG and above, 5 × 2 MB) ─────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,  # 2 MB per file
        backupCount=4,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s:%(lineno)d — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("ctranslate2").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — file: %s", log_file
    )


_configure_logging()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt bootstrap (must come after stdlib imports)
# ---------------------------------------------------------------------------

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Global Qt exception hook
# ---------------------------------------------------------------------------

def _qt_exception_hook(exc_type, exc_value, exc_tb) -> None:
    """Log unhandled exceptions that bubble up to the top level."""
    logger.critical(
        "Unhandled exception — shutting down.",
        exc_info=(exc_type, exc_value, exc_tb),
    )
    # Let Qt's default handler also run so the app exits cleanly
    sys.__excepthook__(exc_type, exc_value, exc_tb)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Initialise and run the AudioTracer application.

    Returns
    -------
    int
        Process exit code (0 = clean exit, non-zero = error).
    """
    # Install top-level exception handler before creating QApplication
    sys.excepthook = _qt_exception_hook

    # ── High-DPI and rendering hints (must be set before QApplication) ──
    # Qt6 enables high-DPI scaling by default; these lines make it explicit
    # and consistent across platforms.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # ── Application metadata ─────────────────────────────────────────
    app.setApplicationName("AudioTracer")
    app.setApplicationDisplayName("AudioTracer")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("AudioTracer")
    app.setOrganizationDomain("audiotracer.local")

    # ── Default application font ──────────────────────────────────────
    default_font = QFont("Segoe UI", 10)
    app.setFont(default_font)

    from PyQt6.QtCore import QLibraryInfo
    logger.info(
        "AudioTracer starting — Qt %s, Python %s",
        QLibraryInfo.version().toString(),
        sys.version.split()[0],
    )

    # ── Create and show the main window ──────────────────────────────
    window = MainWindow()
    window.show()
    window.raise_()           # bring above other windows
    window.activateWindow()   # give it keyboard focus

    exit_code: int = app.exec()

    logger.info("AudioTracer exiting — code %d.", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
