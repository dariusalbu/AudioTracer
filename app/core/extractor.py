"""
app/core/extractor.py
=====================
YouTube audio extraction layer for AudioTracer.

Wraps ``yt-dlp`` to download the best available audio stream from a YouTube
URL and save it as an MP3 file in a caller-specified output directory.

Design principles
-----------------
- **No Qt imports** — this module is pure Python and can be exercised from
  tests, scripts, or a CLI without a display.
- Raises typed domain exceptions so callers can handle errors uniformly.
- Progress hooks forward download percentage to an optional callback so the
  UI layer can update a progress bar without polling.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yt_dlp  # type: ignore[import-untyped]

from app.utils.file_manager import sanitise_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when audio extraction fails for any reason."""


class InvalidURLError(ExtractionError):
    """Raised when the supplied URL is not a valid / supported YouTube link."""


# ---------------------------------------------------------------------------
# URL detection helper
# ---------------------------------------------------------------------------

#: URL prefixes that indicate a remote resource rather than a local path.
_URL_PREFIXES: tuple[str, ...] = ("http://", "https://", "www.")


def _is_url(value: str) -> bool:
    """Return ``True`` if *value* looks like a remote URL.

    Parameters
    ----------
    value:
        The raw string to inspect (may be a URL or a local file path).

    Returns
    -------
    bool
        ``True`` when *value* starts with ``http://``, ``https://``, or
        ``www.`` (case-insensitive); ``False`` otherwise.
    """
    return any(value.strip().lower().startswith(prefix) for prefix in _URL_PREFIXES)


class InvalidURLError(ExtractionError):
    """Raised when the supplied URL is not a valid / supported YouTube link."""


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: Signature for the optional progress callback.
#: Arguments: ``(downloaded_bytes: int, total_bytes: int, percent: float)``
ProgressCallback = Callable[[int, int, float], None]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_progress_hook(
    callback: ProgressCallback | None,
) -> Callable[[dict[str, Any]], None]:
    """Return a yt-dlp progress hook that forwards status to *callback*."""

    def hook(d: dict[str, Any]) -> None:
        if callback is None or d.get("status") != "downloading":
            return

        downloaded: int = d.get("downloaded_bytes", 0) or 0
        total: int = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        percent: float = (downloaded / total * 100.0) if total > 0 else 0.0

        try:
            callback(downloaded, total, percent)
        except Exception:  # noqa: BLE001
            # Never let a UI callback crash the download thread
            logger.debug("Progress callback raised an exception — ignoring.", exc_info=True)

    return hook


def _build_ydl_opts(
    output_dir: Path,
    progress_hook: Callable,
    cookies_from_browser: str | None = None,
) -> dict[str, Any]:
    """Construct the ``yt_dlp.YoutubeDL`` options dictionary.

    Parameters
    ----------
    output_dir:
        Directory where the downloaded file will be saved.
    progress_hook:
        yt-dlp progress hook callable.
    cookies_from_browser:
        Browser name to extract cookies from (e.g. ``"chrome"``, ``"edge"``,
        ``"firefox"``).  Pass ``None`` to skip cookie extraction.
    """
    opts: dict[str, Any] = {
        # Save as MP3; yt-dlp handles the ffmpeg post-processing step
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        # Suppress console output — we handle progress via the hook
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [progress_hook],
        # Abort after 3 retries on network hiccups
        "retries": 3,
        "socket_timeout": 30,
    }

    if cookies_from_browser:
        # Passes your browser's YouTube login cookies to bypass bot-detection.
        # Tuple format: (browser, profile, keyring, container)
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
        logger.debug("Cookie source: browser=%s", cookies_from_browser)

    return opts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def download_youtube_audio(
    url: str,
    output_dir: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Download the audio track from a YouTube URL and save it as an MP3.

    Parameters
    ----------
    url:
        A fully-qualified YouTube URL
        (e.g. ``"https://www.youtube.com/watch?v=dQw4w9WgXcQ"``).
    output_dir:
        Directory into which the MP3 file is written.  Created automatically
        if it does not exist.
    progress_callback:
        Optional callable invoked periodically during the download with
        ``(downloaded_bytes, total_bytes, percent_float)``.

    Returns
    -------
    str
        Absolute path to the downloaded MP3 file.

    Raises
    ------
    InvalidURLError
        If *url* is empty, malformed, or not recognised by yt-dlp.
    ExtractionError
        For any other download or post-processing failure.
    """
    url = url.strip()
    if not url:
        raise InvalidURLError("URL must not be empty.")

    # Basic structural check before hitting the network
    if not (url.startswith("http://") or url.startswith("https://")):
        raise InvalidURLError(f"URL does not look valid: '{url}'")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    progress_hook = _make_progress_hook(progress_callback)
    ydl_opts = _build_ydl_opts(out_path, progress_hook)

    logger.info("Starting audio extraction: %s → %s", url, out_path)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info: dict[str, Any] = ydl.extract_info(url, download=True)

            if info is None:
                raise ExtractionError("yt-dlp returned no metadata for the given URL.")

            # yt-dlp resolves the final filename after post-processing
            title: str = info.get("title", "audio_file")
            safe_stem = sanitise_filename(title)

            # The postprocessor renames the file to .mp3
            mp3_path = out_path / f"{safe_stem}.mp3"

            # Fallback: scan directory for the newest .mp3 if the expected path
            # does not exist (yt-dlp may alter the title slightly)
            if not mp3_path.exists():
                mp3_files = sorted(
                    out_path.glob("*.mp3"), key=os.path.getmtime, reverse=True
                )
                if not mp3_files:
                    raise ExtractionError(
                        "Download completed but no MP3 file was found in "
                        f"'{out_path}'. Check that ffmpeg is installed."
                    )
                mp3_path = mp3_files[0]
                logger.debug(
                    "Expected path not found; resolved to newest MP3: %s", mp3_path
                )

            logger.info("Audio extraction successful: %s", mp3_path)
            return str(mp3_path)

    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "is not a valid URL" in msg or "Unsupported URL" in msg:
            raise InvalidURLError(f"Unsupported or invalid URL: {url!r}") from exc
        raise ExtractionError(f"Download failed: {msg}") from exc

    except ExtractionError:
        raise

    except Exception as exc:
        raise ExtractionError(
            f"Unexpected error during audio extraction: {exc}"
        ) from exc
