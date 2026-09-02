"""Full-surah audio mode: ONE continuous recording + exact verse timestamps.

Providers (timestamps always belong to the SAME recording as the audio):
  QDC — Quran Foundation chapter API (api.qurancdn.com/api/qdc), official
        verse_timings, ms. Config: reciters.json "qdcId".
  QUL — Quranic Universal Library (qul.tarteel.ai) gapless "Surah by Surah"
        recitations with word-level ayah segments, ms. Config: "qulId".

Range extraction is a single continuous slice [start of Ayah N, start of
Ayah M+1) — zero joins inside the range. Reciters with neither id fall
back to the verse-by-verse pipeline (caller's responsibility). Timestamps
are never guessed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from app.core.config import AUDIO_DIR

QDC_ENDPOINT = (
    "https://api.qurancdn.com/api/qdc/audio/reciters/{pid}/audio_files"
    "?chapter={surah}&segments=true"
)
QUL_ENDPOINT = (
    "https://qul.tarteel.ai/api/v1/audio/surah_segments/{pid}"
    "?surah={surah}&from=1&to=999&per_page=100"
)
SURAH_DIR = AUDIO_DIR / "surah"
TIMINGS_CACHE_DIR = Path(__file__).resolve().parents[2] / ".." / "data" / "qdc_timings"

_mem_cache: dict[tuple[str, int], dict] = {}


class SurahAudioError(RuntimeError):
    pass


def reciter_provider(rec: dict) -> tuple[str, int] | None:
    """('qdc'|'qul', provider_id) for a reciter config, or None."""
    if rec.get("qdcId"):
        return "qdc", int(rec["qdcId"])
    if rec.get("qulId"):
        return "qul", int(rec["qulId"])
    return None


def _timings_cache_path(provider: str, pid: int, surah: int) -> Path:
    d = TIMINGS_CACHE_DIR.resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{provider}{pid}_{surah:03d}.json"


def _fetch_qdc(pid: int, surah: int) -> dict[str, Any]:
    try:
        r = requests.get(QDC_ENDPOINT.format(pid=pid, surah=surah), timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise SurahAudioError(f"QDC API unreachable: {exc}") from exc
    files = data.get("audio_files") or []
    if not files:
        raise SurahAudioError(f"QDC returned no audio file for reciter {pid}, surah {surah}")
    af = files[0]
    vt = af.get("verse_timings") or []
    if len(vt) < 2:
        raise SurahAudioError(f"QDC has no verse timings for reciter {pid}, surah {surah}")
    timings = []
    for v in vt:
        _, ayah_s = v["verse_key"].split(":")  # "89:6"
        entry = {
            "ayah": int(ayah_s),
            "from_ms": int(v["timestamp_from"]),
            "to_ms": int(v["timestamp_to"]),
        }
        words = v.get("segments") or []
        if words:
            entry["word_from_ms"] = int(float(words[0][1]))
        timings.append(entry)
    timings.sort(key=lambda t: t["ayah"])
    return {"audio_url": af["audio_url"], "duration_ms": int(af["duration"]), "timings": timings}


def _fetch_qul(pid: int, surah: int) -> dict[str, Any]:
    """QUL gapless recitation: one full-surah file + word-level ayah segments."""
    try:
        r = requests.get(QUL_ENDPOINT.format(pid=pid, surah=surah), timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise SurahAudioError(f"QUL API unreachable: {exc}") from exc
    audio = data.get("audio") or {}
    url = audio.get("url")
    segments = data.get("segments") or {}
    if not url or not segments:
        raise SurahAudioError(f"QUL has no gapless segments for reciter {pid}, surah {surah}")
    timings = []
    for key, seg in segments.items():
        _, ayah_s = key.split(":")  # "89:1"
        entry = {
            "ayah": int(ayah_s),
            "from_ms": int(seg["time_from"]),
            "to_ms": int(seg["time_to"]),
        }
        words = seg.get("segments") or []
        if words:
            entry["word_from_ms"] = int(words[0][1])
        timings.append(entry)
    timings.sort(key=lambda t: t["ayah"])
    if len(timings) < 2:
        raise SurahAudioError(f"QUL returned too few ayah segments for reciter {pid}, surah {surah}")
    duration_ms = int(float(audio.get("duration") or 0) * 1000)
    return {"audio_url": url, "duration_ms": duration_ms, "timings": timings}


_FETCHERS = {"qdc": _fetch_qdc, "qul": _fetch_qul}


def fetch_timings(provider: str, pid: int, surah: int) -> dict[str, Any]:
    """{audio_url, duration_ms, timings: [{ayah, from_ms, to_ms}]} for the recording."""
    key = (provider, surah)
    if key in _mem_cache and _mem_cache[key].get("_pid") == pid:
        return _mem_cache[key]

    cache_file = _timings_cache_path(provider, pid, surah)
    if cache_file.exists():
        info = json.loads(cache_file.read_text(encoding="utf-8"))
        if info.get("timings"):
            info["_pid"] = pid
            _mem_cache[key] = info
            return info

    info = _FETCHERS[provider](pid, surah)
    try:
        cache_file.write_text(json.dumps(info), encoding="utf-8")
    except OSError:
        pass
    info["_pid"] = pid
    _mem_cache[key] = info
    return info


def surah_path(reciter_id: str, surah: int) -> Path:
    return SURAH_DIR / reciter_id / f"{surah:03d}.mp3"


def ensure_surah(reciter_id: str, provider_cfg: tuple[str, int], surah: int) -> tuple[Path, dict]:
    """Download the continuous surah file if missing. Returns (path, info)."""
    provider, pid = provider_cfg
    info = fetch_timings(provider, pid, surah)
    dest = surah_path(reciter_id, surah)
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest, info
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        with requests.get(info["audio_url"], stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise SurahAudioError(f"Could not download surah audio: {exc}") from exc
    if tmp.stat().st_size < 50_000:
        tmp.unlink(missing_ok=True)
        raise SurahAudioError("Surah audio download came back empty.")
    tmp.replace(dest)
    return dest, info


def range_bounds(
    from_ayah: int, to_ayah: int, ayah_count: int, info: dict, file_duration_s: float | None = None,
    use_word: bool = False,
) -> tuple[float, float, list[tuple[int, float]]]:
    """(start_s, end_s, [(ayah, relative_start_s)]).

    start = start of Ayah N; end = start of Ayah M+1, or the end of
    the recording when M is the final ayah.
    Boundary time = first-WORD start when use_word (PCM-verified reciters
    whose verse_from includes leading pad); otherwise verse_from.
    """
    timings = {t["ayah"]: t for t in info["timings"]}

    def start_of(t: dict) -> int:
        if use_word and "word_from_ms" in t:
            return t["word_from_ms"]
        return t["from_ms"]

    if from_ayah not in timings:
        raise SurahAudioError(f"No timestamp for ayah {from_ayah}")
    start_ms = start_of(timings[from_ayah])
    if to_ayah < ayah_count:
        nxt = to_ayah + 1
        if nxt not in timings:
            raise SurahAudioError(f"No timestamp for ayah {nxt}")
        end_ms = start_of(timings[nxt])
    else:
        end_ms = info["duration_ms"]
        if file_duration_s:
            end_ms = int(file_duration_s * 1000)

    bounds = []
    for ayah in range(from_ayah, to_ayah + 1):
        if ayah not in timings:
            raise SurahAudioError(f"No timestamp for ayah {ayah}")
        bounds.append((ayah, (start_of(timings[ayah]) - start_ms) / 1000.0))
    return start_ms / 1000.0, end_ms / 1000.0, bounds
