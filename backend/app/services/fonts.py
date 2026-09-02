"""Font catalog (files under fonts/) shared by renderer and API."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import FONTS_DIR


class FontError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def catalog() -> dict:
    return {
        "arabic": [
            {"id": "amiri", "name": "Amiri", "file": "Amiri-Regular.ttf"},
            {"id": "notonaskh", "name": "Noto Naskh Arabic", "file": "NotoNaskhArabic.ttf"},
            {"id": "notosansarabic", "name": "Noto Sans Arabic", "file": "NotoSansArabic.ttf"},
        ],
        "latin": [
            {"id": "amiri", "name": "Amiri Serif", "file": "Amiri-Regular.ttf"},
            {"id": "inter", "name": "Inter", "file": "Inter.ttf"},
        ],
    }


def font_path(font_id: str, script: str) -> Path:
    cat = catalog()
    for f in cat.get(script, []):
        if f["id"] == font_id:
            p = FONTS_DIR / f["file"]
            if not p.exists():
                raise FontError(f"Font file missing: {p.name}. Re-run setup.bat to download fonts.")
            return p
    raise FontError(f"Unknown {script} font '{font_id}'")
