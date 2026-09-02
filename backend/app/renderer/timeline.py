"""Verse timeline built from measured audio durations (never guessed)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    surah: int
    ayah: int
    audio_path: Path
    duration: float
    start: float = 0.0
    end: float = 0.0
    card_path: Path | None = field(default=None)


def build_timeline(items: list[tuple[int, int, Path, float]]) -> list[Segment]:
    """items: (surah, ayah, audio_path, measured_duration) -> sequential segments."""
    segments: list[Segment] = []
    t = 0.0
    for surah, ayah, path, dur in items:
        seg = Segment(surah=surah, ayah=ayah, audio_path=path, duration=dur, start=t, end=t + dur)
        segments.append(seg)
        t += dur
    return segments


def total_duration(segments: list[Segment]) -> float:
    return segments[-1].end if segments else 0.0
