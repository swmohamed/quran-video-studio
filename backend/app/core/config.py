"""Application paths and constants. All paths derive from the project root."""
from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
ROOT = BACKEND_DIR.parent                          # quran-video-studio/

DATA_DIR = ROOT / "data"
VERSES_DIR = DATA_DIR / "verses"
AUDIO_DIR = ROOT / "audio"
RECITERS_DIR = AUDIO_DIR / "reciters"
BACKGROUNDS_DIR = ROOT / "backgrounds"
THUMBS_DIR = BACKGROUNDS_DIR / "thumbs"
UPLOADS_DIR = ROOT / "uploads"
TEMP_DIR = ROOT / "temp"
OUTPUT_DIR = ROOT / "output"
FONTS_DIR = ROOT / "fonts"

for _d in (VERSES_DIR, RECITERS_DIR, BACKGROUNDS_DIR, THUMBS_DIR, UPLOADS_DIR, TEMP_DIR, OUTPUT_DIR, AUDIO_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Video output constants (default platform = TikTok vertical)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
MAX_AYAHS_PER_RENDER = 30
FADE_SECONDS = 0.28  # subtle verse transition

# Platform / video-format presets. Every preset carries explicit output
# dimensions; social vertical platforms stay separate so safe zones can be
# defined per platform (preview-only, frontend).
PLATFORM_PRESETS: dict[str, dict] = {
    "tiktok": {"label": "TikTok", "width": 1080, "height": 1920, "orientation": "portrait", "aspect": "9:16"},
    "shorts": {"label": "YouTube Shorts", "width": 1080, "height": 1920, "orientation": "portrait", "aspect": "9:16"},
    "reels": {"label": "Instagram Reels", "width": 1080, "height": 1920, "orientation": "portrait", "aspect": "9:16"},
    "youtube": {"label": "YouTube", "width": 1920, "height": 1080, "orientation": "landscape", "aspect": "16:9"},
    "portrait": {"label": "Portrait", "width": 1080, "height": 1350, "orientation": "portrait", "aspect": "4:5"},
    "square": {"label": "Square", "width": 1080, "height": 1080, "orientation": "square", "aspect": "1:1"},
}
DEFAULT_PLATFORM = "tiktok"


def platform_dims(platform: str | None) -> tuple[int, int]:
    """(width, height) for a platform id; unknown ids fall back to the default."""
    p = PLATFORM_PRESETS.get(platform or "", PLATFORM_PRESETS[DEFAULT_PLATFORM])
    return p["width"], p["height"]

# Upload limits
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
ALLOWED_BACKGROUND_EXT = {".mp4", ".webm", ".jpg", ".jpeg", ".png"}


def rel_to_root(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)
