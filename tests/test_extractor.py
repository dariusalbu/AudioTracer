"""
tests/test_extractor.py
=======================
Unit tests for app.core.extractor.

Network access is fully avoided — ``yt_dlp.YoutubeDL`` is mocked in every
test that would otherwise make an outbound connection.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yt_dlp

from app.core.extractor import (
    ExtractionError,
    InvalidURLError,
    _is_url,
    _make_progress_hook,
    download_youtube_audio,
)


# ---------------------------------------------------------------------------
# _is_url (internal helper — tested via white-box)
# ---------------------------------------------------------------------------


class TestIsUrl:
    @pytest.mark.parametrize(
        "value",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtu.be/abc123",
            "www.youtube.com/watch?v=abc",
        ],
    )
    def test_returns_true_for_url_like_strings(self, value: str) -> None:
        assert _is_url(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "/home/user/audio.mp3",
            "C:\\Users\\audio.wav",
            "relative/path/file.m4a",
            "",
        ],
    )
    def test_returns_false_for_local_paths(self, value: str) -> None:
        assert _is_url(value) is False


# ---------------------------------------------------------------------------
# _make_progress_hook
# ---------------------------------------------------------------------------


class TestMakeProgressHook:
    def test_calls_callback_with_correct_percent(self) -> None:
        received: list[float] = []
        callback = lambda d, t, p: received.append(p)
        hook = _make_progress_hook(callback)

        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})

        assert len(received) == 1
        assert received[0] == pytest.approx(50.0)

    def test_ignores_non_downloading_status(self) -> None:
        received: list = []
        hook = _make_progress_hook(lambda d, t, p: received.append(p))

        hook({"status": "finished"})
        hook({"status": "error"})

        assert received == []

    def test_no_callback_does_not_raise(self) -> None:
        hook = _make_progress_hook(None)
        hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})

    def test_zero_total_bytes_produces_zero_percent(self) -> None:
        received: list[float] = []
        hook = _make_progress_hook(lambda d, t, p: received.append(p))

        hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 0})

        assert received[0] == pytest.approx(0.0)

    def test_callback_exception_is_swallowed(self) -> None:
        """A buggy callback must never crash the download thread."""

        def bad_callback(d, t, p):
            raise RuntimeError("boom")

        hook = _make_progress_hook(bad_callback)
        # Must not raise
        hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})


# ---------------------------------------------------------------------------
# download_youtube_audio — input validation (no network)
# ---------------------------------------------------------------------------


class TestDownloadYoutubeAudioValidation:
    def test_empty_url_raises_invalid_url_error(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidURLError, match="empty"):
            download_youtube_audio("", str(tmp_path))

    def test_whitespace_only_url_raises_invalid_url_error(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidURLError, match="empty"):
            download_youtube_audio("   ", str(tmp_path))

    def test_url_without_scheme_raises_invalid_url_error(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidURLError, match="valid"):
            download_youtube_audio("youtube.com/watch?v=abc", str(tmp_path))

    def test_ftp_scheme_raises_invalid_url_error(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidURLError):
            download_youtube_audio("ftp://youtube.com/watch?v=abc", str(tmp_path))


# ---------------------------------------------------------------------------
# download_youtube_audio — yt-dlp errors (mocked)
# ---------------------------------------------------------------------------


class TestDownloadYoutubeAudioYtDlpErrors:
    """Mock yt_dlp.YoutubeDL to exercise error-handling paths without network."""

    def _make_mock_ctx(self, mocker, side_effect):
        """Return a context-manager mock whose extract_info raises side_effect."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        mocker.patch("app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx)
        return mock_ydl

    def test_unsupported_url_message_raises_invalid_url_error(
        self, mocker, tmp_path: Path
    ) -> None:
        self._make_mock_ctx(
            mocker,
            yt_dlp.utils.DownloadError("is not a valid URL"),
        )
        with pytest.raises(InvalidURLError):
            download_youtube_audio("https://youtube.com/watch?v=BAD", str(tmp_path))

    def test_unsupported_url_keyword_raises_invalid_url_error(
        self, mocker, tmp_path: Path
    ) -> None:
        self._make_mock_ctx(
            mocker,
            yt_dlp.utils.DownloadError("Unsupported URL: https://nosite.xyz"),
        )
        with pytest.raises(InvalidURLError):
            download_youtube_audio("https://nosite.xyz/video", str(tmp_path))

    def test_generic_download_error_raises_extraction_error(
        self, mocker, tmp_path: Path
    ) -> None:
        self._make_mock_ctx(
            mocker,
            yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests"),
        )
        with pytest.raises(ExtractionError, match="Download failed"):
            download_youtube_audio("https://youtube.com/watch?v=abc", str(tmp_path))

    def test_none_metadata_raises_extraction_error(
        self, mocker, tmp_path: Path
    ) -> None:
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None  # yt-dlp returned nothing

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx)

        with pytest.raises(ExtractionError, match="no metadata"):
            download_youtube_audio("https://youtube.com/watch?v=abc", str(tmp_path))

    def test_no_mp3_on_disk_raises_extraction_error(
        self, mocker, tmp_path: Path
    ) -> None:
        """Simulate successful download but ffmpeg failed to produce an mp3."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"title": "Some Video"}

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx)

        # tmp_path is empty — no mp3 will be found
        with pytest.raises(ExtractionError, match="no MP3 file"):
            download_youtube_audio("https://youtube.com/watch?v=abc", str(tmp_path))

    def test_unexpected_exception_wrapped_as_extraction_error(
        self, mocker, tmp_path: Path
    ) -> None:
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = RuntimeError("unexpected crash")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx)

        with pytest.raises(ExtractionError, match="Unexpected error"):
            download_youtube_audio("https://youtube.com/watch?v=abc", str(tmp_path))


# ---------------------------------------------------------------------------
# download_youtube_audio — happy path (mocked yt-dlp + pre-seeded mp3)
# ---------------------------------------------------------------------------


class TestDownloadYoutubeAudioSuccess:
    def _mock_successful_ydl(self, mocker, title: str):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {"title": title}

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mocker.patch("app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx)
        return mock_ydl

    def test_returns_string_path(self, mocker, tmp_path: Path) -> None:
        self._mock_successful_ydl(mocker, "My Great Video")
        # Pre-seed the mp3 the extractor would find via fallback glob
        (tmp_path / "My_Great_Video.mp3").write_bytes(b"fake mp3 data")

        result = download_youtube_audio(
            "https://youtube.com/watch?v=abc", str(tmp_path)
        )

        assert isinstance(result, str)
        assert result.endswith(".mp3")

    def test_returned_path_exists_on_disk(self, mocker, tmp_path: Path) -> None:
        self._mock_successful_ydl(mocker, "Lecture 101")
        (tmp_path / "Lecture_101.mp3").write_bytes(b"audio bytes")

        result = download_youtube_audio(
            "https://youtube.com/watch?v=xyz", str(tmp_path)
        )

        assert Path(result).exists()

    def test_fallback_resolves_newest_mp3(self, mocker, tmp_path: Path) -> None:
        """When the sanitised filename does not match, the newest mp3 is returned."""
        self._mock_successful_ydl(mocker, "Video: Special? Chars!")
        # Only a differently-named mp3 exists — triggers the fallback path
        fallback = tmp_path / "actually_downloaded.mp3"
        fallback.write_bytes(b"bytes")

        result = download_youtube_audio(
            "https://youtube.com/watch?v=abc", str(tmp_path)
        )

        assert Path(result).name == fallback.name

    def test_progress_callback_is_invoked(self, mocker, tmp_path: Path) -> None:
        """The progress_callback must be wired into the yt-dlp hook."""
        received: list[tuple] = []

        def callback(downloaded, total, percent):
            received.append((downloaded, total, percent))

        # Patch YoutubeDL to call the hook once during extract_info
        def fake_extract_info(url, download):
            # Simulate the hook being called by yt-dlp
            opts = mock_ydl_cls.call_args[0][0]  # positional dict arg
            for hook in opts.get("progress_hooks", []):
                hook(
                    {
                        "status": "downloading",
                        "downloaded_bytes": 1_048_576,
                        "total_bytes": 10_485_760,
                    }
                )
            return {"title": "Hook Test"}

        (tmp_path / "Hook_Test.mp3").write_bytes(b"data")

        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = fake_extract_info
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ydl_cls = mocker.patch(
            "app.core.extractor.yt_dlp.YoutubeDL", return_value=mock_ctx
        )

        download_youtube_audio(
            "https://youtube.com/watch?v=abc", str(tmp_path), callback
        )

        assert len(received) >= 1
        _, _, pct = received[0]
        assert 0.0 <= pct <= 100.0

    def test_output_directory_created_if_missing(self, mocker, tmp_path: Path) -> None:
        """output_dir must be created automatically when it doesn't exist."""
        new_dir = tmp_path / "new" / "nested" / "dir"
        self._mock_successful_ydl(mocker, "Video")
        (new_dir / "Video.mp3").mkdir(parents=True)
        # Rewrite as file
        (new_dir / "Video.mp3").rmdir()
        (new_dir / "Video.mp3").write_bytes(b"mp3")

        result = download_youtube_audio(
            "https://youtube.com/watch?v=abc", str(new_dir)
        )

        assert new_dir.exists()
        assert result.endswith(".mp3")
