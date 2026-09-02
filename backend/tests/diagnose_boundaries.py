"""Diagnose ayah-boundary audio quality in the current pipeline.

1. Raw verse files: how much digital silence / encoder padding at head/tail?
2. Rendered output: exact silence span at each ayah junction + click energy.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.core.ffmpeg import tools  # noqa: E402

ROOT = Path("..").resolve()


def decode(path: Path, sr=44100) -> np.ndarray:
    proc = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
        capture_output=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def frame_db(x: np.ndarray, sr: int, ms=10) -> np.ndarray:
    n = int(sr * ms / 1000)
    m = len(x) // n * n
    rms = np.sqrt((x[:m].reshape(-1, n) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    return db


def silence_span(x: np.ndarray, sr: int, center_s: float, win=0.6, thresh_db=-50.0):
    """Longest run of frames below thresh crossing `center_s`."""
    db = frame_db(x, sr)
    ft = 0.01
    c = int(center_s / ft)
    half = int(win / ft / 2)
    lo, hi = max(0, c - half), min(len(db), c + half)
    quiet = db[lo:hi] < thresh_db
    best = (0, 0)
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            span = j - i
            if lo + i <= c < lo + j and span > best[1] - best[0]:
                best = (lo + i, lo + j)
            i = j
        else:
            i += 1
    return (best[1] - best[0]) * ft  # seconds


print("=" * 70)
print("1) RAW VERSE FILES (alafasy) — head/tail digital silence")
print("=" * 70)
for ayah in [6, 7, 8, 9, 10]:
    p = ROOT / "audio/reciters/alafasy" / f"089{ayah:03d}.mp3"
    x = decode(p)
    db = frame_db(x, 44100)
    lead = 0
    while lead < len(db) and db[lead] < -60:
        lead += 1
    tail = 0
    while tail < len(db) and db[len(db) - 1 - tail] < -60:
        tail += 1
    dur = len(x) / 44100
    print(f"  89:{ayah}  dur={dur:5.2f}s  digital-silence head={lead*10}ms tail={tail*10}ms  "
          f"head_db[0:3]={[round(d,0) for d in db[:3]]}")

print()
print("=" * 70)
print("2) CURRENT RENDERED OUTPUT — junction analysis")
print("=" * 70)
out = sorted((ROOT / "output").glob("al-fajr-89-6-12-alafasy-*.mp4"))[-1]
x = decode(out)
sr = 44100
starts = [0.0, 5.68, 9.813, 16.45, 23.575, 28.768, 34.045]
durs = [5.68, 4.133, 6.637, 7.125, 5.193, 5.277, 5.185]

peak_jump = float(np.max(np.abs(np.diff(x))))
print(f"  global max sample-to-sample jump: {peak_jump:.4f}")
for k in range(1, len(starts)):
    t = starts[k]
    gap = silence_span(x, sr, t)
    i0 = int((t - 0.05) * sr)
    i1 = int((t + 0.05) * sr)
    jump = float(np.max(np.abs(np.diff(x[i0:i1]))))
    print(f"  junction before ayah {[6,7,8,9,10,11,12][k]} @ {t:7.3f}s: "
          f"silence-span={gap*1000:5.0f}ms  boundary-jump={jump:.4f} ({'CLICK?' if jump > 0.3 else 'clean'})")

# natural pause reference: measure longest low-level (breath) pauses inside each ayah
print()
print("  reference — quietest internal pause per ayah (breath level, -35dB):")
for k in range(len(starts)):
    seg = x[int(starts[k] * sr):int((starts[k] + durs[k]) * sr)]
    db = frame_db(seg, sr)
    best = 0
    i = 0
    while i < len(db):
        if db[i] < -35:
            j = i
            while j < len(db) and db[j] < -35:
                j += 1
            best = max(best, j - i)
            i = j
        else:
            i += 1
    print(f"    ayah {[6,7,8,9,10,11,12][k]}: longest <-35dB pause inside = {best*10}ms")
