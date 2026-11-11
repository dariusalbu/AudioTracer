"""
build.py
========
PyInstaller packaging script for AudioTracer.

Packages ``app/main.py`` into a distributable executable in the ``dist/``
folder.  Run from the project root after activating your virtual environment::

    pip install pyinstaller
    python build.py

Options
-------
Pass ``--onefile`` on the command line to produce a single-file portable
executable (slower startup, easier distribution)::

    python build.py --onefile

Pass ``--debug`` to keep the console window open (useful for diagnosing
startup crashes in the packaged build)::

    python build.py --debug

Both flags can be combined::

    python build.py --onefile --debug
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent
ENTRY_POINT: Path = PROJECT_ROOT / "app" / "main.py"
DIST_DIR: Path = PROJECT_ROOT / "dist"
BUILD_DIR: Path = PROJECT_ROOT / "build"
SPEC_DIR: Path = PROJECT_ROOT  # .spec file lands here
APP_NAME: str = "AudioTracer"

# Optional: path to a Windows .ico file (comment out if none exists yet)
# ICON_PATH: Path = PROJECT_ROOT / "resources" / "icon.ico"

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# PyInstaller's static analyser cannot always follow dynamic imports inside
# third-party packages.  List them all explicitly here.

HIDDEN_IMPORTS: list[str] = [
    # ── PyQt6 ──────────────────────────────────────────────────────────
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    # ── faster-whisper / CTranslate2 ──────────────────────────────────
    "faster_whisper",
    "faster_whisper.audio",
    "faster_whisper.tokenizer",
    "faster_whisper.transcribe",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "huggingface_hub.file_download",
    "huggingface_hub.repository",
    # ── yt-dlp ────────────────────────────────────────────────────────
    "yt_dlp",
    "yt_dlp.utils",
    "yt_dlp.extractor",
    "yt_dlp.extractor.youtube",
    "yt_dlp.postprocessor",
    "yt_dlp.downloader",
    # ── Google Gemini (google-genai) ──────────────────────────────────
    "google",
    "google.genai",
    "google.auth",
    "google.auth.transport",
    "httpx",
    # ── Standard library modules that sometimes trip up PyInstaller ───
    "logging.handlers",
    "pathlib",
    "tempfile",
    "dataclasses",
    # ── App modules (belt-and-suspenders) ────────────────────────────
    "app",
    "app.core",
    "app.core.extractor",
    "app.core.transcriber",
    "app.core.synthesizer",
    "app.ui",
    "app.ui.worker",
    "app.ui.main_window",
    "app.utils",
    "app.utils.file_manager",
]

# ---------------------------------------------------------------------------
# Data files to bundle
# ---------------------------------------------------------------------------
# Format: list of ("source_glob_or_path", "dest_folder_inside_bundle")
#
# faster-whisper downloads Whisper model weights at runtime from Hugging Face;
# if you want an offline build, download a model first and add it here, e.g.:
#   (str(Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-base"), "models")

DATAS: list[tuple[str, str]] = [
    # Uncomment to bundle a pre-downloaded model:
    # (str(Path.home() / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-base"), "models"),
]

# ---------------------------------------------------------------------------
# Excludes — trim packages that are definitely not needed to reduce exe size
# ---------------------------------------------------------------------------

EXCLUDES: list[str] = [
    "tkinter",
    "matplotlib",
    "numpy",      # only needed transitively; PyInstaller usually resolves it
    "scipy",
    "PIL",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "pytest_mock",
    "pytest_qt",
]


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


def _check_pyinstaller() -> None:
    """Abort early with a friendly message if PyInstaller is not installed."""
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "ERROR: PyInstaller is not installed.\n"
            "Install it with:  pip install pyinstaller\n",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"PyInstaller {result.stdout.strip()} detected.")


def _clean_previous_build() -> None:
    """Remove stale build artefacts so the build starts from a clean slate."""
    for stale in [BUILD_DIR, DIST_DIR]:
        if stale.exists():
            print(f"  Removing {stale} …")
            shutil.rmtree(stale)

    # Remove any existing .spec file for this app
    spec_file = SPEC_DIR / f"{APP_NAME}.spec"
    if spec_file.exists():
        print(f"  Removing {spec_file} …")
        spec_file.unlink()


def _build_pyinstaller_args(onefile: bool, debug: bool) -> list[str]:
    """Assemble the full ``pyinstaller`` command-line argument list."""
    args: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(ENTRY_POINT),
        f"--name={APP_NAME}",
        "--noconfirm",           # overwrite dist without asking
        "--clean",               # wipe PyInstaller cache before build
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={SPEC_DIR}",
    ]

    # ── Packaging mode ────────────────────────────────────────────────
    if onefile:
        args.append("--onefile")
        print("  Mode: single-file executable (--onefile)")
    else:
        args.append("--onedir")
        print("  Mode: one-directory bundle  (--onedir)")

    # ── Console / windowed ────────────────────────────────────────────
    if debug:
        args.append("--console")
        print("  Console: visible (--debug)")
    else:
        args.append("--windowed")

    # ── Optional icon ─────────────────────────────────────────────────
    # icon = PROJECT_ROOT / "resources" / "icon.ico"
    # if icon.exists():
    #     args.append(f"--icon={icon}")

    # ── Hidden imports ────────────────────────────────────────────────
    for imp in HIDDEN_IMPORTS:
        args.append(f"--hidden-import={imp}")

    # ── Data files ───────────────────────────────────────────────────
    for src, dst in DATAS:
        args.append(f"--add-data={src}{':' if sys.platform != 'win32' else ';'}{dst}")

    # ── Excludes ─────────────────────────────────────────────────────
    for exc in EXCLUDES:
        args.append(f"--exclude-module={exc}")

    return args


def _print_summary(onefile: bool) -> None:
    """Print the location of the finished build artefact."""
    print("\n" + "=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    if onefile:
        exe = DIST_DIR / f"{APP_NAME}.exe"
        print(f"  Executable : {exe}")
    else:
        bundle = DIST_DIR / APP_NAME
        exe = bundle / f"{APP_NAME}.exe"
        print(f"  Bundle dir : {bundle}")
        print(f"  Executable : {exe}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the PyInstaller build."""
    parser = argparse.ArgumentParser(
        description="Package AudioTracer as a standalone executable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        default=False,
        help="Produce a single .exe (slower startup; easier to share).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Keep the console window open (useful for diagnosing crashes).",
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        default=False,
        help="Do not remove previous build artefacts before building.",
    )
    args = parser.parse_args()

    print("\n AudioTracer — Build Script")
    print(" " + "─" * 42)

    _check_pyinstaller()

    if not args.skip_clean:
        print("\n[1/3] Cleaning previous build artefacts …")
        _clean_previous_build()
    else:
        print("\n[1/3] Skipping clean (--skip-clean).")

    print("\n[2/3] Assembling PyInstaller command …")
    cmd = _build_pyinstaller_args(onefile=args.onefile, debug=args.debug)

    print(f"\n[3/3] Running PyInstaller …")
    print(f"  Entry point : {ENTRY_POINT}")
    print(f"  Output dir  : {DIST_DIR}\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print(
            f"\nERROR: PyInstaller exited with code {result.returncode}.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)

    _print_summary(onefile=args.onefile)


if __name__ == "__main__":
    main()
