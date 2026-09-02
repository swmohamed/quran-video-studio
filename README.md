# Quran Video Studio

A local web application for creating vertical (9:16) Quran recitation videos —
Quranic Arabic text with a traditional verse-end marker, translation, animated
background, and verse-synced recitation — ready for TikTok, Instagram Reels,
and YouTube Shorts.

Runs entirely on your machine. No accounts, no watermarks.

![stack](https://img.shields.io/badge/React%2019-Vite%206-TS-blue) ![backend](https://img.shields.io/badge/FastAPI-Python%203.11-009688) ![render](https://img.shields.io/badge/FFmpeg-H.264%20%2B%20AAC-orange)

## Features

- **Verse-synced rendering** — the timeline is built from real measured audio
  durations (ffprobe), never from guessed timestamps.
- **Continuous full-surah audio mode** — one continuous recitation slice
  (EveryAyah, QUL, QDC) with verified verse boundaries, zero gaps between
  ayahs, for supported reciters. Falls back to verse-by-verse audio otherwise.
- **Correct Arabic typography** — HarfBuzz + FreeType shaping (joining,
  ligatures, diacritic positioning), Amiri / Noto Naskh / Noto Sans fonts.
- **Quranic verse-end marker** — an ornamental rosette with the ayah number
  in Arabic-Indic digits, glued to the end of the verse in proper RTL flow,
  identical in preview and export.
- **Online background library** — search and import stock videos/photos from
  Pexels and Pixabay (your own API keys), or upload your own media.
- **Platform presets** — safe-zone overlays (preview only) for TikTok,
  Reels, Shorts, and WhatsApp status.
- **Resolution & quality tiers** — 1080×1920, 4K, or a light 540×960 render;
  Small / Standard / Best encoding presets.
- **Light & All-in-One exports** — optionally render a second lightweight
  copy for WhatsApp, and/or a single MP4 containing both HD and Light video
  tracks.
- **True preview fidelity** — supersampled text rendering so the exported MP4
  matches the browser preview (centered cover-crop, color conversion, bt709).

## Quick start (Windows)

```
setup.bat    (first run: checks Python/Node/FFmpeg, installs dependencies, downloads Quran text)
start.bat    (launches backend + frontend, opens http://localhost:5173)
```

- App: http://localhost:5173
- Backend API: http://localhost:8000 (interactive docs at `/docs`)

### Stock background keys (optional)

To use the online background library, copy the example file and fill in your
free API keys:

```
copy data\stock_keys.example.json data\stock_keys.json
```

- Pexels: https://www.pexels.com/api/ (free)
- Pixabay: https://pixabay.com/api/docs/ (free)

`data/stock_keys.json` is git-ignored — your keys never leave your machine.

### Manual setup (non-Windows)

```bash
python -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt   # or bin/pip on Linux/macOS
backend/.venv/Scripts/python backend/scripts/fetch_quran_data.py
cd frontend && npm install && npm run dev
# backend: backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

## Workflow

1. Pick a Surah and ayah range (up to 30 ayahs)
2. Choose a reciter and audio mode (continuous full-surah or verse-by-verse)
3. Choose a translation (or none)
4. Pick a background — bundled loop, stock library search, or your own file
5. Adjust text card, typography, and background to taste; the preview updates live
6. **Generate Video** — real per-stage progress, then play or download the MP4

## How rendering works (and why it is accurate)

- Verse audio is fetched per ayah (`SSSAAA.mp3`, e.g. `089006.mp3`) — or, in
  continuous mode, one full-surah recording is sliced at verified boundaries.
- Every ayah's audio is measured with **ffprobe**; the timeline is built from
  those real durations — timestamps are never guessed.
- Audio is concatenated with zero gaps; the recitation length defines the
  video length.
- Arabic text is shaped by a real HarfBuzz + FreeType pipeline and composited
  as transparent PNG cards, supersampled 2× and downscaled with lanczos for
  crisp edges at any output size.
- Backgrounds cover-crop (never stretch) to the target resolution, loop if
  shorter than the recitation, and trim if longer. Brightness / contrast /
  saturation / blur / color overlays are FFmpeg filters.
- Output: H.264 + AAC, yuv420p, 30 fps, `+faststart`, verified with ffprobe
  (streams, resolution, codec, duration) before the result is returned.

## Project structure

```
quran-video-studio/
├── frontend/          React + TypeScript + Vite + Tailwind (editor UI, live preview)
├── backend/           FastAPI app (api/, core/, models/, services/, renderer/)
│   ├── scripts/       fetch_quran_data.py (Quran text cache builder)
│   └── tests/         end-to-end render + audio continuity checks
├── data/              surahs.json, verses/, reciters, presets
├── fonts/             Amiri, Noto Naskh Arabic, Noto Sans Arabic, Inter
├── uploads/           user-uploaded backgrounds        (runtime)
├── backgrounds/       stock library download cache      (runtime)
├── audio/             recitation cache                  (runtime)
├── temp/              per-job render scratch            (runtime)
├── output/            generated MP4s                    (runtime)
├── setup.bat / start.bat
```

Runtime folders are created automatically and are git-ignored.

## Data sources & attribution

- **Quran text (Uthmani):** Tanzil.net text served via api.alquran.cloud
  (`quran-uthmani` edition). Cached locally under `data/verses/`.
- **Translation:** Saheeh International (via api.alquran.cloud, `en.sahih`).
- **Recitation audio:** everyayah.com verse-by-verse archives; full-surah
  recordings via QUL (Quran Unified Library) and QDC timings where verified.
  Downloaded on first use, then cached locally.
- **Stock media:** official Pexels / Pixabay APIs with user-provided keys.
- **Fonts:** Amiri (SIL OFL), Noto Naskh/Sans Arabic (SIL OFL), Inter (SIL OFL).

The data layer is replaceable: `backend/app/services/quran.py`,
`reciters.py`, and `surah_audio.py` are the only modules that know where
text/audio come from.

## Requirements

- Python 3.11+ (backend), Node.js 20+ (frontend build)
- FFmpeg + ffprobe on PATH (`winget install Gyan.FFmpeg`)
- Internet access for the first data/audio fetch; editing and cached ayahs
  work offline

## Troubleshooting

- **"FFmpeg was not found"** — install it (`winget install Gyan.FFmpeg`),
  reopen the terminal, restart with `start.bat`. The backend also honors
  `QVS_FFMPEG` / `QVS_FFPROBE` environment variables pointing at the
  executables.
- **Render fails at audio stage** — the reciter file for an ayah could not be
  downloaded; check internet access. Already-cached ayahs keep working.
- **Backend not reachable** — the backend window shows errors; it must stay
  open.
