# AudioTracer — Architecture Specification

> **Version:** 1.0 | **Status:** Initial Design | **Date:** 2026-11-12

---

## 1. Project Overview

**AudioTracer** is a native desktop application that:
1. Accepts YouTube URLs as input.
2. Downloads the audio track locally via `yt-dlp`.
3. Transcribes the audio locally via `faster-whisper` (runs on CPU or CUDA GPU).
4. Sends the transcript to an AI endpoint (mocked; swappable for Gemini / OpenAI) to generate structured Markdown notes.
5. Presents and exports the notes through a PyQt6 GUI.

All heavy work (download, transcription, AI call) runs on **background QThreads** — the main thread is reserved exclusively for the GUI event loop.

---

## 2. File & Directory Structure

```
AudioTracer/
├── main.py                          # Entry point — creates QApplication, launches MainWindow
├── requirements.txt                 # Pinned dependencies
├── architecture_spec.md             # This document
│
├── app/
│   ├── __init__.py
│   │
│   ├── core/                        # Pure business logic — no Qt imports
│   │   ├── __init__.py
│   │   ├── downloader.py            # yt-dlp wrapper — downloads audio to temp file
│   │   ├── transcriber.py           # faster-whisper wrapper — returns plain text
│   │   ├── note_generator.py        # AI client abstraction — returns Markdown string
│   │   └── pipeline.py              # Orchestrates downloader → transcriber → note_generator
│   │
│   ├── ui/                          # PyQt6 views and worker threads
│   │   ├── __init__.py
│   │   ├── main_window.py           # MainWindow(QMainWindow) — top-level shell
│   │   ├── input_panel.py           # URL input bar + "Trace" button widget
│   │   ├── progress_panel.py        # QProgressBar + status label widget
│   │   ├── notes_panel.py           # QTextEdit markdown preview + export button
│   │   └── worker.py                # PipelineWorker(QThread) — runs pipeline off GUI thread
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config.py                # App-wide settings (paths, model name, API key env var)
│       ├── logger.py                # Centralised logging setup (rotating file + console)
│       └── file_helpers.py          # Temp-dir management, safe filename sanitisation, export
│
└── tests/
    ├── __init__.py
    ├── test_downloader.py           # Unit tests for downloader (yt-dlp mocked)
    ├── test_transcriber.py          # Unit tests for transcriber (faster-whisper mocked)
    ├── test_note_generator.py       # Unit tests for note_generator (HTTP mocked)
    ├── test_pipeline.py             # Integration test for full pipeline (all deps mocked)
    └── test_ui.py                   # pytest-qt smoke tests for MainWindow
```

---

## 3. Module Responsibilities

### 3.1 `app/core/downloader.py`
| Concern | Detail |
|---|---|
| **Input** | YouTube URL (`str`) |
| **Output** | Path to downloaded `.mp3` / `.wav` temp file (`pathlib.Path`) |
| **Library** | `yt-dlp` via Python API (`yt_dlp.YoutubeDL`) |
| **Config** | Output template, audio format, quality all read from `utils/config.py` |
| **Errors** | Raises `DownloadError(Exception)` on network/format failure |

### 3.2 `app/core/transcriber.py`
| Concern | Detail |
|---|---|
| **Input** | Path to audio file (`pathlib.Path`) |
| **Output** | Full transcript as plain `str` |
| **Library** | `faster_whisper.WhisperModel` |
| **Config** | Model size (`tiny` → `large-v3`), device (`cpu`/`cuda`), compute type — from `config.py` |
| **Errors** | Raises `TranscriptionError(Exception)` |

### 3.3 `app/core/note_generator.py`
| Concern | Detail |
|---|---|
| **Input** | Transcript `str` |
| **Output** | Structured Markdown notes `str` |
| **Interface** | Abstract base class `NoteGeneratorBase` with `generate(transcript: str) -> str` |
| **Implementations** | `MockNoteGenerator` (returns templated Markdown), `GeminiNoteGenerator`, `OpenAINoteGenerator` |
| **Active impl** | Selected at startup via `config.py` → `NOTE_GENERATOR_BACKEND` env var |

