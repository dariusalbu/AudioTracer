"""
app/utils/file_manager.py
=========================
Filesystem helpers for AudioTracer.

Responsibilities:
- Create and locate the application's temporary download directory.
- Safely delete processed audio files to reclaim disk space.
- Provide path-sanitisation utilities for derived file names.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUDIO_SUFFIXES: frozenset[str] = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac"})
_DEFAULT_SUBDIR: str = "AudioTracer_downloads"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_download_dir(base_dir: str | None = None) -> Path:
    """Return (and create if necessary) the directory used for audio downloads.

    Parameters
    ----------
    base_dir:
        Root under which the ``AudioTracer_downloads`` sub-folder is created.
        Defaults to the system's temporary directory when *None*.

    Returns
    -------
    Path
        Absolute path to the download directory (guaranteed to exist).

    Raises
    ------
    OSError
        If the directory cannot be created due to permission issues.
    """
    root = Path(base_dir) if base_dir else Path(tempfile.gettempdir())
    download_dir = root / _DEFAULT_SUBDIR

    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Download directory ready: %s", download_dir)
    except OSError as exc:
        logger.error("Failed to create download directory %s: %s", download_dir, exc)
        raise

    return download_dir


def cleanup_audio_file(file_path: str | Path) -> bool:
    """Delete a single processed audio file from disk.

    Only files with recognised audio extensions (``.mp3``, ``.wav``, ``.m4a``,
    ``.ogg``, ``.flac``) are removed.  All other paths are ignored and
    ``False`` is returned — this prevents accidental deletion of non-audio
    artefacts even if the caller passes a wrong path.

    Parameters
    ----------
    file_path:
        Path to the audio file to delete.

    Returns
    -------
    bool
        ``True`` if the file was deleted successfully, ``False`` otherwise
        (file not found, wrong extension, or permission error).
    """
    path = Path(file_path)

    if path.suffix.lower() not in _AUDIO_SUFFIXES:
        logger.warning(
            "cleanup_audio_file: skipped '%s' — not a recognised audio extension.",
            path,
        )
        return False

    if not path.exists():
        logger.warning("cleanup_audio_file: '%s' does not exist — skipping.", path)
        return False

    try:
        path.unlink()
        logger.info("Deleted audio file: %s", path)
        return True
    except OSError as exc:
        logger.error("Failed to delete '%s': %s", path, exc)
        return False


def cleanup_download_dir(directory: str | Path) -> int:
    """Delete **all** audio files inside *directory* (non-recursive).

    Parameters
    ----------
    directory:
        The folder to clean.  Sub-directories are **not** traversed.

    Returns
    -------
    int
        Number of files successfully deleted.

    Raises
    ------
    NotADirectoryError
        If *directory* exists but is not a directory.
    """
    dir_path = Path(directory)

    if not dir_path.exists():
        logger.debug("cleanup_download_dir: '%s' does not exist — nothing to do.", dir_path)
        return 0

    if not dir_path.is_dir():
        raise NotADirectoryError(f"'{dir_path}' is not a directory.")

    deleted = 0
    for entry in dir_path.iterdir():
        if entry.is_file() and entry.suffix.lower() in _AUDIO_SUFFIXES:
            if cleanup_audio_file(entry):
                deleted += 1

    logger.info("cleanup_download_dir: deleted %d file(s) from '%s'.", deleted, dir_path)
    return deleted


def sanitise_filename(raw: str, max_length: int = 180) -> str:
    """Convert an arbitrary string into a safe cross-platform filename stem.

    - Strips leading/trailing whitespace.
    - Replaces characters that are illegal on Windows / macOS / Linux with ``_``.
    - Collapses consecutive underscores.
    - Truncates to *max_length* characters.

    Parameters
    ----------
    raw:
        The original string (e.g. a YouTube video title).
    max_length:
        Maximum length of the returned stem (default 180, leaving room for
        an extension without hitting the 255-char filename limit).

    Returns
    -------
    str
        A filename-safe string.  Falls back to ``"audio_file"`` if the
        result would otherwise be empty.
    """
    stem = raw.strip()
    # Replace illegal characters with underscore
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1F]', "_", stem)
    # Collapse runs of whitespace/underscores
    stem = re.sub(r"[\s_]+", "_", stem)
    stem = stem.strip("_")
    stem = stem[:max_length] or "audio_file"
    return stem
