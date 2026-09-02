"""DIAGNOSIS ONLY — compare ORIGINAL full-surah audio vs FINAL MP4 at each Ayah boundary.

Measures per boundary (Al-Fajr 1-7, Alafasy, surah mode):
  - source pause (quiet span at -40dB) around the boundary in the original recording
  - final pause (same measurement) in the rendered MP4 audio
  - speech offset/onset positions in both  -> pause composition + timing shift
  - sample discontinuities (clicks) in both
  - silence added/removed (pause delta + energy in the pause window)
  - global timing shift via cross-correlation of speech after each boundary
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.core.ffmpeg import tools  # noqa: E402

ROOT = Path("..").resolve()
SR = 44100
FT = 0.01  # 10ms frames
SOURCE = ROOT / "audio/surah/alafasy/089.mp3"
FINAL = sorted((ROOT / "output").glob("al-fajr-89-1-7-alafasy-*.mp4"))[-1]
BOUNDS = [1.440, 3.870, 6.270, 9.090, 13.430, 19.440]  # QDC official (ms->s)
NAMES = ["1->2", "2->3", "3->4", "4->5", "5->6", "6->7"]


def decode(path: Path) -> np.ndarray:
    proc = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def frame_db(x: np.ndarray) -> np.ndarray:
    n = int(SR * FT)
    m = len(x) // n * n
    rms = np.sqrt((x[:m].reshape(-1, n) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def analyze(x: np.ndarray, db: np.ndarray, t: float, quiet_db=-40.0, speech_db=-35.0):
    f0 = int(t / FT)
    half = int(2.5 / FT)
    lo, hi = max(0, f0 - half), min(len(db), f0 + half)
    seg = db[lo:hi]
    quiet = seg < quiet_db
    # quiet span crossing the boundary frame
    ci = f0 - lo
    if not quiet[ci]:
        span = 0.0
    else:
        i = ci
        while i > 0 and quiet[i - 1]:
            i -= 1
        j = ci
        while j < len(quiet) - 1 and quiet[j + 1]:
            j += 1
        span = (j - i + 1) * FT
    # speech offset/onset
    sp = seg > speech_db
    off = 0
    for i in range(ci, -1, -1):
        if sp[i]:
            off = (lo + i) * FT
            break
    onset = 0
    for i in range(ci, len(seg)):
        if sp[i]:
            onset = (lo + i) * FT
            break
    # click: max sample jump +-30ms around boundary
    s0, s1 = int((t - 0.03) * SR), int((t + 0.03) * SR)
    jump = float(np.max(np.abs(np.diff(x[s0:s1])))) if s1 - s0 > 2 else 0.0
    # energy inside the measured quiet span window (is there added noise/silence?)
    return span, off, onset, jump


def xcorr_shift(a: np.ndarray, b: np.ndarray) -> int:
    """Lag (samples) of b relative to a, +/- 4000 samples."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    a = a - a.mean()
    b = b - b.mean()
    lags = range(-4000, 4001, 20)
    best, best_r = 0, -1e18
    for L in lags:
        if L >= 0:
            r = float(np.dot(a[L:], b[: n - L]))
        else:
            r = float(np.dot(a[: n + L], b[-L:]))
        if r > best_r:
            best_r, best = r, L
    return best


xs = decode(SOURCE)
xf = decode(FINAL)
dbs = frame_db(xs)
dbf = frame_db(xf)
print(f"source: {SOURCE.name}  dur={len(xs)/SR:.3f}s")
print(f"final:  {FINAL.name}  dur={len(xf)/SR:.3f}s")
print(f"boundaries (QDC official): {BOUNDS}")
print()
print(f"{'seam':6s} {'src-pause':>9s} {'fin-pause':>9s} {'delta':>7s} {'src-off':>8s} {'fin-off':>8s} "
      f"{'shift-off':>9s} {'src-on':>8s} {'fin-on':>8s} {'shift-on':>9s} {'src-jump':>8s} {'fin-jump':>8s}")

src_pauses, fin_pauses = [], []
for t, name in zip(BOUNDS, NAMES):
    s_span, s_off, s_on, s_jump = analyze(xs, dbs, t)
    f_span, f_off, f_on, f_jump = analyze(xf, dbf, t)
    # timing shift: cross-correlate 800ms of speech just after onset
    a0 = int((t + 0.15) * SR)
    w = int(0.8 * SR)
    shift = xcorr_shift(xs[a0:a0 + w], xf[a0:a0 + w])
    src_pauses.append(s_span)
    fin_pauses.append(f_span)
    print(f"{name:6s} {s_span*1000:8.0f}ms {f_span*1000:8.0f}ms {(f_span-s_span)*1000:+6.0f}ms "
          f"{s_off:8.3f} {f_off:8.3f} {(f_off-s_off)*1000:+8.1f} "
          f"{s_on:8.3f} {f_on:8.3f} {(f_on-s_on)*1000:+8.1f} {s_jump:8.4f} {f_jump:8.4f}  xcorr={shift:+d}smp")

print()
print(f"pause deltas (final - source): {[round((f-s)*1000) for s, f in zip(src_pauses, fin_pauses)]} ms")
print(f"mean delta: {np.mean([(f-s)*1000 for s, f in zip(src_pauses, fin_pauses)]):+.1f} ms")
