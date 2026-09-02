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
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.core.config import BACKGROUNDS_DIR, DATA_DIR, MAX_UPLOAD_BYTES
from app.core.ffmpeg import tools
from app.services.backgrounds import _entry, set_display_name

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


def search(provider: str, query: str, orientation: str | None = None,
           kind: str = "image", per_page: int = 24) -> list[dict[str, Any]]:
    """Search one provider. kind: image | video. Returns normalized items:
    {provider, id, kind, thumb, preview, url, width, height, author, name}."""
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
    orient = _orientation_param(orientation, provider)

    try:
        if provider == "pexels":
            return _search_pexels(key, q, orient, kind, per_page)
        if provider == "pixabay":
            return _search_pixabay(key, q, orient, kind, per_page)
    except requests.RequestException as exc:
        raise StockError(f"{provider.title()} request failed: {exc}") from exc
    raise StockError(f"Unknown provider '{provider}'")


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
            best = max(files, key=lambda f: (f.get("width", 0) * f.get("height", 0)))
            small = min(
                (f for f in files if f.get("width", 0) >= 720 and f.get("width", 0) <= 1280),
                key=lambda f: f.get("width", 0), default=None,
            )
            src = small or best
            out.append({
                "provider": "pexels", "id": str(v["id"]), "kind": "video",
                "thumb": v.get("image"),
                "preview": v.get("image"),
                "url": src["link"],
                "width": src.get("width"), "height": src.get("height"),
                "author": v.get("user", {}).get("name", ""),
                "name": f"Pexels video {v['id']}",
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
            "author": p.get("photographer", ""),
            "name": f"Pexels {p['id']}",
        })
    return out


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
            formats = (v.get("videos") or {}).get("large") or (v.get("videos") or {}).get("medium")
            if not formats:
                continue
            out.append({
                "provider": "pixabay", "id": str(v["id"]), "kind": "video",
                "thumb": v.get("picture_id") and f"https://i.ytimg.com/vi/{v['picture_id']}/hqdefault.jpg",
                "preview": v.get("pageURL"),
                "url": formats.get("url"),
                "width": formats.get("width"), "height": formats.get("height"),
                "author": v.get("user", ""),
                "name": f"Pixabay video {v['id']}",
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
