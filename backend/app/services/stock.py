"""Online background library — Pexels & Pixabay official APIs only.

Search returns normalized results; Download & Use pulls the media file
through the backend into the LOCAL background library (validated with
ffprobe), exactly like an upload. No scraping.

API keys: set PEXELS_API_KEY / PIXABAY_API_KEY environment variables, or
fill data/stock_keys.json {"pexels": "...", "pixabay": "..."}.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.config import BACKGROUNDS_DIR, DATA_DIR, MAX_UPLOAD_BYTES
from app.core.ffmpeg import tools
from app.services.backgrounds import _entry, set_display_name
from app.services.stock_smart import (
    expand_video_queries,
    resolution_score,
    suitability_bucket,
    tags_from_pexels_video,
)

PEXELS_KEY_ENV = "PEXELS_API_KEY"
PIXABAY_KEY_ENV = "PIXABAY_API_KEY"
KEYS_FILE = DATA_DIR / "stock_keys.json"

# only media CDNs of the two providers may be downloaded from
ALLOWED_HOSTS = {
    "images.pexels.com", "videos.pexels.com", "player.vimeo.com",
    "cdn.pixabay.com", "pixabay.com", "www.pixabay.com",
}


class StockError(RuntimeError):
    pass


def _keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    try:
        keys.update(json.loads(KEYS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return {
        "pexels": os.environ.get(PEXELS_KEY_ENV) or keys.get("pexels") or "",
        "pixabay": os.environ.get(PIXABAY_KEY_ENV) or keys.get("pixabay") or "",
    }


def ensure_keys_template() -> None:
    """Create an empty template once so the user knows where to put keys."""
    if not KEYS_FILE.exists():
        try:
            KEYS_FILE.write_text(
                json.dumps({"pexels": "", "pixabay": ""}, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


def provider_available(provider: str) -> bool:
    return bool(_keys().get(provider))


def _orientation_param(orientation: str | None, provider: str) -> str | None:
    """Map our orientation hint to the provider's search parameter."""
    if not orientation:
        return None
    if provider == "pexels":
        # Pexels accepts portrait / landscape / square
        return orientation if orientation in ("portrait", "landscape", "square") else "portrait"
    # Pixabay images: orientation=horizontal|vertical|all
    if orientation == "landscape":
        return "horizontal"
    if orientation in ("portrait", "square"):
        return "vertical"
    return None


def classify_orientation(width: int | None, height: int | None) -> str | None:
    """portrait / landscape / square from pixel size. None if unknown."""
    if not width or not height:
        return None
    ratio = width / height
    if ratio >= 1.15:
        return "landscape"
    if ratio <= 0.87:
        return "portrait"
    return "square"


def _annotate_item(item: dict[str, Any]) -> dict[str, Any]:
    if not item.get("orientation"):
        item["orientation"] = classify_orientation(item.get("width"), item.get("height"))
    return item


def rank_stock_items(
    items: list[dict[str, Any]],
    audio_duration: float | None = None,
    target_orientation: str | None = None,
    user_query: str | None = None,
) -> list[dict[str, Any]]:
    """Rank stock results for the current recitation.

    Videos: Quran-background suitability first, then duration >= audio
    (closest first; shorter clips are fallbacks), then orientation, then
    resolution. Other orientations are kept, not dropped.
    """
    want_dur = bool(audio_duration and audio_duration > 0)
    target = target_orientation if target_orientation in ("portrait", "landscape", "square") else None
    q = user_query or ""

    for item in items:
        if item.get("kind") == "video" and item.get("suitScore") is None:
            item["suitScore"] = suitability_bucket(item, q)

    def sort_key(item: dict[str, Any]) -> tuple:
        suit = item.get("suitScore")
        if not isinstance(suit, int):
            suit = 1
        dur = item.get("duration")
        kind = item.get("kind")
        if want_dur and kind == "video":
            if isinstance(dur, (int, float)) and dur > 0:
                if dur + 1.0 >= float(audio_duration):
                    dur_bucket = 0  # long enough
                    dur_delta = abs(float(dur) - float(audio_duration))
                else:
                    dur_bucket = 1  # too short — fallback
                    dur_delta = float(audio_duration) - float(dur)
            else:
                dur_bucket = 2
                dur_delta = 0.0
        else:
            dur_bucket = 0
            dur_delta = 0.0

        orient = item.get("orientation") or classify_orientation(item.get("width"), item.get("height"))
        if target and orient:
            orient_bucket = 0 if orient == target else 1
        else:
            orient_bucket = 0
        # Higher resolution first (negative so it sorts ascending).
        return (suit, dur_bucket, dur_delta, orient_bucket, -resolution_score(item))

    return sorted(items, key=sort_key)


