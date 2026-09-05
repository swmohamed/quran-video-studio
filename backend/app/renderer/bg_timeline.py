"""Background clip timeline — trim, order, concat, optional crossfade.

The Quran audio duration is the master clock. This module only builds the
visual sequence; it never changes recitation length.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.ffmpeg import tools
from app.models.schemas import BackgroundClip, BackgroundSettings
from app.services.backgrounds import resolve_background

VIDEO_EXT = {".mp4", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
IMAGE_DEFAULT_S = 8.0
DEFAULT_XFADE_S = 0.50
XFADE_MIN_S = 0.20
XFADE_MAX_S = 1.00
XFADE_S = DEFAULT_XFADE_S
MIN_CLIP_S = 0.05


@dataclass
class ResolvedClip:
    id: str
    source_id: str
    path: Path
    kind: str  # video | image
    src_dur: float
    trim_start: float
    trim_end: float

    @property
    def duration(self) -> float:
        return max(MIN_CLIP_S, self.trim_end - self.trim_start)


def _source_duration(path: Path, kind: str) -> float:
    if kind == "image":
        return IMAGE_DEFAULT_S
    try:
        return max(MIN_CLIP_S, tools.probe_duration(path))
    except Exception:
        return IMAGE_DEFAULT_S


def _clamp_trim(start: float, end: float, src_dur: float) -> tuple[float, float]:
    src = max(MIN_CLIP_S, src_dur)
    t0 = max(0.0, min(float(start), src - MIN_CLIP_S))
    t1 = float(end) if end and end > 0 else src
    t1 = min(src, max(t0 + MIN_CLIP_S, t1))
    return t0, t1


def resolve_clips(bg: BackgroundSettings) -> list[ResolvedClip]:
    """Normalize settings into playable clips. Empty clips → single current id."""
    raw = list(bg.clips or [])
    if not raw:
        raw = [BackgroundClip(id="legacy", sourceId=bg.id, trimStart=0, trimEnd=0)]
    out: list[ResolvedClip] = []
    for c in raw:
        path = resolve_background(c.sourceId)
        kind = "video" if path.suffix.lower() in VIDEO_EXT else "image"
        src_dur = _source_duration(path, kind)
        if kind == "image" and c.trimEnd > 0:
            src_dur = max(src_dur, float(c.trimEnd))
        t0, t1 = _clamp_trim(c.trimStart, c.trimEnd, src_dur)
        out.append(ResolvedClip(
            id=c.id or c.sourceId,
            source_id=c.sourceId,
            path=path,
            kind=kind,
            src_dur=src_dur,
            trim_start=t0,
            trim_end=t1,
        ))
    return out


def clip_is_trimmed(clip: ResolvedClip) -> bool:
    return clip.trim_start > 0.02 or clip.trim_end < clip.src_dur - 0.05


def _clamp_requested_xfade(requested: float | None) -> float:
    try:
        n = float(requested) if requested is not None else DEFAULT_XFADE_S
    except (TypeError, ValueError):
        n = DEFAULT_XFADE_S
    if n != n:  # NaN
        n = DEFAULT_XFADE_S
    return min(XFADE_MAX_S, max(XFADE_MIN_S, n))


def xfade_duration(
    clips: list[ResolvedClip],
    enabled: bool,
    requested: float | None = None,
) -> float:
    if not enabled or len(clips) < 2:
        return 0.0
    want = _clamp_requested_xfade(requested)
    shortest = min(c.duration for c in clips)
    cap = max(0.0, shortest - MIN_CLIP_S)
    if cap < 0.05:
        return 0.0
    return min(want, cap)


def sequence_duration(
    clips: list[ResolvedClip],
    crossfade: bool,
    requested: float | None = None,
) -> float:
    if not clips:
        return 0.0
    total = sum(c.duration for c in clips)
    xf = xfade_duration(clips, crossfade, requested)
    if xf:
        total -= xf * (len(clips) - 1)
    return max(MIN_CLIP_S, total)


def map_audio_to_sequence(t: float, seq_dur: float, audio_dur: float) -> float:
    """Audio time → time inside the (possibly looping) background sequence."""
    if seq_dur <= 0:
        return 0.0
    t = max(0.0, float(t))
    if audio_dur > 0:
        t = min(t, audio_dur)
    if seq_dur + 1e-4 >= audio_dur:
        return min(t, seq_dur)
    return t % seq_dur


def clip_at(
    seq_t: float,
    clips: list[ResolvedClip],
    crossfade: bool,
    requested: float | None = None,
) -> tuple[int, float]:
    """Return (clip_index, time inside the source trim)."""
    layers = layers_at(seq_t, clips, crossfade, requested)
    return layers[0][0], layers[0][1]


def layers_at(
    seq_t: float,
    clips: list[ResolvedClip],
    crossfade: bool,
    requested: float | None = None,
) -> list[tuple[int, float, float]]:
    """(index, source_time, opacity) bottom-to-top. Incoming is under outgoing
    during a fade so a 1→0 opacity on top is A*(1-p)+B*p, same as xfade."""
    if not clips:
        return [(0, 0.0, 1.0)]
    xf = xfade_duration(clips, crossfade, requested)
    used = [c.duration for c in clips]
    starts = [0.0]
    for i in range(len(clips) - 1):
        starts.append(starts[i] + max(MIN_CLIP_S, used[i] - xf))
    t = max(0.0, float(seq_t))

    def layer(i: int) -> tuple[int, float, float]:
        local = min(used[i] - 1e-3, max(0.0, t - starts[i]))
        return i, clips[i].trim_start + local, 1.0

    for i in range(len(clips) - 1):
        fade0 = starts[i + 1]
        fade1 = fade0 + xf
        if xf > 0 and fade0 <= t < fade1:
            p = min(1.0, max(0.0, (t - fade0) / xf))
            incoming = layer(i + 1)
            outgoing = layer(i)
            return [(incoming[0], incoming[1], 1.0), (outgoing[0], outgoing[1], 1.0 - p)]

    for i in range(len(clips)):
        end = starts[i + 1] if i < len(clips) - 1 else starts[i] + used[i]
        if t < end or i == len(clips) - 1:
            return [layer(i)]
    return [layer(len(clips) - 1)]


def needs_compose(clips: list[ResolvedClip]) -> bool:
    return len(clips) > 1 or (len(clips) == 1 and clip_is_trimmed(clips[0]))


def _crop_y(position: str) -> str:
    if position == "top":
        return "0"
    if position == "bottom":
        return "ih-oh"
    return "(ih-oh)/2"


def compose_sequence(
    clips: list[ResolvedClip],
    crossfade: bool,
    out_path: Path,
    width: int,
    height: int,
    position: str = "center",
    transition_duration: float | None = None,
) -> Path:
    """Write a single video of the trimmed clip sequence. Does not loop or
    pad to audio length — the caller loops/trims with -stream_loop / -t.

    Crossfade blends the last ``xf`` seconds of each trimmed clip with the
    first ``xf`` seconds of the next. Sources are never rewritten.
    """
    if not clips:
        raise RuntimeError("No background clips to compose.")
    args: list[str] = ["-y"]
    for clip in clips:
        if clip.kind == "image":
            args += [
                "-loop", "1",
                "-framerate", "30",
                "-t", f"{clip.duration:.3f}",
                "-i", str(clip.path),
            ]
        else:
            # Seek to the in-point, then take an exact trimmed duration so
            # xfade overlaps A-out with B-in — not the start of A again.
            args += [
                "-ss", f"{clip.trim_start:.4f}",
                "-i", str(clip.path),
            ]

    y = _crop_y(position)
    parts: list[str] = []
    labels: list[str] = []
    geo = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:"
        f"flags=lanczos+accurate_rnd+full_chroma_int,"
        f"crop={width}:{height}:(iw-ow)/2:{y},"
        f"fps=30,setsar=1,format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration=0.08"
    )
    for i, clip in enumerate(clips):
        if clip.kind == "image":
            parts.append(f"[{i}:v]setpts=PTS-STARTPTS,{geo}[v{i}]")
        else:
            parts.append(
                f"[{i}:v]trim=duration={clip.duration:.4f},"
                f"setpts=PTS-STARTPTS,{geo}[v{i}]"
            )
        labels.append(f"[v{i}]")

    xf = xfade_duration(clips, crossfade, transition_duration)
    if xf and len(clips) > 1:
        prev = "v0"
        acc = clips[0].duration
        for i in range(1, len(clips)):
            offset = max(0.0, acc - xf)
            nxt = f"x{i}"
            parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:duration={xf:.3f}:offset={offset:.3f}[{nxt}]"
            )
            prev = nxt
            acc += clips[i].duration - xf
        parts.append(f"[{prev}]format=yuv420p[vout]")
    else:
        parts.append(f"{''.join(labels)}concat=n={len(clips)}:v=1:a=0,format=yuv420p[vout]")

    args += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        str(out_path),
    ]
    proc = tools.run(args, timeout=600)
    if proc.returncode != 0 or not out_path.exists():
        tail = (proc.stderr or "")[-800:]
        raise RuntimeError(f"Background timeline compose failed.\n{tail}")
    return out_path


def prepare_input_args(
    bg: BackgroundSettings,
    audio_total: float,
    tmp: Path,
    width: int,
    height: int,
) -> list[str]:
    """FFmpeg input args for the background track, duration-capped by audio."""
    from app.renderer.background import background_input_args

    clips = resolve_clips(bg)
    if not needs_compose(clips):
        return background_input_args(clips[0].path, audio_total)
    out = tmp / "bg_sequence.mp4"
    compose_sequence(
        clips,
        bg.crossfade,
        out,
        width,
        height,
        bg.position,
        bg.transitionDuration,
    )
    return background_input_args(out, audio_total)
