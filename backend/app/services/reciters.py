"""Reciter registry + on-demand verse audio downloads (everyayah.com, SSSAAA.mp3)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import requests

from app.core.config import DATA_DIR, RECITERS_DIR


class ReciterError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict]:
    path = DATA_DIR / "reciters.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["reciters"]}


def list_reciters() -> list[dict]:
    out = []
    for rid, r in _registry().items():
        audio_dir = Path(r["audioDirectory"])
        entry = {
            "id": rid,
            "name": r["name"],
            "cachedAudioCount": len(list(audio_dir.glob("*.mp3"))) if audio_dir.exists() else 0,
        }
        if r.get("arabicName"):
            entry["arabicName"] = r["arabicName"]
        out.append(entry)
    return out


def get_reciter(id_: str) -> dict:
    if id_ not in _registry():
        raise ReciterError(f"Unknown reciter '{id_}'")
    return _registry()[id_]


def ayah_filename(surah: int, ayah: int) -> str:
    return f"{surah:03d}{ayah:03d}.mp3"


def local_audio_path(reciter_id: str, surah: int, ayah: int) -> Path:
    return RECITERS_DIR / reciter_id / ayah_filename(surah, ayah)


def download_ayah(reciter_id: str, surah: int, ayah: int) -> Path:
    """Download one verse file if missing. Returns local path."""
    dest = local_audio_path(reciter_id, surah, ayah)
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    rec = get_reciter(reciter_id)
    url = f"{rec['remoteUrl']}/{ayah_filename(surah, ayah)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise ReciterError(
            f"Could not download recitation audio for {surah}:{ayah} "
            f"(reciter {reciter_id}): {exc}"
        ) from exc
    if tmp.stat().st_size < 1024:
        tmp.unlink(missing_ok=True)
        raise ReciterError(f"Recitation audio for {surah}:{ayah} downloaded empty.")
    tmp.replace(dest)
    return dest
