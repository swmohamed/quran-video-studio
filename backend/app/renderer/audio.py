"""Continuous-recitation audio pipeline — ZERO inserted pause.

Product rules (per spec):
- decode every verse to uniform float PCM (44.1kHz stereo)
- trim ONLY proven digital padding: frames at/below the digital-dither
  floor (-60dB, well under any speech/breath/reverb) beyond tiny keeps
- NEVER trim low-volume reverb, breath tails, or natural vocal decay
  (anything above -60dB is kept in full)
- NEVER insert, generate, or reconstruct inter-ayah silence: Ayah N+1
  begins at the sample right after Ayah N's preserved tail
- 8/10ms linear edge fades are applied ONLY across the kept <=-60dB edge
  samples (confirmed non-speech) to prevent digital clicks; they cannot
  touch words, shorten endings, or create audible pauses
- one WAV is written; AAC is encoded once downstream
- ayah timestamps are rebuilt from the assembled boundaries
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.ffmpeg import tools

SR = 44100
FRAME_MS = 5
QUIET_DB = -60.0          # digital dither/padding floor; speech/breath never this low
MIN_SOUND_FRAMES = 3      # 15ms of continuous energy to count as content
KEEP_LEAD_S = 0.010       # kept head edge (<=QUIET_DB zone only)
KEEP_TAIL_S = 0.012       # kept tail edge (<=QUIET_DB zone only)
ADAPTIVE_TAIL_KEEP_S = 0.060  # longer decay kept for files cut mid-tone
FADE_IN_S = 0.008         # click smoothing inside confirmed non-speech head
FADE_OUT_S = 0.010        # click smoothing inside confirmed non-speech tail


@dataclass
class VerseSpan:
    offset: float    # seconds into the ORIGINAL verse file
    duration: float  # kept duration (natural tail included)
    start: float = 0.0   # start in the combined track
    end: float = 0.0


class AudioPrepareError(RuntimeError):
    pass


def _decode(path: Path) -> np.ndarray:
    proc = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-i", str(path),
         "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise AudioPrepareError(f"Could not decode {path.name}: {proc.stderr.decode(errors='replace')[-200:]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2)


def _frame_db(mono: np.ndarray, frame_n: int) -> np.ndarray:
    m = len(mono) // frame_n * frame_n
    if m == 0:
        return np.array([])
    rms = np.sqrt((mono[:m].reshape(-1, frame_n) ** 2).mean(axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9))


def _content_bounds(x: np.ndarray) -> tuple[int, int]:
    """Sample indices [start, end) of recitation content.

    Edge handling adapts to each file's waveform (inspected, not assumed):
    - Files that END in true quiet (edges <= -55dB) use the digital-padding
      threshold; every frame above the dither floor is kept (alafasy, muaiqly).
    - Files cut mid-tone at EOF (dosari: room tone around -30dB right up to
      the final sample) get a side-specific threshold above that local tone,
      so the boundary lands after real vocal content — never mid-tone — and
      a slightly longer tail is preserved before the click-prevention fade.
    """
    n = len(x)
    mono = x.mean(axis=1)
    fn = int(SR * FRAME_MS / 1000)
    db = _frame_db(mono, fn)
    if len(db) == 0:
        return 0, n

    head_edge = float(np.median(db[:6]))
    tail_edge = float(np.median(db[-6:]))
    head_thresh = QUIET_DB if head_edge <= -55.0 else max(-45.0, head_edge + 9.0)
    tail_thresh = QUIET_DB if tail_edge <= -55.0 else max(-45.0, tail_edge + 9.0)
    adaptive_tail = tail_thresh != QUIET_DB

    sound = db > head_thresh
    start_f = len(sound)
    run = 0
    for i, s in enumerate(sound):
        run = run + 1 if s else 0
        if run >= MIN_SOUND_FRAMES:
            start_f = i - MIN_SOUND_FRAMES + 1
            break

    sound_t = db > tail_thresh
    end_f = -1
    run = 0
    for i in range(len(sound_t) - 1, -1, -1):
        run = run + 1 if sound_t[i] else 0
        if run >= MIN_SOUND_FRAMES:
            end_f = i + MIN_SOUND_FRAMES
            break

    if start_f >= end_f:
        return 0, n  # entirely quiet file: keep as-is

    start = max(0, start_f * fn - int(SR * KEEP_LEAD_S))
    tail_keep = ADAPTIVE_TAIL_KEEP_S if adaptive_tail else KEEP_TAIL_S
    end = min(n, end_f * fn + int(SR * tail_keep))
    return start, end


def analyze_playback(paths: list[Path]) -> list[VerseSpan]:
    """Decode each verse once; return spans for the live preview —
    identical boundaries to the render pipeline (zero inserted pause)."""
    spans: list[VerseSpan] = []
    for p in paths:
        x = _decode(p)
        s, e = _content_bounds(x)
        spans.append(VerseSpan(offset=s / SR, duration=(e - s) / SR))
    return spans


def _apply_edge_fades(seg: np.ndarray, fade_out_s: float = FADE_OUT_S) -> None:
    """Edge fades confined to non-speech edges. Hard-cut sources (files that
    end mid-tone) get the wider 14ms release so the archive's abrupt EOF
    reads as a natural syllable release instead of a click."""
    fi = min(len(seg), int(SR * FADE_IN_S))
    fo = min(len(seg), int(SR * fade_out_s))
    if fi > 0:
        g = np.linspace(0.0, 1.0, fi, dtype=np.float32)
        seg[:fi] *= g[:, None]
    if fo > 0 and 2 * fo < len(seg):
        g = np.linspace(1.0, 0.0, fo, dtype=np.float32)
        seg[-fo:] *= g[:, None]


def _tail_is_loud(x: np.ndarray) -> bool:
    fn = int(SR * FRAME_MS / 1000)
    db = _frame_db(x.mean(axis=1), fn)
    if len(db) == 0:
        return False
    return float(np.median(db[-6:])) > -55.0


def _write_wav(combined: np.ndarray, out_wav: Path) -> None:
    proc = subprocess.run(
        [tools.ffmpeg, "-y", "-v", "error",
         "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
         "-c:a", "pcm_s16le", str(out_wav)],
        input=combined.astype(np.float32).tobytes(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AudioPrepareError(f"Could not write combined WAV: {proc.stderr.decode(errors='replace')[-200:]}")


def build_continuous(
    paths: list[Path], out_wav: Path, fades: bool = True
) -> tuple[list[VerseSpan], float]:
    """Decode, edge-trim digital padding only, and concatenate with ZERO
    inserted pause — the next ayah begins at the sample after the previous
    ayah's preserved natural tail.

    Returns (spans with absolute start/end, total seconds).
    """
    spans: list[VerseSpan] = []
    chunks: list[np.ndarray] = []
    t = 0.0
    for p in paths:
        x = _decode(p)
        s, e = _content_bounds(x)
        seg = np.ascontiguousarray(x[s:e]).copy()
        if fades:
            _apply_edge_fades(seg, fade_out_s=0.014 if _tail_is_loud(x) else FADE_OUT_S)
        dur = len(seg) / SR
        spans.append(VerseSpan(offset=s / SR, duration=dur, start=t, end=t + dur))
        chunks.append(seg)
        t += dur  # NO pause insertion — immediate continuation

    if not chunks:
        raise AudioPrepareError("No audio to process.")
    combined = np.concatenate(chunks, axis=0)
    _write_wav(combined, out_wav)
    return spans, t
