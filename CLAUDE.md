# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

For media features (downloading/clipping), also install `yt-dlp` and `ffmpeg` separately on the system.

### Run

```bash
# CLI — fetch and print transcript
.venv/bin/python -m youtube_script_app "https://youtu.be/VIDEO_ID" -l fr -f text-timestamps

# GUI
.venv/bin/python -m youtube_script_app.gui
```

### Tests

```bash
# All tests
.venv/bin/python -m pytest

# Single test
.venv/bin/python -m pytest tests/test_base.py::test_extract_video_id_watch
```

CI runs pytest on Python 3.10, 3.11, and 3.12 (Ubuntu). Tkinter (`python3-tk`) must be installed for the GUI tests.

### Build standalone binary (macOS/Linux)

```bash
./scripts/build_app.sh gui     # or cli / both
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 gui
```

Output lands in `dist/`. The PyInstaller entry points are in `scripts/entrypoints/`.

## Architecture

The package lives in `src/youtube_script_app/` and is split into four layers:

### `core/` — pure logic, no UI

| Module | Responsibility |
|---|---|
| `transcript_fetcher` | Extract YouTube video ID, call `youtube-transcript-api`, fall back to `yt-dlp` JSON3 subtitles on IP-block errors, return `TranscriptResult` |
| `transcript_formatter` | Convert raw transcript chunks to `text`, `text-timestamps`, or `json` |
| `moment_analyzer` | Score transcript minutes with keyword heuristics, return ranked `MomentScore` list |
| `subtitle_renderer` | Build ASS subtitle documents; clip/rechunk subtitle entries to a time window; generate Pillow-based subtitle preview images |
| `lower_third` | Generate lower-third overlay PNGs (channel name + tagline + accent bar) via Pillow |

### `video/` — ffmpeg pipeline helpers

| Module | Responsibility |
|---|---|
| `renderer` | Build and run `ffmpeg` filter-complex commands: 9:16 crop, logo overlay, ASS subtitles, video effects, progress bar, animated watermark, intro/outro fade |
| `logo_config` | `LogoConfig` dataclass — validates logo path, reads original image dimensions, normalises size/position/opacity |
| `presets` | Named creative presets (`tiktok_viral`, `podcast_clip`, etc.) that bundle a fixed set of download settings |

### `downloads/` — yt-dlp helpers

| Module | Responsibility |
|---|---|
| `utils` | Build `yt-dlp` CLI commands; normalise logo position/ratio/opacity constants; parse download size strings |
| `history` | Append and load `~/.youtube-script/download_history.json` |

### `gui.py` — Tkinter front-end (`TranscriptApp`)

Single large file (~5 000 lines). Orchestrates all layers:
- Validates URL and settings inputs.
- Runs transcript generation and downloads on background threads (never blocks the main Tk loop).
- Manages a `download_queue` (list of dicts describing each pending item: `kind`, `url`, `output_dir`, format options, logo/subtitle/effect config).
- Calls `video.renderer` and `core.subtitle_renderer` to build variants after raw download completes.
- Reads/writes `~/.youtube-script/gui_settings.json` via `settings.py` on every launch/exit.

### `base.py` — backwards-compatible re-exports

Re-exports all public symbols from `core.*` and `cli` so tests and external code can `from youtube_script_app.base import …`.

### `cli.py` — argument parser and `main()`

`build_parser()` → `main()` → `generate_transcript_with_format()`. Returns exit code 0 on success, calls `parser.error()` (exit 2) on bad input or transcript errors.

## Key data flows

**Transcript (CLI/GUI):**
`url` → `extract_video_id` → `fetch_transcript` (with yt-dlp fallback) → `format_transcript` → `analyze_most_viewed_moments` (optional)

**Download + post-process (GUI):**
`_enqueue_media_download` adds a dict to `download_queue` → `_download_media_item` runs `yt-dlp` via `subprocess.Popen` → `_build_download_variant` calls `video.renderer` functions to apply crop/logo/subtitles/effects → `_record_download_history`

## Persistent user files (never versioned)

| Path | Contents |
|---|---|
| `~/.youtube-script/app.log` | Application log |
| `~/.youtube-script/gui_settings.json` | GUI preferences (version 7 schema) |
| `~/.youtube-script/download_history.json` | Download history |

Settings are versioned (`"version": 7`). `normalize_gui_settings` in `settings.py` migrates and clamps every field on load, so it is always safe to read stale or partial JSON.

## Testing patterns

- GUI tests use `gui.TranscriptApp.__new__(gui.TranscriptApp)` to instantiate without a Tk root, then monkey-patch instance methods with lambdas. Tests that need a real Tk root guard with `pytest.skip("Tk unavailable …")`.
- Network calls and subprocess calls are always monkeypatched — no real network or ffmpeg/yt-dlp needed.
- The `base` module re-exports everything, so most tests import from `youtube_script_app.base`.
