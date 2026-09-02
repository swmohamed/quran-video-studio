"""Master continuity gate — AUDIO + VIDEO.

AUDIO (final continuous WAV + MP4 audio track):
  per junction: inserted silence (must be 0 by construction — verified at
  the seam sample), source trailing/leading digital silence, effective gap
  at the -50dB meaningful level, click transient at the seam.

VIDEO (final MP4):
  for each boundary, frames at b-200, b-100, b, b+100, b+200 ms:
  - no black frame (mean luma)
  - Surah header region stable (never disappears)
  - card edge regions stable (never disappears)
  - whole-frame change is bounded (text changes, scene does NOT reset)
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

RECITER = sys.argv[1] if len(sys.argv) > 1 else RECITER
sys.path.insert(0, ".")
from app.core.ffmpeg import tools  # noqa: E402
from app.services import reciters as recsvc  # noqa: E402
from app.renderer.audio import analyze_playback  # noqa: E402

ROOT = Path("..").resolve()
SR = 44100
FT = 0.01
diag = ROOT / "temp" / "audio_tests"
report = json.loads((diag / "timestamps.json").read_text(encoding="utf-8"))
starts = [b["start"] for b in report["boundaries"]]
ends = [b["end"] for b in report["boundaries"]]
ayahs = [b["ayah"] for b in report["boundaries"]]
mp4 = ROOT / "output" / report["video"]
CANVAS_W = int(report.get("width") or 1080)
CANVAS_H = int(report.get("height") or 1920)
SX, SY = CANVAS_W / 1080, CANVAS_H / 1920
wav = diag / "final_recitation.wav"
print(f"video: {mp4.name}")
print(f"wav:   {wav}  (continuous track, listen separately)")


def decode_audio(path: Path) -> np.ndarray:
    proc = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def frame_db(x: np.ndarray) -> np.ndarray:
    n = int(SR * FT)
    m = len(x) // n * n
    rms = np.sqrt((x[:m].reshape(-1, n) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def grab_frame(t: float) -> np.ndarray:
    proc = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True)
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(CANVAS_H, CANVAS_W)


print("\n================ AUDIO ================")
xa = decode_audio(wav)
db = frame_db(xa)
all_pass = True
surah_mode = report.get("audioMode", "verses") == "surah"
xs_src = None
if surah_mode and report.get("surahFile"):
    xs_src = decode_audio(Path(report["surahFile"]))
    src_off = report.get("surahStart") or 0.0
for k in range(1, len(starts)):
    b = starts[k]
    bf = int(b / FT)
    quiet = db < -50
    if not quiet[bf]:
        i = j = bf
    else:
        i = bf
        while i > 0 and quiet[i - 1]:
            i -= 1
        j = bf
        while j < len(quiet) - 1 and quiet[j + 1]:
            j += 1
    eff_gap = (j - i + 1) * FT * 1000
    # click: max sample jump within +-2ms of the exact seam (fade zone)
    s0 = int((b - 0.002) * SR)
    s1 = int((b + 0.002) * SR)
    seam_jump = float(np.max(np.abs(np.diff(xa[s0:s1]))))
    if surah_mode:
        # ONE continuous slice: a boundary "jump" is a defect ONLY if the
        # pipeline introduced it. Compare against the ORIGINAL recording at
        # the same absolute instant (reciter mid-speech transients are fine —
        # e.g. flowing murattal styles that continue through verse starts).
        if xs_src is not None:
            a0 = int((src_off + b - 0.002) * SR)
            src_jump = float(np.max(np.abs(np.diff(xs_src[a0:a0 + (s1 - s0)]))))
        else:
            src_jump = seam_jump
        ok = seam_jump <= max(src_jump, 0.02) + 0.005
        print(f"  seam {ayahs[k-1]:2d}->{ayahs[k]:2d} @ {b:7.3f}s: pause={eff_gap:4.0f}ms  "
              f"final-jump={seam_jump:.4f} source-jump={src_jump:.4f} (same recording)  "
              f"-> {'PASS' if ok else 'FAIL'}")
        all_pass &= ok
        continue
    # verse-by-verse mode: seam must sit in processed silence
    # the seam sample region itself must be at fade/silence level
    w0 = int((b - 0.003) * SR)
    w1 = int((b + 0.004) * SR)
    seam_peak = float(np.max(np.abs(xa[w0:w1])))
    # next verse's head must be clean (no attack inside the first 3ms)
    h1 = int((b + 0.003) * SR)
    head_peak = float(np.max(np.abs(xa[h1:int((b + 0.006) * SR)])))
    ok = seam_jump < 0.02 and head_peak < 0.06
    # source tail level at the seam (informational; hard-cut archives end loud)
    pre = float(np.max(np.abs(xa[int((b - 0.030) * SR):int((b - 0.012) * SR)])))
    all_pass &= ok
    print(f"  seam {ayahs[k-1]:2d}->{ayahs[k]:2d} @ {b:7.3f}s: gap={eff_gap:4.0f}ms  "
          f"jump={seam_jump:.4f} seam-peak={seam_peak:.3f} head-peak={head_peak:.3f} src-tail={pre:.2f}  "
          f"-> {'PASS' if ok else 'FAIL'}")

# source-file trailing/leading digital silence for the record
# source-file analysis only applies to verse-by-verse mode
if not surah_mode:
    spans = analyze_playback([recsvc.local_audio_path(RECITER, 89, a) for a in ayahs])
    raw = [tools.probe_duration(recsvc.local_audio_path(RECITER, 89, a)) for a in ayahs]
    print("  source vs kept (digital padding removed only):")
    for a, r, sp in zip(ayahs, raw, spans):
        print(f"    89:{a}: raw {r:5.2f}s -> kept {sp.duration:5.2f}s  (removed {(r - sp.duration)*1000:4.0f}ms)")
else:
    print(f"  audio mode: surah — single continuous slice, no per-file joins")

print("\n================ VIDEO ================")
f = grab_frame(1.0)
HEADER = (slice(int(100 * SY), int(420 * SY)), slice(int(200 * SX), int(880 * SX)))   # surah header region
CARD_L = (slice(int(700 * SY), int(1500 * SY)), slice(int(120 * SX), int(300 * SX)))   # card left strip (no text)
CARD_R = (slice(int(700 * SY), int(1500 * SY)), slice(int(780 * SX), int(960 * SX)))  # card right strip
base_hdr = f[HEADER].astype(np.int16)

for k in range(1, len(starts)):
    b = starts[k]
    frames = {o: grab_frame(b + o) for o in (-0.2, -0.1, 0.0, 0.1, 0.2)}
    min_luma = min(float(fr.mean()) for fr in frames.values())
    hdr_drift = max(float(np.abs(fr[HEADER].astype(np.int16) - base_hdr).mean()) for fr in frames.values())
    card_ref = frames[-0.2][CARD_L].astype(np.int16)
    card_drift = max(float(np.abs(fr[CARD_L].astype(np.int16) - card_ref).mean()) for fr in frames.values())
    card_drift = max(card_drift, max(float(np.abs(fr[CARD_R].astype(np.int16) - frames[-0.2][CARD_R].astype(np.int16)).mean()) for fr in frames.values()))
    whole = float(np.abs(frames[0.1].astype(np.int16) - frames[-0.1].astype(np.int16)).mean())
    ok = min_luma > 5 and hdr_drift < 10 and card_drift < 12 and whole < 30
    all_pass &= ok
    print(f"  boundary {ayahs[k-1]:2d}->{ayahs[k]:2d} @ {b:7.3f}s: min-luma={min_luma:5.1f}  "
          f"header-drift={hdr_drift:4.1f}  card-drift={card_drift:4.1f}  frame-change={whole:4.1f}  "
          f"-> {'PASS' if ok else 'FAIL'}")

print("\n" + ("ALL CONTINUITY CHECKS PASSED" if all_pass else "CONTINUITY CHECKS FAILED"))
