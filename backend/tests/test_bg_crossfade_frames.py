"""Compose 3 trimmed clips with xfade and check the join is a blend, not a cut."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.core.ffmpeg import tools
from app.models.schemas import BackgroundClip, BackgroundSettings
from app.renderer import bg_timeline as bgtl
from app.services.backgrounds import resolve_background

all_pass = True


def check(name: str, ok: bool, extra: str = "") -> None:
    global all_pass
    all_pass &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def mean_luma(path: Path) -> float:
    import subprocess

    raw = subprocess.run(
        [
            tools.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-vf",
            "scale=64:64,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        timeout=60,
    )
    if raw.returncode != 0 or not raw.stdout:
        raise RuntimeError(f"luma extract failed\n{(raw.stderr or b'').decode('utf-8', 'replace')[-400:]}")
    return sum(raw.stdout) / len(raw.stdout)


def extract_frame(src: Path, at: float, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = tools.run(
        ["-y", "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1", str(dest)],
        timeout=60,
    )
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"frame extract failed at {at}\n{(proc.stderr or '')[-400:]}")


ids = ["night-sky", "ocean", "dawn"]
for bid in ids:
    resolve_background(bid)

clips_meta = []
for bid in ids:
    p = resolve_background(bid)
    d = tools.probe_duration(p)
    start = min(1.0, max(0.0, d * 0.1))
    end = min(d, start + 4.0)
    clips_meta.append(BackgroundClip(id=f"clip-{bid}", sourceId=bid, trimStart=start, trimEnd=end))
    print(f"trim {bid}: {start:.2f}-{end:.2f} ({end - start:.2f}s)")

bg = BackgroundSettings(
    id="night-sky",
    clips=clips_meta,
    crossfade=True,
    transitionDuration=0.5,
)
resolved = bgtl.resolve_clips(bg)
xf = bgtl.xfade_duration(resolved, True, 0.5)
expect = bgtl.sequence_duration(resolved, True, 0.5)
print(f"xfade={xf:.3f}s  sequence={expect:.3f}s")

tmp = Path("temp") / "bg_crossfade"
tmp.mkdir(parents=True, exist_ok=True)
out = tmp / "sequence.mp4"
bgtl.compose_sequence(resolved, True, out, 540, 960, "center", 0.5)
got = tools.probe_duration(out)
print(f"composed {got:.3f}s")
check("compose duration matches math", abs(got - expect) < 0.25, f"{got} vs {expect}")
check("xfade is 0.5s", abs(xf - 0.5) < 1e-6)

# First join is at used0 - xf
join1 = resolved[0].duration - xf
mid = join1 + xf / 2
before = max(0.05, join1 - 0.2)
after = min(expect - 0.05, join1 + xf + 0.2)

f_before = tmp / "before.png"
f_mid = tmp / "mid.png"
f_after = tmp / "after.png"
extract_frame(out, before, f_before)
extract_frame(out, mid, f_mid)
extract_frame(out, after, f_after)

y0 = mean_luma(f_before)
y1 = mean_luma(f_mid)
y2 = mean_luma(f_after)
print(f"luma before={y0:.2f} mid={y1:.2f} after={y2:.2f}")

check("mid-fade is not black", y1 > 8, str(y1))
check("before join is not black", y0 > 8, str(y0))
check("after join is not black", y2 > 8, str(y2))
check(
    "mid-fade is not a copy of either side",
    abs(y1 - y0) > 0.4 or abs(y1 - y2) > 0.4,
    f"dBefore={abs(y1 - y0):.2f} dAfter={abs(y1 - y2):.2f}",
)

# Second join
join2 = resolved[0].duration + resolved[1].duration - 2 * xf
mid2 = join2 + xf / 2
f_mid2 = tmp / "mid2.png"
extract_frame(out, mid2, f_mid2)
y3 = mean_luma(f_mid2)
print(f"luma mid2={y3:.2f} at {mid2:.2f}s")
check("second join is not black", y3 > 8, str(y3))

print()
print("ALL PASS" if all_pass else "SOME FAILED")
sys.exit(0 if all_pass else 1)
