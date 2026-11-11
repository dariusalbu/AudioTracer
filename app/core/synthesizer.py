"""
app/core/synthesizer.py
=======================
AI-powered note synthesis layer for AudioTracer.

Converts a raw transcript into a structured Markdown document with sections
for Key Takeaways, Action Items, and a timestamped Summary.

Architecture
------------
The module exposes:

1. ``NoteGeneratorBase`` — an abstract base class that all backends implement.
2. ``MockNoteGenerator`` — deterministic template renderer used in development
   and unit tests (no network required).
3. ``GeminiNoteGenerator`` — production backend using the ``google-genai`` SDK.
4. ``get_note_generator()`` — factory function that reads
   ``AUDIOTRACER_BACKEND`` from the environment and returns the appropriate
   implementation.
5. ``generate_summary()`` — convenience wrapper around the active backend.

Design principles
-----------------
- **No Qt imports** — pure Python; safe to call from tests without a display.
- Swapping backends requires only an environment variable change.
- Raises ``NoteGenerationError`` for uniform error handling in the pipeline.
"""

from __future__ import annotations

import logging
import os
import textwrap
from abc import ABC, abstractmethod
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class NoteGenerationError(Exception):
    """Raised when note generation fails for any reason."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class NoteGeneratorBase(ABC):
    """Contract that every note-generation backend must fulfil."""

    @abstractmethod
    def generate(self, transcript_text: str) -> str:
        """Convert *transcript_text* into a structured Markdown document.

        Parameters
        ----------
        transcript_text:
            The raw transcript string produced by the transcription layer.

        Returns
        -------
        str
            A Markdown-formatted notes document.

        Raises
        ------
        NoteGenerationError
            If the backend fails to produce a result.
        """


# ---------------------------------------------------------------------------
# Mock backend (development / testing)
# ---------------------------------------------------------------------------

_MOCK_PROMPT_TEMPLATE = """\
You are a professional note-taker. Analyse the following transcript and
produce structured Markdown notes. This is a mock — replace with real API.

TRANSCRIPT:
{transcript}
"""

_MOCK_NOTES_TEMPLATE = """\
# AudioTracer Notes
> Generated: {timestamp}  
> Backend: Mock (development)

---

## 📋 Summary

{summary_placeholder}

---

## 🔑 Key Takeaways

{takeaways}

---

## ✅ Action Items

{action_items}

---

## 📝 Full Transcript

> *The raw transcript is preserved below for reference.*

