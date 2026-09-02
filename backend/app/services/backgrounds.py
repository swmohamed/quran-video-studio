"""Background listing, uploads, and thumbnails."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from app.core.config import (
    ALLOWED_BACKGROUND_EXT,
    BACKGROUNDS_DIR,
    DATA_DIR,
    MAX_UPLOAD_BYTES,
    THUMBS_DIR,
    UPLOADS_DIR,
)
from app.core.ffmpeg import tools


class BackgroundError(RuntimeError):
    pass


_NAMES_FILE = DATA_DIR / "stock_names.json"


def _display_names() -> dict[str, str]:
    """Friendly display names for stock backgrounds (persisted)."""
    try:
        return json.loads(_NAMES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_display_name(stem: str, name: str) -> None:
    names = _display_names()
    names[stem] = name[:40]
    try:
        _NAMES_FILE.write_text(json.dumps(names, indent=1), encoding="utf-8")
    except OSError:
        pass


_BUILTIN_NAMES = {
    "night-sky": "Night Sky",
    "dawn": "Dawn",
    "ocean": "Deep Ocean",
    "emerald": "Emerald",
    "sand": "Warm Sand",
}


def _entry(path: Path, uploaded: bool) -> dict[str, Any]:
    stem = path.stem
    is_video = path.suffix.lower() in {".mp4", ".webm"}
    entry: dict[str, Any] = {
        "id": stem,
        "file": path.name,
        "kind": "video" if is_video else "image",
        "uploaded": uploaded,
        "name": _display_names().get(stem) or _BUILTIN_NAMES.get(
            stem, " ".join(w.capitalize() for w in stem.split("-"))),
        "url": f"/static/{'uploads' if uploaded else 'backgrounds'}/{path.name}",
    }
    thumb = THUMBS_DIR / f"{stem}.jpg"
    if not thumb.exists():
        try:
            thumb.parent.mkdir(parents=True, exist_ok=True)
            if is_video:
                import subprocess
                subprocess.run(
                    [tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", "1", "-i", str(path), "-frames:v", "1", "-q:v", "3", str(thumb)],
                    check=True, timeout=60, capture_output=True,
                )
            else:
                import shutil
                from PIL import Image
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((216, 384))
                    im.save(thumb, "JPEG", quality=80)
        except Exception:
            pass
    if thumb.exists():
        entry["thumb"] = f"/static/backgrounds/thumbs/{thumb.name}"
    try:
        if is_video:
            entry["duration"] = round(tools.probe_duration(path), 2)
    except Exception:
        pass
    return entry


def list_backgrounds() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(BACKGROUNDS_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in ALLOWED_BACKGROUND_EXT:
            out.append(_entry(path, uploaded=False))
    for path in sorted(UPLOADS_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in ALLOWED_BACKGROUND_EXT:
            out.append(_entry(path, uploaded=True))
    return out


def resolve_background(bg_id: str) -> Path:
    """Resolve a background id to a local file, safely (no traversal)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", bg_id or ""):
        raise BackgroundError("Invalid background id")
    for root in (BACKGROUNDS_DIR, UPLOADS_DIR):
        for path in root.iterdir():
            if path.is_file() and path.stem == bg_id and path.suffix.lower() in ALLOWED_BACKGROUND_EXT:
                return path
    raise BackgroundError(f"Background '{bg_id}' was not found")


_slug_re = re.compile(r"[^a-z0-9-]+")


def save_upload(upload: UploadFile) -> dict[str, Any]:
    if upload.filename is None:
        raise HTTPException(400, "Upload has no filename")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_BACKGROUND_EXT:
        raise HTTPException(400, f"Unsupported background type '{suffix}'. Use MP4, WebM, JPG or PNG.")
    stem = _slug_re.sub("-", Path(upload.filename).stem.lower()).strip("-")[:60] or "background"
    dest = UPLOADS_DIR / f"{stem}{suffix}"
    # avoid clobbering
    n = 1
    while dest.exists():
        dest = UPLOADS_DIR / f"{stem}-{n}{suffix}"
        n += 1
    size = 0
    try:
        with open(dest, "wb") as fh:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(400, "Background file is larger than 200 MB.")
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    if size < 1024:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Background file is empty or unreadable.")
    # validate it is actual media via ffprobe
    try:
        info = tools.probe_json(dest)
        has_video = any(s.get("codec_type") == "video" for s in info.get("streams", []))
        if not has_video:
            raise BackgroundError("no video stream")
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "That file could not be read as a valid image or video.")
    return _entry(dest, uploaded=True)
