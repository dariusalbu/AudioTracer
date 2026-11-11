"""
app/ui/worker.py
================
Background thread for the full AudioTracer pipeline.

``TranscriptionWorker`` inherits from ``QThread`` and runs the entire
processing pipeline (extract → transcribe → synthesize → cleanup) off the
main GUI thread so the interface never freezes during heavy work.

Signal contract
---------------
progress_update(str, int)
    Human-readable status message and a 0-100 completion percentage.
    Safe to connect directly to a ``QProgressBar`` and a status ``QLabel``.

finished(dict)
    Emitted on successful completion.  The payload dict contains:

    .. code-block:: python

        {
            "full_text": str,          # raw joined transcript
            "segments":  list[dict],   # [{start, end, text}, …]
            "summary":   str,          # Markdown notes from synthesizer
            "language":  str,          # ISO-639-1 detected language code
            "source":    str,          # original URL or file path
        }

error(str)
    Emitted when any step raises an unhandled exception.  The string
    contains a user-readable error description.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.extractor import download_youtube_audio, _is_url
from app.core.synthesizer import generate_summary
from app.core.transcriber import Transcriber
from app.utils.file_manager import cleanup_audio_file, get_download_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Progress milestones (percentage)
_P_DOWNLOAD_START = 0
_P_DOWNLOAD_END = 40
_P_MODEL_LOAD = 48
_P_TRANSCRIBE_START = 50
_P_TRANSCRIBE_END = 82
_P_SYNTHESIZE_START = 84
_P_SYNTHESIZE_END = 97
_P_CLEANUP = 99
_P_DONE = 100

# URL prefixes that indicate a remote resource — imported from extractor
# (kept here as a note; _is_url is now in app.core.extractor)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class TranscriptionWorker(QThread):
    """Run the full AudioTracer pipeline on a background thread.

    Parameters
    ----------
    url_or_path:
        Either a YouTube URL (starts with ``http``/``https``) or an absolute
        path to a local audio file (MP3, WAV, M4A, …).
    model_size:
        Whisper model variant forwarded to :class:`~app.core.transcriber.Transcriber`.
    device:
        Inference device — ``"cpu"`` or ``"cuda"``.
    compute_type:
        CTranslate2 quantisation type (e.g. ``"int8"``, ``"float16"``).
    backend:
        Note-generation backend name forwarded to
        :func:`~app.core.synthesizer.generate_summary`
        (e.g. ``"mock"``, ``"gemini"``).

    Example
    -------
    .. code-block:: python

        worker = TranscriptionWorker("https://youtu.be/dQw4w9WgXcQ")
        worker.progress_update.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.start()
    """

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    #: Emits (status_message, percent_complete 0-100)
    progress_update: pyqtSignal = pyqtSignal(str, int)

    #: Emits the result payload dict on success
    finished: pyqtSignal = pyqtSignal(dict)

    #: Emits a human-readable error description on failure
    error: pyqtSignal = pyqtSignal(str)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        url_or_path: str,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        backend: str = "mock",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = url_or_path.strip()
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._backend = backend
        self._audio_path: str | None = None  # set during run; used by cleanup

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _emit_progress(self, message: str, percent: int) -> None:
        """Clamp *percent* to [0, 100] and emit :attr:`progress_update`."""
        logger.debug("[worker] %d%% — %s", percent, message)
        self.progress_update.emit(message, max(0, min(100, percent)))

    def _make_download_callback(self):
        """Return a yt-dlp progress callback that maps to 0-40%."""

        def callback(downloaded: int, total: int, percent: float) -> None:
            mapped = int(_P_DOWNLOAD_START + (percent / 100.0) * (_P_DOWNLOAD_END - _P_DOWNLOAD_START))
            self._emit_progress(
                f"Downloading … {percent:.0f}%  "
                f"({downloaded // 1_048_576} / {total // 1_048_576 if total else '?'} MB)",
                mapped,
            )

        return callback

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: C901 — complexity acceptable for a pipeline
        """Execute the pipeline on the worker thread.

        Flow
        ----
        1. If source is a URL → download via :func:`~app.core.extractor.download_youtube_audio`.
        2. Load & run :class:`~app.core.transcriber.Transcriber`.
        3. Generate Markdown notes via :func:`~app.core.synthesizer.generate_summary`.
        4. Clean up the downloaded audio file (URL path only).
        5. Emit :attr:`finished` with the result dict.
        """
        try:
            audio_path = self._run_extraction()
            result = self._run_transcription(audio_path)
            self._run_cleanup(audio_path)
            self._emit_progress("Done!", _P_DONE)
            self.finished.emit(result)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline failed in worker thread.")
            self.error.emit(str(exc))

    def _run_extraction(self) -> str:
        """Return the path to the audio file (download if URL, else validate local)."""
        if _is_url(self._source):
            self._emit_progress("Starting download …", _P_DOWNLOAD_START)
            download_dir = str(get_download_dir())
            audio_path = download_youtube_audio(
                url=self._source,
                output_dir=download_dir,
                progress_callback=self._make_download_callback(),
            )
            self._audio_path = audio_path  # remember for cleanup
            self._emit_progress("Download complete.", _P_DOWNLOAD_END)
            return audio_path

        # Local file path
        path = Path(self._source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: '{self._source}'")
        self._emit_progress("Local file validated.", _P_DOWNLOAD_END)
        return str(path)

    def _run_transcription(self, audio_path: str) -> dict:
        """Load the model, transcribe, and generate notes.  Returns result dict."""
        self._emit_progress("Loading Whisper model …", _P_MODEL_LOAD)
        transcriber = Transcriber(
            model_size=self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )

        self._emit_progress("Transcribing audio …", _P_TRANSCRIBE_START)
        transcript = transcriber.transcribe(audio_path)

        # Map transcription progress across the 50-82 band by word count proxy
        word_count = len(transcript.full_text.split())
        self._emit_progress(
            f"Transcription complete — {word_count:,} words, "
            f"language: {transcript.language}.",
            _P_TRANSCRIBE_END,
        )

        self._emit_progress("Generating structured notes …", _P_SYNTHESIZE_START)
        summary = generate_summary(transcript.full_text, backend=self._backend)
        self._emit_progress("Notes generated.", _P_SYNTHESIZE_END)

        return {
            "full_text": transcript.full_text,
            "segments": [
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                }
                for seg in transcript.segments
            ],
            "summary": summary,
            "language": transcript.language,
            "source": self._source,
        }

    def _run_cleanup(self, audio_path: str) -> None:
        """Delete the downloaded audio file (skip for local source paths)."""
        # Only clean up files we downloaded ourselves
        if self._audio_path is None:
            return

        self._emit_progress("Cleaning up temporary files …", _P_CLEANUP)
        deleted = cleanup_audio_file(audio_path)
        if deleted:
            logger.info("Cleaned up: %s", audio_path)
        else:
            logger.warning("Cleanup skipped or failed for: %s", audio_path)