def search(provider: str, query: str, orientation: str | None = None,
           kind: str = "image", per_page: int = 24,
           audio_duration: float | None = None) -> list[dict[str, Any]]:
    """Search one provider. kind: image | video. Returns normalized items:
    {provider, id, kind, thumb, preview, url, width, height, author, name,
     duration, orientation}."""
    keys = _keys()
    key = keys.get(provider)
    if not key:
        raise StockError(
            f"{provider.title()} API key is not configured. "
            f"Set {PEXELS_KEY_ENV if provider == 'pexels' else PIXABAY_KEY_ENV} "
            f"or fill data/stock_keys.json."
        )
    q = (query or "").strip()
    if not q:
        return []
    target_orient = orientation if orientation in ("portrait", "landscape", "square") else None
    orient = _orientation_param(orientation, provider)
    fetch_n = per_page
    if kind == "video" and audio_duration:
        fetch_n = max(per_page, 40)

    try:
        if kind == "video":
            items = _search_videos_smart(provider, key, q, orient, fetch_n)
        elif provider == "pexels":
            items = _search_pexels(key, q, orient, kind, fetch_n)
        elif provider == "pixabay":
            items = _search_pixabay(key, q, orient, kind, fetch_n)
        else:
            raise StockError(f"Unknown provider '{provider}'")
    except requests.RequestException as exc:
        raise StockError(f"{provider.title()} request failed: {exc}") from exc

    for it in items:
        _annotate_item(it)
        if kind == "video":
            it["suitScore"] = suitability_bucket(it, q)
    return rank_stock_items(items, audio_duration, target_orient, user_query=q)


def _search_one(provider: str, key: str, q: str, orient: str | None,
                kind: str, per_page: int) -> list[dict[str, Any]]:
    if provider == "pexels":
        return _search_pexels(key, q, orient, kind, per_page)
    if provider == "pixabay":
        return _search_pixabay(key, q, orient, kind, per_page)
    raise StockError(f"Unknown provider '{provider}'")


