"""Quran text data access (cached alquran.cloud data under data/)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR, VERSES_DIR


class QuranDataError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def surahs() -> list[dict[str, Any]]:
    path = DATA_DIR / "surahs.json"
    if not path.exists():
        raise QuranDataError(
            "Surah metadata is missing. Run backend/scripts/fetch_quran_data.py "
            "(or setup.bat) to download the Quran text cache."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    out = data["surahs"]
    if len(out) != 114:
        raise QuranDataError(f"Expected 114 surahs, found {len(out)}")
    return out


def get_surah(number: int) -> dict[str, Any]:
    for s in surahs():
        if s["number"] == number:
            return s
    raise QuranDataError(f"Surah {number} not found")


@lru_cache(maxsize=16)
def _verses_file(surah: int) -> dict[str, Any]:
    path = VERSES_DIR / f"{surah:03d}.json"
    if not path.exists():
        raise QuranDataError(f"Verse data for surah {surah} is missing from the local cache.")
    return json.loads(path.read_text(encoding="utf-8"))


def get_ayat(surah: int, from_ayah: int, to_ayah: int) -> list[dict[str, Any]]:
    """Validated slice of ayah records with arabic text + translations."""
    meta = get_surah(surah)
    if not (1 <= from_ayah <= to_ayah <= meta["ayahCount"]):
        raise QuranDataError(
            f"Invalid ayah range {from_ayah}-{to_ayah} for {meta['englishName']} "
            f"(1-{meta['ayahCount']})."
        )
    ayahs = _verses_file(surah)["ayahs"]
    return [a for a in ayahs if from_ayah <= a["ayah"] <= to_ayah]


@lru_cache(maxsize=1)
def translations() -> list[dict[str, Any]]:
    path = DATA_DIR / "translations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["translations"]


def get_translation(id_: str) -> dict[str, Any]:
    for t in translations():
        if t["id"] == id_:
            return t
    raise QuranDataError(f"Unknown translation '{id_}'")


@lru_cache(maxsize=1)
def presets() -> list[dict[str, Any]]:
    path = DATA_DIR / "presets.json"
    return json.loads(path.read_text(encoding="utf-8"))["presets"]


def quran_source_note() -> str:
    v = _verses_file(1)
    return v.get("source", {}).get("arabic", "alquran.cloud (Tanzil Uthmani text)")