### 3.4 `app/core/pipeline.py`
| Concern | Detail |
|---|---|
| **Role** | Single entry-point function `run_pipeline(url: str, callbacks: PipelineCallbacks)` |
| **Flow** | `downloader → transcriber → note_generator` sequentially |
| **Callbacks** | `PipelineCallbacks` dataclass: `on_progress(step, pct)`, `on_complete(notes)`, `on_error(exc)` |
| **No Qt** | Communicates results only through the callbacks dataclass — zero Qt coupling |

### 3.5 `app/ui/worker.py`
| Concern | Detail |
|---|---|
| **Class** | `PipelineWorker(QThread)` |
| **Signals** | `progress = pyqtSignal(str, int)`, `completed = pyqtSignal(str)`, `failed = pyqtSignal(str)` |
| **Run** | `run()` calls `pipeline.run_pipeline()`, bridges `PipelineCallbacks` → Qt signals |
| **Lifecycle** | Created per-job, started by `MainWindow`, auto-deleted on `finished` signal |

### 3.6 `app/ui/main_window.py`
| Concern | Detail |
|---|---|
| **Class** | `MainWindow(QMainWindow)` |
| **Owns** | `InputPanel`, `ProgressPanel`, `NotesPanel`, `PipelineWorker` (one at a time) |
| **Wires** | Connects worker signals → panel slots |
| **Guards** | Disables input while a job is running; re-enables on `completed` or `failed` |

---

## 4. Data Flow Diagram

```
+--------------------------------------------------------------------------+
|  MAIN THREAD (Qt Event Loop)                                             |
|                                                                          |
|  +-------------+   URL    +------------------------------------------+  |
|  |  InputPanel  | -------> |           MainWindow                     |  |
|  |  (QWidget)   |          |  - creates PipelineWorker                |  |
|  +-------------+          |  - connects signals <-> slots             |  |
|                            |  - calls worker.start()                   |  |
|  +-------------+           +------------------+-----------------------+  |
|  |ProgressPanel| <-- progress signal ----------|                         |
|  |  (QWidget)  |                               | Qt Signal/Slot          |
|  +-------------+ <-- completed signal ---------|  (thread-safe)          |
|  +-------------+                               |                         |
|  |  NotesPanel | <-- completed signal ----------+                        |
|  |  (QTextEdit)|                                                         |
|  +-------------+                                                         |
+-----------------------------------------------------------------------+--+
                                                                        |  QThread.start()
+-----------------------------------------------------------------------v--+
|  BACKGROUND THREAD (PipelineWorker : QThread)                            |
|                                                                           |
|   run()                                                                   |
|    |                                                                      |
|    +-> downloader.download(url)          -> audio_path: Path             |
|    |       emit progress("Downloading", 10..50)                          |
|    |                                                                      |
|    +-> transcriber.transcribe(audio_path) -> transcript: str            |
|    |       emit progress("Transcribing", 51..85)                         |
|    |                                                                      |
|    +-> note_generator.generate(transcript) -> markdown: str             |
|            emit progress("Generating notes", 86..99)                     |
|            emit completed(markdown)                                       |
|                                                                           |
|   On any exception -> emit failed(str(exc))                              |
+---------------------------------------------------------------------------+
```

---

## 5. Threading Model

| Thread | Runs | Qt Allowed? |
|---|---|---|
| **Main thread** | Qt event loop, all UI rendering and signals | Yes |
| **PipelineWorker (QThread)** | `downloader`, `transcriber`, `note_generator` | No direct widget access |