{transcript_block}
"""


class MockNoteGenerator(NoteGeneratorBase):
    """Returns a deterministic Markdown template without any network calls.

    Suitable for development, CI, and unit tests.  The "analysis" is a
    simple heuristic: sentences containing trigger words are classified as
    takeaways or action items.
    """

    _TAKEAWAY_KEYWORDS = frozenset(
        {"important", "key", "note", "remember", "critical", "essential", "main", "primary"}
    )
    _ACTION_KEYWORDS = frozenset(
        {"should", "must", "need to", "action", "follow up", "next step", "todo", "task"}
    )

    def generate(self, transcript_text: str) -> str:  # noqa: D102
        if not transcript_text or not transcript_text.strip():
            raise NoteGenerationError("Cannot generate notes from an empty transcript.")

        logger.info("MockNoteGenerator: generating notes from %d chars.", len(transcript_text))

        sentences = [s.strip() for s in transcript_text.replace("\n", " ").split(".") if s.strip()]

        takeaways: list[str] = []
        action_items: list[str] = []
        summary_sentences: list[str] = []

        for i, sentence in enumerate(sentences):
            lower = sentence.lower()
            if any(kw in lower for kw in self._TAKEAWAY_KEYWORDS):
                takeaways.append(sentence)
            elif any(kw in lower for kw in self._ACTION_KEYWORDS):
                action_items.append(sentence)

            # Use the first 3 sentences as a summary proxy
            if i < 3:
                summary_sentences.append(sentence)

        # Fallback placeholders when heuristics find nothing
        if not takeaways:
            takeaways = ["No explicit takeaways detected — review full transcript below."]
        if not action_items:
            action_items = ["No explicit action items detected."]

        takeaway_md = "\n".join(f"- {t}." for t in takeaways)
        action_md = "\n".join(f"- [ ] {a}." for a in action_items)
        summary_md = " ".join(summary_sentences) or "_No summary available._"

        # Wrap transcript in a blockquote with 80-char line wrapping
        transcript_block = "\n".join(
            f"> {line}" for line in textwrap.wrap(transcript_text, width=80)
        )

        return _MOCK_NOTES_TEMPLATE.format(
            timestamp=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            summary_placeholder=summary_md,
            takeaways=takeaway_md,
            action_items=action_md,
            transcript_block=transcript_block,
        )


# ---------------------------------------------------------------------------
# Gemini backend
# ---------------------------------------------------------------------------

_GEMINI_SYSTEM_PROMPT = """\
You are an expert meeting and lecture note-taker.
Given a raw audio transcript, produce clean, structured Markdown notes with:
1. A concise **Summary** (3-5 sentences).
2. A **Key Takeaways** bullet list (5-10 items).
3. An **Action Items** checklist (use Markdown task list syntax).
4. Preserve any technical terms, names, and figures exactly as spoken.
Return ONLY the Markdown document — no preamble, no commentary.
"""


class GeminiNoteGenerator(NoteGeneratorBase):
    """Calls the Gemini API via ``google-genai`` to generate structured notes.

    Parameters
    ----------
    model:
        Gemini model identifier (default ``"gemini-2.0-flash"``).
    api_key:
        Gemini API key.  Falls back to the ``GEMINI_API_KEY`` environment
        variable when *None*.

    Raises
    ------
    NoteGenerationError
        If the API key is missing or the API call fails.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")

        if not self._api_key:
            raise NoteGenerationError(
                "Gemini API key not found. Set the GEMINI_API_KEY environment variable."
            )

    def generate(self, transcript_text: str) -> str:  # noqa: D102
        if not transcript_text or not transcript_text.strip():
            raise NoteGenerationError("Cannot generate notes from an empty transcript.")

        try:
            # Import lazily so the module loads even when google-genai is absent
            from google import genai  # type: ignore[import-untyped]
            from google.genai import types  # type: ignore[import-untyped]

            client = genai.Client(api_key=self._api_key)

            user_message = (
                f"Please analyse this transcript and generate structured notes:\n\n"
                f"{transcript_text}"
            )

            response = client.models.generate_content(
                model=self._model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=_GEMINI_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=4096,
                ),
            )

            notes: str = response.text
            if not notes or not notes.strip():
                raise NoteGenerationError("Gemini returned an empty response.")

            logger.info(
                "GeminiNoteGenerator: received %d chars from API.", len(notes)
            )
            return notes

        except NoteGenerationError:
            raise
        except Exception as exc:
            raise NoteGenerationError(
                f"Gemini API call failed: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[NoteGeneratorBase]] = {
    "mock": MockNoteGenerator,
    "gemini": GeminiNoteGenerator,
}


def get_note_generator(
    backend: str | None = None,
    **kwargs: object,
) -> NoteGeneratorBase:
    """Instantiate and return the configured note-generation backend.

    Parameters
    ----------
    backend:
        Backend name: ``"mock"`` or ``"gemini"``.  Reads the
        ``AUDIOTRACER_BACKEND`` environment variable when *None*; defaults
        to ``"mock"`` if neither is set.
    **kwargs:
        Additional keyword arguments forwarded to the backend constructor
        (e.g. ``model="gemini-2.0-flash-lite"``).

    Returns
    -------
    NoteGeneratorBase
        A ready-to-use note generator instance.

    Raises
    ------
    NoteGenerationError
        If the requested backend name is unknown.
    """
    name = (backend or os.environ.get("AUDIOTRACER_BACKEND", "mock")).lower().strip()

    if name not in _REGISTRY:
        available = ", ".join(f"'{k}'" for k in _REGISTRY)
        raise NoteGenerationError(
            f"Unknown backend '{name}'. Available backends: {available}."
        )

    logger.info("Instantiating note generator backend: '%s'", name)
    return _REGISTRY[name](**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def generate_summary(
    transcript_text: str,
    backend: str | None = None,
) -> str:
    """Generate a structured Markdown summary from a raw transcript.

    This is the primary entry point used by ``pipeline.py``.  It calls
    :func:`get_note_generator` to resolve the active backend, then invokes
    :meth:`NoteGeneratorBase.generate`.

    Parameters
    ----------
    transcript_text:
        The raw transcript string produced by the transcription layer.
    backend:
        Backend override.  When *None*, falls back to the
        ``AUDIOTRACER_BACKEND`` environment variable (default ``"mock"``).

    Returns
    -------
    str
        A Markdown-formatted notes document.

    Raises
    ------
    NoteGenerationError
        If the backend fails to produce a result.
    """
    generator = get_note_generator(backend=backend)
    return generator.generate(transcript_text)
