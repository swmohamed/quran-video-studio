"""Unit tests for background clip timeline math (no media files required)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.renderer.bg_timeline import (
    MIN_CLIP_S,
    ResolvedClip,
    clip_at,
    clip_is_trimmed,
    layers_at,
    map_audio_to_sequence,
    needs_compose,
    sequence_duration,
    xfade_duration,
    _clamp_trim,
)

all_pass = True


def check(name: str, ok: bool, extra: str = "") -> None:
    global all_pass
    all_pass &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


def clip(cid: str, start: float, end: float, src: float = 45.0) -> ResolvedClip:
    return ResolvedClip(
        id=cid,
        source_id=cid,
        path=Path(f"{cid}.mp4"),
        kind="video",
        src_dur=src,
        trim_start=start,
        trim_end=end,
    )


print("== clamp trim ==")
t0, t1 = _clamp_trim(12, 27, 45)
check("12–27 on 45s source", (t0, t1) == (12.0, 27.0), f"{t0},{t1}")
t0, t1 = _clamp_trim(0, 0, 45)
check("end 0 means rest of source", (t0, t1) == (0.0, 45.0), f"{t0},{t1}")
t0, t1 = _clamp_trim(40, 10, 45)
check("end before start is forced to min length", t1 >= t0 + MIN_CLIP_S and t0 == 40.0, f"{t0},{t1}")
t0, t1 = _clamp_trim(-4, 99, 45)
check("out of range is clamped", (t0, t1) == (0.0, 45.0), f"{t0},{t1}")

print("== sequence duration + loop map ==")
clips = [
    clip("mountains", 10, 25),  # 15s
    clip("ocean", 5, 20),       # 15s
    clip("clouds", 15, 30),     # 15s
]
check("three 15s clips = 45s", abs(sequence_duration(clips, False) - 45.0) < 1e-6, str(sequence_duration(clips, False)))
check("audio shorter than seq stays in seq", map_audio_to_sequence(20, 45, 30) == 20)
check("audio longer than seq loops", abs(map_audio_to_sequence(50, 45, 80) - 5.0) < 1e-6)
check("playhead past audio is clamped then mapped", abs(map_audio_to_sequence(99, 45, 80) - (80 % 45)) < 1e-6)
check("seq longer than audio is trimmed at audio", map_audio_to_sequence(40, 45, 30) == 30)

print("== clip_at respects trim ==")
idx, src_t = clip_at(0, clips, False)
check("t=0 is mountains at in-point", idx == 0 and abs(src_t - 10.0) < 1e-6, f"{idx},{src_t}")
idx, src_t = clip_at(15, clips, False)
check("t=15 is ocean at in-point", idx == 1 and abs(src_t - 5.0) < 1e-6, f"{idx},{src_t}")
idx, src_t = clip_at(20, clips, False)
check("t=20 is ocean +5s", idx == 1 and abs(src_t - 10.0) < 1e-6, f"{idx},{src_t}")
idx, src_t = clip_at(30, clips, False)
check("t=30 is clouds at in-point", idx == 2 and abs(src_t - 15.0) < 1e-6, f"{idx},{src_t}")

print("== compose decision ==")
full = clip("a", 0, 40, 40)
part = clip("b", 12, 27, 45)
check("full single clip skips compose", needs_compose([full]) is False)
check("trimmed single clip needs compose", needs_compose([part]) is True)
check("multi clip needs compose", needs_compose(clips) is True)
check("untrimmed is not trimmed", clip_is_trimmed(full) is False)
check("in/out is trimmed", clip_is_trimmed(part) is True)

print("== text offsets are % of canvas ==")
from app.renderer.text import _user_offset

class _Layer:
    def __init__(self, x: float, y: float) -> None:
        self.offsetX = x
        self.offsetY = y

check("10% x / -5% y on 1080×1920", _user_offset(_Layer(10, -5), 1080, 1920) == (108, -96))
check("zero stays default", _user_offset(_Layer(0, 0), 1080, 1920) == (0, 0))

print("== crossfade shortens sequence ==")
xf = xfade_duration(clips, True, 0.5)
seq_xf = sequence_duration(clips, True, 0.5)
check("default requested fade is 0.5s", abs(xf - 0.5) < 1e-6, str(xf))
check("custom 0.7s is honored", abs(xfade_duration(clips, True, 0.7) - 0.7) < 1e-6)
check("crossfade sequence is shorter by 1.0s for 3 clips", abs(seq_xf - 44.0) < 1e-6, str(seq_xf))
check("crossfade off is zero", xfade_duration(clips, False, 0.5) == 0.0)

print("== crossfade blends A-out with B-in ==")
# mountains 10–25, ocean 5–20; fade 0.5 starts at 14.5
layers = layers_at(14.5, clips, True, 0.5)
check("fade start has two layers", len(layers) == 2, str(layers))
check("incoming is ocean at in-point", layers[0][0] == 1 and abs(layers[0][1] - 5.0) < 1e-6, str(layers[0]))
check("outgoing is mountains at last 0.5s", layers[1][0] == 0 and abs(layers[1][1] - 24.5) < 1e-6, str(layers[1]))
check("outgoing still fully visible at fade start", abs(layers[1][2] - 1.0) < 1e-6, str(layers[1][2]))
layers = layers_at(14.75, clips, True, 0.5)
check("mid fade mixes 50/50 opacity on top", abs(layers[1][2] - 0.5) < 1e-6, str(layers[1][2]))
check("mid fade outgoing is 24.75", abs(layers[1][1] - 24.75) < 1e-6, str(layers[1][1]))
check("mid fade incoming is 5.25", abs(layers[0][1] - 5.25) < 1e-6, str(layers[0][1]))
idx, src_t = clip_at(14.75, clips, True, 0.5)
check("clip_at during fade reports incoming", idx == 1 and abs(src_t - 5.25) < 1e-6, f"{idx},{src_t}")

print()
print("ALL PASS" if all_pass else "SOME FAILED")
sys.exit(0 if all_pass else 1)
