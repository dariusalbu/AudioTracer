"""
app/core/transcriber.py
=======================
Local audio transcription layer for AudioTracer.

Wraps ``faster-whisper`` (CTranslate2 backend) to convert an audio file into
a structured transcript containing the full text and per-segment timestamps.

Design principles
-----------------
- **No Qt imports** — pure Python; safe to call from tests without a display.
- The ``Transcriber`` class is initialised once and reused across multiple
  calls to avoid repeatedly loading the model (~1–10 GB) from disk.
- Raises typed domain exceptions for clean error handling in the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Compatibility patch for PyAV >= 14 / 19
# ---------------------------------------------------------------------------
# In newer PyAV versions, av.open() removed/deprecated 'metadata_errors'.
# faster-whisper 1.2.x still passes metadata_errors="ignore", which causes:
# TypeError: open() got an unexpected keyword argument 'metadata_errors'.
try:
    import av

    _orig_av_open = av.open

    def _compat_av_open(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)

    av.open = _compat_av_open  # type: ignore[assignment]
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class TranscriptionError(Exception):
    """Raised when transcription fails for any reason."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptSegment:
    """A single timed segment of a transcription.

    Attributes
    ----------
    start:
        Segment start time in seconds.
    end:
        Segment end time in seconds.
    text:
        Transcribed text for this segment (stripped of leading/trailing
        whitespace).
    """

    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    """The complete output of a transcription run.

    Attributes
    ----------
    full_text:
        The entire transcript as a single string with segments joined by
        a single space.
    segments:
        Ordered list of :class:`TranscriptSegment` objects.
    language:
        ISO-639-1 language code detected by Whisper (e.g. ``"en"``).
    language_probability:
        Confidence in the detected language (0.0 – 1.0).
    """

    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = "unknown"
    language_probability: float = 0.0


# ---------------------------------------------------------------------------
# Transcriber class
# ---------------------------------------------------------------------------


class Transcriber:
    """Wraps a ``faster-whisper`` model for repeated transcription calls.

    Parameters
    ----------
    model_size:
        Whisper model variant.  Smaller models are faster but less accurate.
        Accepted values: ``"tiny"``, ``"base"``, ``"small"``, ``"medium"``,
        ``"large-v1"``, ``"large-v2"``, ``"large-v3"``.
    device:
        Inference device — ``"cpu"`` or ``"cuda"``.
    compute_type:
        Quantisation type for CTranslate2.
        Common values: ``"int8"`` (fastest on CPU), ``"float16"`` (GPU),
        ``"float32"`` (maximum precision).
    beam_size:
        Beam search width.  Higher values improve accuracy at the cost of
        speed.  Defaults to ``5``.

    Examples
    --------
    >>> t = Transcriber(model_size="base", device="cpu")
    >>> result = t.transcribe("/tmp/audio.mp3")
    >>> print(result.full_text)
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
        cpu_threads: int = 8,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._cpu_threads = cpu_threads
        self._model: WhisperModel | None = None

        logger.info(
            "Transcriber configured — model: %s | device: %s | compute_type: %s | beam_size: %d | cpu_threads: %d",
            model_size,
            device,
            compute_type,
            beam_size,
            cpu_threads,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> WhisperModel:
        """Lazily load the Whisper model on first use.

        Returns
        -------
        WhisperModel
            The initialised model instance (cached for subsequent calls).
        """
        if self._model is None:
            logger.info(
                "Loading Whisper model '%s' on %s (threads=%d) …",
                self._model_size,
                self._device,
                self._cpu_threads,
            )
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=2,
                )
                logger.info("Whisper model loaded successfully.")
            except Exception as exc:
                raise TranscriptionError(
                    f"Failed to load Whisper model '{self._model_size}': {exc}"
                ) from exc

        return self._model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        task: str = "transcribe",
        vad_filter: bool = True,
    ) -> TranscriptResult:
        """Transcribe an audio file and return a structured result.

        Parameters
        ----------
        audio_path:
            Absolute or relative path to the audio file (MP3, WAV, M4A, …).
        language:
            BCP-47 language code to force (e.g. ``"en"``).  When *None*,
            Whisper auto-detects the language from the first 30 seconds.
        task:
            ``"transcribe"`` (default) or ``"translate"`` (outputs English
            regardless of source language).
        vad_filter:
            When ``True``, Silero VAD pre-filters silence to speed up
            transcription and reduce hallucinations.

        Returns
        -------
        TranscriptResult
            Dataclass with ``full_text``, ``segments``, ``language``, and
            ``language_probability``.

        Raises
        ------
        FileNotFoundError
            If *audio_path* does not exist.
        TranscriptionError
            If the Whisper model fails to load or transcription errors out.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: '{path}'")
        if not path.is_file():
            raise ValueError(f"Path is not a file: '{path}'")

        logger.info("Starting transcription: %s", path)

        model = self._load_model()

        try:
            segments_iter, info = model.transcribe(
                str(path),
                language=language,
                task=task,
                beam_size=self._beam_size,
                vad_filter=vad_filter,
            )

            detected_lang: str = getattr(info, "language", "unknown")
            lang_prob: float = getattr(info, "language_probability", 0.0)
            logger.debug(
                "Detected language: %s (probability: %.2f)", detected_lang, lang_prob
            )

            segments: list[TranscriptSegment] = []
            text_parts: list[str] = []

            for seg in segments_iter:
                cleaned = seg.text.strip()
                segments.append(
                    TranscriptSegment(
                        start=round(seg.start, 3),
                        end=round(seg.end, 3),
                        text=cleaned,
                    )
                )
                text_parts.append(cleaned)

            full_text = " ".join(text_parts)

            logger.info(
                "Transcription complete — %d segment(s), ~%d words.",
                len(segments),
                len(full_text.split()),
            )

            return TranscriptResult(
                full_text=full_text,
                segments=segments,
                language=detected_lang,
                language_probability=lang_prob,
            )

        except (FileNotFoundError, ValueError):
            raise
        except Exception as exc:
            raise TranscriptionError(
                f"Transcription failed for '{path}': {exc}"
            ) from exc

    def unload(self) -> None:
        """Release the loaded model from memory.

        Useful when switching model sizes at runtime or during teardown in
        long-running processes.
        """
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Whisper model unloaded from memory.")
