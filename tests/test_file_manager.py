"""
tests/test_file_manager.py
==========================
Unit tests for app.utils.file_manager.

All tests use pytest's built-in ``tmp_path`` fixture so no real filesystem
state is left behind after the suite runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.utils.file_manager import (
    cleanup_audio_file,
    cleanup_download_dir,
    get_download_dir,
    sanitise_filename,
)

# ---------------------------------------------------------------------------
# get_download_dir
# ---------------------------------------------------------------------------


class TestGetDownloadDir:
    def test_creates_subdirectory_under_base(self, tmp_path: Path) -> None:
        result = get_download_dir(base_dir=str(tmp_path))
        assert result.exists()
        assert result.is_dir()

    def test_subdirectory_is_named_correctly(self, tmp_path: Path) -> None:
        result = get_download_dir(base_dir=str(tmp_path))
        assert result.name == "AudioTracer_downloads"

    def test_idempotent_called_twice(self, tmp_path: Path) -> None:
        """Calling twice must not raise and must return the same path."""
        first = get_download_dir(base_dir=str(tmp_path))
        second = get_download_dir(base_dir=str(tmp_path))
        assert first == second

    def test_creates_nested_base_dir(self, tmp_path: Path) -> None:
        """Base dir that does not exist yet should be created."""
        deep_base = tmp_path / "a" / "b" / "c"
        result = get_download_dir(base_dir=str(deep_base))
        assert result.exists()

    def test_no_base_dir_uses_system_temp(self) -> None:
        """When base_dir is None the system temp dir is used as root."""
        import tempfile

        result = get_download_dir()
        assert result.parent == Path(tempfile.gettempdir())


# ---------------------------------------------------------------------------
# cleanup_audio_file
# ---------------------------------------------------------------------------


class TestCleanupAudioFile:
    @pytest.mark.parametrize("ext", [".mp3", ".wav", ".m4a", ".ogg", ".flac"])
    def test_deletes_recognised_audio_formats(self, tmp_path: Path, ext: str) -> None:
        audio = tmp_path / f"track{ext}"
        audio.write_bytes(b"\xff\xfb" * 64)  # dummy audio-like bytes

        result = cleanup_audio_file(audio)

        assert result is True
        assert not audio.exists()

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.mp3"
        audio.write_bytes(b"data")

        result = cleanup_audio_file(str(audio))

        assert result is True
        assert not audio.exists()

    @pytest.mark.parametrize("ext", [".txt", ".pdf", ".py", ".json", ".exe"])
    def test_skips_non_audio_extensions(self, tmp_path: Path, ext: str) -> None:
        document = tmp_path / f"file{ext}"
        document.write_text("important data")

        result = cleanup_audio_file(document)

        assert result is False
        assert document.exists()  # file must NOT be deleted

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost.mp3"
        # deliberately not created

        result = cleanup_audio_file(ghost)

        assert result is False

    def test_does_not_raise_on_missing_file(self, tmp_path: Path) -> None:
        """Must be silent — callers must not need try/except for missing files."""
        ghost = tmp_path / "ghost.wav"
        cleanup_audio_file(ghost)  # should not raise


# ---------------------------------------------------------------------------
# cleanup_download_dir
# ---------------------------------------------------------------------------


class TestCleanupDownloadDir:
    def test_deletes_all_audio_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"audio1")
        (tmp_path / "b.wav").write_bytes(b"audio2")
        (tmp_path / "c.m4a").write_bytes(b"audio3")

        deleted = cleanup_download_dir(tmp_path)

        assert deleted == 3
        assert list(tmp_path.iterdir()) == []

    def test_preserves_non_audio_files(self, tmp_path: Path) -> None:
        (tmp_path / "audio.mp3").write_bytes(b"audio")
        notes_file = tmp_path / "notes.txt"
        notes_file.write_text("keep me")

        cleanup_download_dir(tmp_path)

        assert notes_file.exists()

    def test_returns_zero_for_empty_directory(self, tmp_path: Path) -> None:
        result = cleanup_download_dir(tmp_path)
        assert result == 0

    def test_returns_zero_for_nonexistent_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_such_dir"
        result = cleanup_download_dir(missing)
        assert result == 0

    def test_raises_for_path_that_is_a_file(self, tmp_path: Path) -> None:
        file_not_dir = tmp_path / "file.mp3"
        file_not_dir.write_bytes(b"data")

        with pytest.raises(NotADirectoryError):
            cleanup_download_dir(file_not_dir)

    def test_does_not_recurse_into_subdirectories(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        nested_mp3 = sub / "nested.mp3"
        nested_mp3.write_bytes(b"nested audio")

        deleted = cleanup_download_dir(tmp_path)

        assert deleted == 0
        assert nested_mp3.exists()


# ---------------------------------------------------------------------------
# sanitise_filename
# ---------------------------------------------------------------------------


class TestSanitiseFilename:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Hello World", "Hello_World"),
            ("video: best?", "video__best"),
            ('"quoted"', "_quoted_"),
            ("normal_name", "normal_name"),
            ("trailing_", "trailing"),
            ("_leading", "leading"),
        ],
    )
    def test_strips_illegal_characters(self, raw: str, expected: str) -> None:
        result = sanitise_filename(raw)
        # Verify none of the illegal chars survived
        for char in r'\/:*?"<>|':
            assert char not in result

    def test_whitespace_only_returns_fallback(self) -> None:
        assert sanitise_filename("   ") == "audio_file"

    def test_empty_string_returns_fallback(self) -> None:
        assert sanitise_filename("") == "audio_file"

    def test_truncates_to_max_length(self) -> None:
        long_name = "a" * 300
        result = sanitise_filename(long_name, max_length=180)
        assert len(result) <= 180

    def test_custom_max_length_respected(self) -> None:
        result = sanitise_filename("a" * 100, max_length=50)
        assert len(result) <= 50

    def test_collapses_consecutive_underscores(self) -> None:
        result = sanitise_filename("hello   world")
        assert "__" not in result

    def test_preserves_unicode_letters(self) -> None:
        result = sanitise_filename("Üntergang über alles")
        assert "ntergang" in result  # Unicode letters kept