**Rules enforced by design:**
- `app/core/` modules have **zero Qt imports** — this is enforced by linting.
- `PipelineWorker.run()` only emits **signals** (not slots), which Qt queues safely across threads.
- UI slots that modify widgets are always connected with `Qt.ConnectionType.QueuedConnection` (the default for cross-thread signals).
- Only **one** `PipelineWorker` can be active at a time; the UI disables the "Trace" button for the duration.

---

## 6. Configuration (`app/utils/config.py`)

| Setting | Environment Variable | Default |
|---|---|---|
| Whisper model size | `AUDIOTRACER_WHISPER_MODEL` | `base` |
| Whisper device | `AUDIOTRACER_DEVICE` | `cpu` |
| Whisper compute type | `AUDIOTRACER_COMPUTE_TYPE` | `int8` |
| Note generator backend | `AUDIOTRACER_BACKEND` | `mock` |
| Gemini API key | `GEMINI_API_KEY` | _(none)_ |
| OpenAI API key | `OPENAI_API_KEY` | _(none)_ |
| Audio output directory | `AUDIOTRACER_OUTPUT_DIR` | `~/AudioTracer/output` |
| Temp directory | `AUDIOTRACER_TEMP_DIR` | system temp |

---

## 7. AI Backend Abstraction

```python
# app/core/note_generator.py (interface sketch)

class NoteGeneratorBase(ABC):
    @abstractmethod
    def generate(self, transcript: str) -> str: ...

class MockNoteGenerator(NoteGeneratorBase):
    """Returns a deterministic Markdown template — used in dev and tests."""

class GeminiNoteGenerator(NoteGeneratorBase):
    """Uses google-genai SDK; reads GEMINI_API_KEY from env."""

class OpenAINoteGenerator(NoteGeneratorBase):
    """Uses openai SDK; reads OPENAI_API_KEY from env."""

def get_note_generator() -> NoteGeneratorBase:
    """Factory — reads AUDIOTRACER_BACKEND env var."""
```

Swapping backends requires **no UI or pipeline changes** — only the env var changes.

---

## 8. Error Handling Strategy

| Layer | Mechanism |
|---|---|
| `core/` modules | Raise typed domain exceptions (`DownloadError`, `TranscriptionError`, `NoteGenerationError`) |
| `PipelineWorker` | Catches all exceptions in `run()`, emits `failed(str(exc))` signal |
| `MainWindow` | Connects `failed` signal to a `QMessageBox.critical()` slot on the main thread |
| Logging | All exceptions logged via `utils/logger.py` before re-raising or signalling |

---

## 9. Testing Strategy

| Test File | Scope | Key Technique |
|---|---|---|
| `test_downloader.py` | Unit | Mock `yt_dlp.YoutubeDL` with `pytest-mock` |
| `test_transcriber.py` | Unit | Mock `faster_whisper.WhisperModel` |
| `test_note_generator.py` | Unit | Mock HTTP calls; test all three backends |
| `test_pipeline.py` | Integration | Mock all three core modules; verify callback ordering |
| `test_ui.py` | GUI smoke | `pytest-qt` `qtbot`; verify button state transitions |

Run all tests:
```bash
pytest tests/ -v
```

---

## 10. Dependency Versions & Rationale

| Package | Version Constraint | Reason |
|---|---|---|
| `PyQt6` | `>=6.7` | Qt 6.7 LTS — stable signal/slot cross-thread model |
| `yt-dlp` | `>=2024.11` | Active fork of youtube-dl with format selector fixes |
| `faster-whisper` | `>=1.0` | CTranslate2 backend; 4x faster than openai-whisper on CPU |
| `google-genai` | `>=0.8` | Unified Gemini + Vertex SDK |
| `pytest` | `>=8.3` | Latest stable; supports `asyncio` mode out of the box |
| `pytest-qt` | `>=4.4` | `qtbot` fixture for PyQt6 event-loop-aware testing |
| `pytest-mock` | `>=3.14` | `mocker` fixture — cleaner than `unittest.mock` |
