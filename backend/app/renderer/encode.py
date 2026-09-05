"""Single-pass continuous composition.

Timeline model (professional-editor equivalent):
  [0] background  — ONE continuous input (looped/trimmed to total)
  [1] audio       — ONE continuous WAV (zero-gap assembled recitation)
  [2] persistent  — ONE static overlay (Surah header + card), never fades
  [3+i] ayah text — transparent TEXT-ONLY overlays, 120ms alpha fades

There are no per-ayah scenes, no per-ayah encodes, no background restarts,
no black frames, and no whole-composition fades. Only the verse text
cross-fades at audio boundaries.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable

from app.core.config import VIDEO_FPS
from app.core.ffmpeg import FFmpegNotFound, tools
from app.renderer.timeline import Segment

TEXT_FADE = 0.12  # subtle text-only crossfade (spec: 80-150ms)

# x264 quality tiers. CRF stays in the 16–18 band so thin Arabic strokes
# survive TikTok / phone / desktop playback without a later upscale.
QUALITY_TIERS = {
    "max": {"crf": 16, "preset": "slow"},
    "high": {"crf": 16, "preset": "medium"},
    "small": {"crf": 18, "preset": "slow"},
}


class EncodeError(RuntimeError):
    pass


def _overlay_prep(extra: str, overlay_scale: tuple[int, int] | None) -> str:
    """Keep the PNG as lossless RGBA; Lanczos-downscale at most once."""
    steps = ["format=rgba"]
    if overlay_scale:
        steps.append(
            f"scale={overlay_scale[0]}:{overlay_scale[1]}:"
            "flags=lanczos+accurate_rnd+full_chroma_int"
        )
    if extra:
        steps.append(extra)
    return ",".join(steps)


def build_filter_complex(
    bg_filter: str,
    segments: list[Segment],
    fade: float,
    overlay_scale: tuple[int, int] | None = None,
) -> str:
    """overlay_scale: when text layers were rendered supersampled,
    they are lanczos-downscaled here once. Composition stays full-chroma
    (gbrp) until a single final yuv420p convert for H.264."""
    parts = [bg_filter]
    # persistent header+card layer: static, always on, never faded
    parts.append(f"[2:v]{_overlay_prep('', overlay_scale)}[persist]")
    parts.append(
        "[bgv][persist]overlay=x=0:y=0:shortest=0:format=gbrp:alpha=straight[base]"
    )
    prev = "base"
    for i, seg in enumerate(segments):
        idx = 3 + i  # 0=bg, 1=audio, 2=persistent, 3..=ayah text
        start, end = seg.start, seg.end
        tf = min(TEXT_FADE, max(0.04, (end - start) / 4))
        fade_out_st = max(start, end - tf)
        if i == 0:
            # First ayah: text is fully present from frame 0 — no fade-in,
            # so the very first frame already carries the verse.
            extra = (
                f"setpts=PTS-STARTPTS+{start:.3f}/TB,"
                f"fade=t=out:st={fade_out_st:.3f}:d={tf:.3f}:alpha=1"
            )
        else:
            extra = (
                f"setpts=PTS-STARTPTS+{start:.3f}/TB,"
                f"fade=t=in:st={start:.3f}:d={tf:.3f}:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={tf:.3f}:alpha=1"
            )
        parts.append(f"[{idx}:v]{_overlay_prep(extra, overlay_scale)}[ov{i}]")
        parts.append(
            f"[{prev}][ov{i}]overlay=x=0:y=0:eof_action=pass:shortest=0:"
            f"format=gbrp:alpha=straight[v{i}]"
        )
        prev = f"v{i}"
    # One chroma downsample, after every overlay — never before text.
    # Explicit full-RGB → limited bt709 so cream verse ink is not crushed
    # by an implicit range guess.
    parts.append(
        f"[{prev}]scale=in_range=full:out_range=tv:out_color_matrix=bt709:"
        f"flags=accurate_rnd+full_chroma_int,"
        f"setparams=color_primaries=bt709:color_trc=bt709:"
        f"colorspace=bt709:range=tv,format=yuv420p[vout]"
    )
    parts.append("[1:a]aformat=sample_rates=44100:channel_layouts=stereo[aout]")
    return ";".join(parts)


def build_args(
    bg_filter: str,
    bg_args: list[str],
    audio_path: Path,
    persistent_png: Path,
    segments: list[Segment],
    total: float,
    out_path: Path,
    quality: str = "high",
    overlay_scale: tuple[int, int] | None = None,
) -> list[str]:
    filter_complex = build_filter_complex(bg_filter, segments, TEXT_FADE, overlay_scale)
    tier = QUALITY_TIERS.get(quality, QUALITY_TIERS["high"])
    args = [
        "-y", "-hide_banner", "-nostdin",
        *bg_args,
        "-i", str(audio_path),
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{total:.3f}", "-i", str(persistent_png),
    ]
    for seg in segments:
        seg_dur = seg.end - seg.start + 0.05
        args += ["-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{seg_dur:.3f}",
                 "-i", str(seg.card_path)]
    args += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", tier["preset"], "-crf", str(tier["crf"]),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
        "-x264-params", "aq-mode=3:deblock=-1,-1",
        "-sws_flags", "lanczos+accurate_rnd+full_chroma_int",
        # explicit color pipeline — prevents player-side washed/shifted colors
        "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart",
        "-t", f"{total:.3f}",
        str(out_path),
        "-progress", "pipe:1", "-nostats",
    ]
    return args


def run_encode(
    bg_filter: str,
    bg_args: list[str],
    audio_path: Path,
    persistent_png: Path,
    segments: list[Segment],
    total: float,
    out_path: Path,
    on_progress: Callable[[float], None],
    register_proc: Callable[[subprocess.Popen], None],
    quality: str = "high",
    overlay_scale: tuple[int, int] | None = None,
) -> None:
    args = build_args(bg_filter, bg_args, audio_path, persistent_png, segments, total, out_path, quality, overlay_scale)
    try:
        ffmpeg = tools.ffmpeg
    except FFmpegNotFound as exc:
        raise EncodeError(str(exc)) from exc

    proc = subprocess.Popen(
        [ffmpeg, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    register_proc(proc)

    stderr_tail: list[str] = []

    def drain_stderr() -> None:
        try:
            for line in proc.stderr:
                stderr_tail.append(line)
                if len(stderr_tail) > 60:
                    del stderr_tail[:30]
        except Exception:
            pass

    threading.Thread(target=drain_stderr, daemon=True).start()

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                val = int(line.split("=", 1)[1])
                out_time = val / 1_000_000.0
                on_progress(min(1.0, max(0.0, out_time / total)) if total > 0 else 0.0)
            except ValueError:
                continue
        elif line.startswith("progress="):
            if line.split("=", 1)[1] == "end":
                break

    proc.wait()
    on_progress(1.0)
    if proc.returncode != 0:
        tail = "\n".join(stderr_tail[-12:]).strip()
        raise EncodeError(
            f"FFmpeg encoding failed (exit code {proc.returncode})."
            + (f"\n{tail}" if tail else "")
        )
