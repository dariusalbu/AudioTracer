# 🎙 AudioTracer

> **Download · Transcribe · Summarise — entirely on your machine.**

AudioTracer is a native desktop application that takes a YouTube URL (or a local audio file), downloads the audio track, transcribes it locally using [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and generates clean, structured Markdown notes — all without sending your audio to a third-party server.

---

## ✨ Features

- 🔗 **YouTube audio extraction** via `yt-dlp` — no browser extension needed
- 🧠 **Local transcription** via `faster-whisper` (Whisper large-v3 runs on CPU _or_ CUDA GPU)
- 📝 **AI note synthesis** — Key Takeaways, Action Items, and a full summary
- 🔌 **Swappable AI backends** — ships with a mock; drop in Gemini or OpenAI via env var
- 🖥 **Native dark-themed GUI** — PyQt6, never freezes during heavy work
- 💾 **One-click Markdown export**
- 🧪 **Fully tested** — pytest unit suite with mocked network/model calls

---

## 📋 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.10 + | 3.11 or 3.12 recommended |
| **ffmpeg** | Any recent | Required by `yt-dlp` for audio conversion |
| **CUDA** _(optional)_ | 11.8 / 12.x | For GPU-accelerated transcription |

### Installing ffmpeg

**Windows (winget):**
```powershell
winget install ffmpeg
```

**Windows (Chocolatey):**
```powershell
choco install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu / Debian:**
```bash
sudo apt install ffmpeg
```

---

## 🚀 Installation

### 1 · Clone the repository

```bash
git clone https://github.com/your-org/AudioTracer.git
cd AudioTracer
```

### 2 · Create and activate a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3 · Install dependencies

```bash
pip install -r requirements.txt
```

> **GPU users:** After the standard install, replace the CPU build of CTranslate2 with the CUDA variant:
> ```bash
> pip install ctranslate2 --extra-index-url https://download.pytorch.org/whl/cu121
> ```

---

## ▶ Running the App

```bash
python app/main.py
```

The application window will open. Paste a YouTube URL (or click **Browse…** to pick a local MP3/WAV) and press **▶ Start Transcription**.

### Runtime log

Logs are written to:
```
~/AudioTracer/logs/audiotracer.log
```
(rotated at 2 MB, 4 backups kept)

---

## ⚙️ Configuration

All settings are controlled via environment variables — no config file to edit.

| Variable | Default | Description |
|---|---|---|
| `AUDIOTRACER_WHISPER_MODEL` | `base` | Whisper model size: `tiny` · `base` · `small` · `medium` · `large-v3` |
| `AUDIOTRACER_DEVICE` | `cpu` | Inference device: `cpu` or `cuda` |
| `AUDIOTRACER_COMPUTE_TYPE` | `int8` | Quantisation: `int8` (CPU) · `float16` (GPU) · `float32` |
| `AUDIOTRACER_BACKEND` | `mock` | Note-generation backend: `mock` or `gemini` |
| `GEMINI_API_KEY` | _(none)_ | Required when `AUDIOTRACER_BACKEND=gemini` |
| `AUDIOTRACER_OUTPUT_DIR` | `~/AudioTracer/output` | Default export directory |
| `AUDIOTRACER_TEMP_DIR` | system temp | Scratch directory for downloaded audio |

### Example — use Gemini for note generation

```powershell
# Windows PowerShell
$env:AUDIOTRACER_BACKEND = "gemini"
$env:GEMINI_API_KEY      = "AIza..."
python app/main.py
```

```bash
# macOS / Linux
AUDIOTRACER_BACKEND=gemini GEMINI_API_KEY=AIza... python app/main.py
```

### Example — large model on GPU

```bash
AUDIOTRACER_WHISPER_MODEL=large-v3 AUDIOTRACER_DEVICE=cuda AUDIOTRACER_COMPUTE_TYPE=float16 python app/main.py
```

---

## 🧪 Running the Test Suite

```bash
# Install test dependencies (included in requirements.txt)
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=app --cov-report=term-missing

# Run a single test file
pytest tests/test_file_manager.py -v

# Run a single test class
pytest tests/test_extractor.py::TestDownloadYoutubeAudioValidation -v
```

> **Note:** All tests mock network and model calls — no internet connection or GPU is required to run the suite.

### Test matrix

| File | Scope | Mocks |
|---|---|---|
| `test_file_manager.py` | Unit — filesystem helpers | Real FS via `tmp_path` |
| `test_extractor.py` | Unit — download & error handling | `yt_dlp.YoutubeDL` |
| _(planned)_ `test_transcriber.py` | Unit — Whisper wrapper | `faster_whisper.WhisperModel` |
| _(planned)_ `test_synthesizer.py` | Unit — all backends | HTTP calls, `google.genai` |
| _(planned)_ `test_ui.py` | GUI smoke tests | `pytest-qt` `qtbot` |

---

## 📦 Building a Standalone Executable

The `build.py` script wraps PyInstaller with all required hidden imports pre-configured.

### Install PyInstaller

```bash
pip install pyinstaller
```

### One-directory bundle _(recommended — faster startup)_

```bash
python build.py
```

Output: `dist/AudioTracer/AudioTracer.exe`

### Single-file portable executable

```bash
python build.py --onefile
```

Output: `dist/AudioTracer.exe`

### Debug build _(keeps console window open)_

```bash
python build.py --debug
```

### All options

```
usage: build.py [-h] [--onefile] [--debug] [--skip-clean]

  --onefile     Produce a single .exe (slower startup; easier to share).
  --debug       Keep the console window open (useful for diagnosing crashes).
  --skip-clean  Do not remove previous build artefacts before building.
```

> **ffmpeg in the bundle:** PyInstaller does not automatically include ffmpeg. Place `ffmpeg.exe` alongside `AudioTracer.exe` in the `dist/` folder, or add it to the system PATH on the target machine.

---

## 🗂 Project Structure

```
AudioTracer/
├── app/
│   ├── main.py                  # Entry point — QApplication + logging bootstrap
│   ├── core/
│   │   ├── extractor.py         # yt-dlp wrapper (download_youtube_audio)
│   │   ├── transcriber.py       # faster-whisper wrapper (Transcriber class)
│   │   └── synthesizer.py       # AI note generation (mock + Gemini backends)
│   ├── ui/
│   │   ├── main_window.py       # Dark-themed MainWindow (QMainWindow)
│   │   └── worker.py            # TranscriptionWorker (QThread)
│   └── utils/
│       └── file_manager.py      # Temp dir creation + audio file cleanup
├── tests/
│   ├── test_file_manager.py     # Filesystem helper tests
│   └── test_extractor.py        # Extractor unit tests (mocked yt-dlp)
├── architecture_spec.md         # Full system design document
├── build.py                     # PyInstaller packaging script
└── requirements.txt             # Pinned Python dependencies
```

---

## 🔄 Data Flow

```
YouTube URL / Local File
        │
        ▼
 TranscriptionWorker (QThread)
        │
        ├─► extractor.py      download_youtube_audio()   ──► .mp3
        │
        ├─► transcriber.py    Transcriber.transcribe()   ──► TranscriptResult
        │
        ├─► synthesizer.py    generate_summary()         ──► Markdown str
        │
        └─► file_manager.py   cleanup_audio_file()       ──► disk freed
                │
                │  Qt signals (thread-safe)
                ▼
        MainWindow (main thread)
        ├── progress bar updates
        ├── AI Summary tab
        └── Raw Transcript tab
```

---

## 🤝 Contributing

1. Fork the repository and create a feature branch.
2. Run the test suite (`pytest tests/ -v`) — all tests must pass.
3. Add or update tests for any new behaviour.
4. Submit a pull request with a clear description of changes.

---

## 📄 License

MIT License — see `LICENSE` for details.
