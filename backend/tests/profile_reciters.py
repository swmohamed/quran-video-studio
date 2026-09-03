"""Measure the 'muaiqly/dosari standard' for every surah-mode reciter.

Per reciter (default surah 89, ayahs 1->8 junctions):
  - pause: PCM quiet span (<-42dB, 10ms frames) around each boundary
  - lead  : time from boundary to the next actual speech onset (text-sync)
Reference (user-approved): muaiqly QUL65 / dosari QDC97.

Verdicts:
  OK (matches standard)      — flowing recitation, tight sync
  OK (natural waqf)          — tight sync (speech resumes right at the
                               boundary), longer inter-ayah pauses are the
                               reciter's own style preserved from the single
                               continuous recording (e.g. Abdul Basit murattal)
  NEEDS BETTER SOURCE        — speech lags the boundary (sync defect) or
                               dead air AFTER the boundary timestamp

Usage: python tests/profile_reciters.py [surah_number]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.core.config import RECITERS_DIR, ROOT  # noqa: E402
from app.core.ffmpeg import tools  # noqa: E402
from app.services import surah_audio  # noqa: E402

SURAH = int(sys.argv[1]) if len(sys.argv) > 1 else 89
N_FROM, N_TO = 1, 7
SR, FT = 44100, 0.01
reciters = json.loads((ROOT / "data" / "reciters.json").read_text(encoding="utf-8"))["reciters"]


def decode(p: Path) -> np.ndarray:
    pr = subprocess.run([tools.ffmpeg, "-v", "error", "-i", str(p),
                         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True)
    return np.frombuffer(pr.stdout, dtype=np.float32)


def frame_db(x):
    n = int(SR * FT)
    m = len(x) // n * n
    rms = np.sqrt((x[:m].reshape(-1, n) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


print(f"{'reciter':11s} {'source':16s} {'median-pause':>12s} {'max-pause':>9s} "
      f"{'median-lead':>11s} {'max-lead':>8s}  verdict")
for rec in reciters:
    rid = rec["id"]
    cfg = surah_audio.reciter_provider(rec)
    if not cfg:
        print(f"{rid:11s} {'verse-fallback':16s}  (not surah mode)")
        continue
    provider, pid = cfg
    path = surah_audio.surah_path(rid, SURAH)
    if not path.exists():
        print(f"{rid:11s} {provider}{pid:<13d}  (audio not cached yet)")
        continue
    info = surah_audio.fetch_timings(provider, pid, SURAH)
    x = decode(path)
    db = frame_db(x)
    use_word = rec.get("surahBoundary") == "word"
    tm = {t["ayah"]: t for t in info["timings"]}

    def start_of(t):
        return (t.get("word_from_ms") if use_word and "word_from_ms" in t else t["from_ms"]) / 1000.0

    pauses, leads = [], []
    for a in range(N_FROM + 1, N_TO + 1):  # boundaries at start of ayahs 2..7
        b = start_of(tm[a])
        bf = int(b / FT)
        quiet = db < -42
        if not quiet[bf]:
            span = 0.0
        else:
            i = j = bf
            while i > 0 and quiet[i - 1]:
                i -= 1
            while j < len(quiet) - 1 and quiet[j + 1]:
                j += 1
            span = (j - i + 1) * FT
        # lead: first speech frame after boundary
        lead = 0.0
        for k in range(bf, min(len(db), bf + int(1.5 / FT))):
            if db[k] > -32:
                lead = k * FT - b
                break
        pauses.append(span)
        leads.append(lead)
    med_p, max_p = np.median(pauses), max(pauses)
    med_l, max_l = np.median(leads), max(leads)
    # standard: flowing pauses (<=650ms max) and tight text sync (<=350ms lead)
    sync_ok = med_l <= 0.35 and max_l <= 0.5
    flowing = max_p <= 0.65
    if sync_ok and flowing:
        verdict = "OK  (matches standard)"
    elif sync_ok:
        # pauses sit BEFORE the boundary (trailing waqf of the previous ayah)
        # and speech resumes right at it — the reciter's own style, preserved
        # from the single continuous recording.
        verdict = "OK  (natural waqf — tight sync, stylistic pauses)"
    else:
        verdict = "NEEDS BETTER SOURCE"
    print(f"{rid:11s} {provider + str(pid):16s} {med_p*1000:10.0f}ms {max_p*1000:6.0f}ms "
          f"{med_l*1000:9.0f}ms {max_l*1000:5.0f}ms  {verdict}")
