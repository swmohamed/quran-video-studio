"""Background FFmpeg input + filter construction (cover-crop, adjustments, loop/trim)."""
from __future__ import annotations

from pathlib import Path

from app.core.config import VIDEO_FPS
from app.models.schemas import BackgroundSettings
from app.services.backgrounds import resolve_background

VIDEO_EXT = {".mp4", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}


def background_input_args(bg_path: Path, total_duration: float) -> list[str]:
    """Input flags. Videos loop automatically (-stream_loop -1) and are trimmed
    by the output -t; images loop for the full duration."""
    if bg_path.suffix.lower() in VIDEO_EXT:
        return ["-stream_loop", "-1", "-i", str(bg_path)]
    return ["-loop", "1", "-framerate", "30", "-t", f"{total_duration + 1:.3f}", "-i", str(bg_path)]


def background_filter(bg: BackgroundSettings, width: int, height: int, in_label: str = "0:v") -> str:
    """Filter chain that mirrors the browser preview EXACTLY:
    cover-scale -> crop -> brightness+contrast in RGB (CSS semantics) ->
    saturation -> gaussian blur (CSS blur = sigma/2) -> dark overlay.
    Stays full-chroma RGB so verse overlays are not composited on 4:2:0."""
    chain: list[str] = []

    # cover (high-quality scaling: no chroma smearing on downscale)
    chain.append(
        f"scale={width}:{height}:force_original_aspect_ratio=increase:"
        "flags=lanczos+accurate_rnd+full_chroma_int"
    )
    # crop with vertical position bias, HORIZONTALLY CENTERED — matches the
    # preview's object-cover (object-position: center X)
    if bg.position == "top":
        y = 0
    elif bg.position == "bottom":
        y = "ih-oh"
    else:
        y = "(ih-oh)/2"
    chain.append(f"crop={width}:{height}:(iw-ow)/2:{y}")

    # brightness + contrast in linear RGB — identical math to CSS
    # brightness(x) then contrast(c): v' = (v*x - 128)*c + 128
    chain.append("format=gbrp")
    b = bg.brightness / 100.0
    c = bg.contrast / 100.0
    lut = ":".join(
        f"{ch}='clip((val*{b:.4f}-128)*{c:.4f}+128,0,255)'" for ch in ("r", "g", "b")
    )
    chain.append(f"lutrgb={lut}")

    # dark overlay in RGB — blends toward true black exactly like the
    # preview's rgba(0,0,0,x) div. (drawbox in yuv space shifts chroma.)
    if bg.darkOverlay > 0:
        chain.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{bg.darkOverlay / 100.0:.2f}:t=fill"
        )

    # Stay in full-chroma RGB until text overlays are composited.
    # Converting to limited-range YUV here crushed cream ink and forced a
    # second RGB↔YUV round-trip under the verse.
    sat = bg.saturation / 100.0
    if abs(sat - 1.0) > 0.001:
        chain.append(f"hue=s={sat:.4f}")

    if bg.blur > 0:
        r = max(1, min(40, bg.blur))
        chain.append(f"gblur=sigma={r / 2:.2f}")

    # Frame-rate only, once, on the background — never after text overlays.
    chain.append(f"fps={VIDEO_FPS}")

    return f"[{in_label}]{','.join(chain)}[bgv]"


def resolve(bg_id: str) -> Path:
    return resolve_background(bg_id)