def _query_page_sizes(n: int, total: int) -> list[int]:
    """Split a small result budget across a few query variations."""
    if n <= 1:
        return [total]
    first = max(12, min(20, total // 2 + 4))
    rest = max(8, min(15, max(total - first, 8 * (n - 1)) // (n - 1)))
    return [first] + [rest] * (n - 1)


def _search_videos_smart(provider: str, key: str, query: str,
                         orient: str | None, fetch_n: int) -> list[dict[str, Any]]:
    """Search one provider with the exact query plus a few Smart Search variants.

    Combines hits, drops duplicate provider+id, and keeps the first occurrence
    (exact query first).
    """
    queries = expand_video_queries(query)
    if not queries:
        return []
    pages = _query_page_sizes(len(queries), fetch_n)
    grouped: dict[str, list[dict[str, Any]]] = {q: [] for q in queries}
    errors: list[Exception] = []

    def run(q: str, per_page: int) -> tuple[str, list[dict[str, Any]]]:
        return q, _search_one(provider, key, q, orient, "video", per_page)

    with ThreadPoolExecutor(max_workers=min(3, len(queries))) as pool:
        futs = [pool.submit(run, q, pages[i]) for i, q in enumerate(queries)]
        for fut in as_completed(futs):
            try:
                q, batch = fut.result()
                grouped[q] = batch
            except Exception as exc:
                errors.append(exc)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for q in queries:
        for it in grouped.get(q) or []:
            ident = (str(it.get("provider") or provider), str(it.get("id") or ""))
            if ident in seen:
                continue
            seen.add(ident)
            merged.append(it)
    if not merged and errors:
        raise StockError(f"{provider.title()} request failed: {errors[0]}") from errors[0]
    return merged


def _search_pexels(key: str, q: str, orient: str | None, kind: str,
                   per_page: int) -> list[dict[str, Any]]:
    headers = {"Authorization": key}
    if kind == "video":
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": q, "per_page": per_page, **({"orientation": orient} if orient else {})},
            headers=headers, timeout=30,
        )
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"]
            if not files:
                continue
            # Highest-resolution MP4 for Download & Use — never a 720p stand-in
            # that later gets upscaled into the 1080×1920 export.
            src = max(files, key=lambda f: (f.get("width", 0) * f.get("height", 0)))
            out.append({
                "provider": "pexels", "id": str(v["id"]), "kind": "video",
                "thumb": v.get("image"),
                "preview": v.get("image"),
                "url": src["link"],
                "width": src.get("width"), "height": src.get("height"),
                "duration": v.get("duration"),
                "orientation": classify_orientation(src.get("width"), src.get("height")),
                "author": v.get("user", {}).get("name", ""),
                "name": f"Pexels video {v['id']}",
                "tags": tags_from_pexels_video(v),
            })
        return out
    r = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": q, "per_page": per_page, **({"orientation": orient} if orient else {})},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    out = []
    for p in r.json().get("photos", []):
        src = p.get("src", {})
        out.append({
            "provider": "pexels", "id": str(p["id"]), "kind": "image",
            "thumb": src.get("medium") or src.get("small"),
            "preview": src.get("large2x") or src.get("large"),
            "url": src.get("large2x") or src.get("original"),
            "width": p.get("width"), "height": p.get("height"),
            "duration": None,
            "orientation": classify_orientation(p.get("width"), p.get("height")),
            "author": p.get("photographer", ""),
            "name": f"Pexels {p['id']}",
        })
    return out


def _pixabay_video_still(videos: dict[str, Any] | None) -> str | None:
    """JPEG still for a Pixabay video result card.

    Current Pixabay video hits expose `videos.{size}.thumbnail` (cdn.pixabay.com
    JPEG). They no longer send `picture_id`, so the old YouTube still URL is
    always empty/broken. Prefer medium, then large — those match the card.
    """
    if not isinstance(videos, dict):
        return None
    for size in ("medium", "large", "small", "tiny"):
        fmt = videos.get(size) or {}
        if not isinstance(fmt, dict):
            continue
        url = fmt.get("thumbnail")
        if not isinstance(url, str):
            continue
        still = url.strip()
        if still.startswith(("https://", "http://")):
            return still
        if still.startswith("//") and "." in still:
            return "https:" + still
    return None


def _search_pixabay(key: str, q: str, orient: str | None, kind: str,
                    per_page: int) -> list[dict[str, Any]]:
    if kind == "video":
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": q, "per_page": min(per_page, 30), "safesearch": "true"},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        out = []
        for v in d.get("hits", []):
            videos = v.get("videos") or {}
            formats = videos.get("large") or videos.get("medium")
            if not formats:
                continue
            still = _pixabay_video_still(videos)
            width = formats.get("width") or 0
            height = formats.get("height") or 0
            if not width or not height:
                for size in ("large", "medium", "small", "tiny"):
                    fmt = videos.get(size) or {}
                    if isinstance(fmt, dict) and fmt.get("width") and fmt.get("height"):
                        width, height = fmt.get("width"), fmt.get("height")
                        break
            out.append({
                "provider": "pixabay", "id": str(v["id"]), "kind": "video",
                "thumb": still,
                "preview": still,
                "url": formats.get("url"),
                "width": width or None, "height": height or None,
                "duration": v.get("duration"),
                "orientation": classify_orientation(width, height),
                "author": v.get("user", ""),
                "name": f"Pixabay video {v['id']}",
                "tags": v.get("tags") or "",
            })
        return out
    r = requests.get(
        "https://pixabay.com/api/",
        params={"key": key, "q": q, "per_page": min(per_page, 100),
                "safesearch": "true", "image_type": "photo",
                **({"orientation": orient} if orient else {})},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        out.append({
            "provider": "pixabay", "id": str(h["id"]), "kind": "image",
            "thumb": h.get("webformatURL"),
            "preview": h.get("webformatURL"),
            "url": h.get("largeImageURL") or h.get("webformatURL"),
            "width": h.get("imageWidth"), "height": h.get("imageHeight"),
            "duration": None,
            "orientation": classify_orientation(h.get("imageWidth"), h.get("imageHeight")),
            "author": h.get("user", ""),
            "name": f"Pixabay {h['id']}",
        })
    return out


def _validate_download_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise StockError(f"Refusing to download from untrusted host '{host}'.")


def download(provider: str, item_id: str, url: str, kind: str,
             name: str | None = None) -> dict[str, Any]:
    """Download a stock media file into the LOCAL library and validate it
    with ffprobe. Returns the new library entry."""
    _validate_download_url(url)
    ext = ".mp4" if kind == "video" else _img_ext(url)
    stem = f"stock-{provider}-{item_id}"
    dest = BACKGROUNDS_DIR / f"{stem}{ext}"
    if dest.exists():
        return _entry(dest, uploaded=False)  # already in the library

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=180,
                          headers={"User-Agent": "QuranVideoStudio/1.0"}) as r:
            r.raise_for_status()
            size = 0
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise StockError("Stock file exceeds the 200 MB limit.")
                    fh.write(chunk)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise StockError(f"Download failed: {exc}") from exc
    if size < 1024:
        tmp.unlink(missing_ok=True)
        raise StockError("Downloaded file is empty.")
    # validate as real media via ffprobe (same gate as uploads)
    try:
        info = tools.probe_json(tmp)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
            raise StockError("no video stream")
    except StockError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise StockError("Downloaded file is not valid media (ffprobe rejected it).") from exc
    tmp.replace(dest)
    if name:
        set_display_name(dest.stem, name)
    entry = _entry(dest, uploaded=False)
    return entry


def _img_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".png"):
        return ".png"
    if path.endswith((".jpeg", ".jpg")):
        return ".jpg"
    return ".jpg"
