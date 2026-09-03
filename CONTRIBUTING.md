# Contributing to Quran Video Studio

Thanks for your interest in contributing. This guide covers the practical
parts: setup, workflow, and the extra care this project requires because it
handles Quranic content.

## Setup

Follow the [README quick start](README.md#quick-start-windows):

```
setup.bat    (first run: installs dependencies, downloads Quran text)
start.bat    (launches backend + frontend)
```

For development, run the servers manually so you get live reload:

```bash
# backend (from backend/)
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# frontend (from frontend/)
npm install
npm run dev
```

Verify FFmpeg + ffprobe are on PATH (`ffmpeg -version`) before working on
anything that renders.

## Development workflow

1. Fork, then create a branch for your change.
2. Make the change — keep it focused; one logical change per PR.
3. Run the relevant tests (see below) and try the change in the app yourself.
4. Open a pull request using the PR template.

## Reporting bugs

Open an issue with the **Bug report** template. Always include: OS, the exact
commit you ran, reproduction steps, and what you expected vs. what happened.
For anything involving rendering, audio, or export, include your FFmpeg
version and backend logs.

Never paste API keys (e.g. `data/stock_keys.json` contents) into an issue.

## Proposing features

Open an issue with the **Feature request** template first, before writing
code. Describe the problem you're solving, not only the solution — there is
often a simpler way that fits the existing pipeline.

Keep in mind the project's non-goals: it is a local, single-user studio. It
does not need accounts, cloud sync, or multi-tenant anything.

## Testing requirements

The backend ships with real end-to-end checks (run from `backend/` with the
project venv):

```bash
python tests/e2e_render.py <reciter> <from_ayah> <to_ayah>   # real MP4 render + ffprobe verification
python tests/verify_continuous.py <reciter>                  # audio seams + video boundary frames
python tests/profile_reciters.py [surah]                     # PCM boundary standard for reciters
```

- **Any change to rendering, audio, or the timeline** → run
  `e2e_render.py` and `verify_continuous.py` on at least one reciter, and
  watch the produced MP4 yourself before submitting.
- **Any change to text rendering** → confirm the exported MP4 matches the
  browser preview (fidelity matters; see README "How rendering works").
- Frontend changes must type-check: `cd frontend && npx tsc -b`.

## Code quality

- Backend: Python 3.11, FastAPI. Keep data-source knowledge inside
  `services/` (`quran.py`, `reciters.py`, `surah_audio.py`) — everything else
  consumes it. Don't scatter HTTP calls for Quran data/audio elsewhere.
- Frontend: TypeScript strict mode, Tailwind. No new runtime dependencies
  without justification.
- Don't modify generated caches or runtime folders (`output/`, `temp/`,
  `audio/`, `backgrounds/`, `uploads/` are git-ignored).
- Never commit API keys or personal data. `data/stock_keys.json` stays local
  (see `data/stock_keys.example.json`).

## Quran data & audio integrity (important)

This project renders the words of the Quran. Treat that responsibility
seriously:

**Do not:**

- fabricate or "fix" Quran text by typing it manually — text comes only from
  the verified data pipeline (`data/verses/` built by `fetch_quran_data.py`)
- modify Quran text casually (e.g. "improving" spelling, removing or editing
  diacritics)
- generate recitations with AI or replace a reciter's audio with synthetic audio
- silently replace translations — translations must come from their known
  source edition
- mix recitation audio with timestamps from a different recording, or guess /
  stretch timestamps to force alignment

**Do:**

- use verifiable sources for any change affecting Quran text, translations,
  recitation audio, or timing data, and say which source you used
- test such changes carefully: multi-ayah render + `verify_continuous.py`,
  and verify recitation/timing changes against the PCM boundary standard
  (`tests/profile_reciters.py`)

Changes in this area that cannot demonstrate their source and pass the tests
will not be merged.
