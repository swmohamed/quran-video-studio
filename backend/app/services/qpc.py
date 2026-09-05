"""QCF V2 (Quran.com Madani) page fonts — ayah-end marker glyphs.

Quran.com renders each Mushaf page with a dedicated King Fahd Complex font
(p{N}-v2). Words on that page are PUA codepoints in `code_v2`; the verse-end
ornament is the word whose `char_type_name` is `end`. The number is already
drawn inside that glyph — it is not a separate digit overlay.

Fonts are downloaded on demand from the same CDN Quran.com documents
(https://quran.com-frontend-next docs/font-rendering-system.md) and cached
under fonts/qpc-v2/. Marker maps (page + codepoint only, never verse text)
are cached under data/qpc_v2/.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import freetype
import requests
from PIL import Image

from app.core.config import DATA_DIR, FONTS_DIR

QPC_FONT_DIR = FONTS_DIR / "qpc-v2"
QPC_META_DIR = DATA_DIR / "qpc_v2"
QPC_FONT_DIR.mkdir(parents=True, exist_ok=True)
QPC_META_DIR.mkdir(parents=True, exist_ok=True)

QURAN_API = "https://api.quran.com/api/v4"
FONT_URLS = (
    "https://static.qurancdn.com/fonts/quran/hafs/v2/ttf/p{page}.ttf",
    "https://verses.quran.foundation/fonts/quran/hafs/v2/ttf/p{page}.ttf",
)
UA = "QuranVideoStudio/1.0 (local QCF v2 ayah-end markers)"
_TTF_MAGICS = (b"\x00\x01\x00\x00", b"true", b"OTTO")

_font_lock = threading.Lock()
_meta_lock = threading.Lock()
_raster_lock = threading.Lock()


class QpcError(RuntimeError):
    pass


def font_family(page: int) -> str:
    return f"p{int(page)}-v2"


def font_path(page: int) -> Path:
    return QPC_FONT_DIR / f"p{int(page)}.ttf"


def _headers() -> dict[str, str]:
    return {"User-Agent": UA, "Accept": "*/*"}


def ensure_page_font(page: int) -> Path:
    """Download and cache the QCF v2 TTF for Mushaf page 1-604. Deduped."""
    page = int(page)
    if not 1 <= page <= 604:
        raise QpcError(f"Mushaf page must be 1-604, got {page}")
    dest = font_path(page)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    with _font_lock:
        if dest.exists() and dest.stat().st_size > 1000:
            return dest
        last_err: Exception | None = None
        tmp = dest.with_suffix(".tmp")
        for template in FONT_URLS:
            url = template.format(page=page)
            try:
                r = requests.get(url, headers=_headers(), timeout=60)
                r.raise_for_status()
                blob = r.content
                if len(blob) < 1000 or blob[:4] not in _TTF_MAGICS:
                    raise QpcError(f"not a TTF from {url}")
                tmp.write_bytes(blob)
                tmp.replace(dest)
                return dest
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
        raise QpcError(f"Could not download QCF v2 font for page {page}: {last_err}")


def _get_json(url: str) -> dict[str, Any]:
    r = requests.get(url, headers={**_headers(), "Accept": "application/json"}, timeout=45)
    r.raise_for_status()
    return r.json()


def _end_word(verse: dict[str, Any]) -> dict[str, Any] | None:
    for w in verse.get("words") or []:
        if w.get("char_type_name") == "end":
            return w
    return None


def _codepoint_from_code(code: str) -> int | None:
    for ch in reversed(code or ""):
        if not ch.isspace():
            return ord(ch)
    return None


def _fetch_surah_markers(surah: int) -> dict[str, dict[str, Any]]:
    ayahs: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        url = (
            f"{QURAN_API}/verses/by_chapter/{surah}"
            f"?words=true&word_fields=page_number,code_v2,char_type_name"
            f"&mushaf=1&per_page=50&page={page}"
        )
        data = _get_json(url)
        for v in data.get("verses") or []:
            ayah_n = int(v.get("verse_number") or 0)
            end = _end_word(v)
            raw = (end or {}).get("code_v2") or ""
            cp = _codepoint_from_code(raw)
            pg = int((end or {}).get("page_number") or v.get("page_number") or 0)
            if ayah_n and cp and 1 <= pg <= 604:
                ayahs[str(ayah_n)] = {"page": pg, "cp": f"{cp:04X}"}
        pag = data.get("pagination") or {}
        total = int(pag.get("total_pages") or 1)
        if page >= total:
            break
        page += 1
    if not ayahs:
        raise QpcError(f"No QCF v2 end-markers returned for surah {surah}")
    return ayahs


def _meta_path(surah: int) -> Path:
    return QPC_META_DIR / f"{int(surah):03d}.json"


def ensure_surah_markers(surah: int) -> dict[str, dict[str, Any]]:
    """Page + PUA codepoint for every ayah-end glyph in a surah."""
    surah = int(surah)
    path = _meta_path(surah)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        ayahs = data.get("ayahs") or {}
        if ayahs:
            return ayahs
    with _meta_lock:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            ayahs = data.get("ayahs") or {}
            if ayahs:
                return ayahs
        ayahs = _fetch_surah_markers(surah)
        payload = {
            "surah": surah,
            "source": "api.quran.com v4 mushaf=1 code_v2 char_type=end",
            "ayahs": ayahs,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return ayahs


def marker_for(surah: int, ayah: int) -> dict[str, Any] | None:
    """Return {page, cp, char, font} or None if mapping is unavailable."""
    try:
        ayahs = ensure_surah_markers(surah)
    except Exception:
        return None
    rec = ayahs.get(str(int(ayah)))
    if not rec:
        return None
    try:
        cp = int(str(rec["cp"]), 16)
        page = int(rec["page"])
    except (KeyError, ValueError, TypeError):
        return None
    if not (1 <= page <= 604) or cp <= 0:
        return None
    return {
        "page": page,
        "cp": f"{cp:04X}",
        "char": chr(cp),
        "font": font_family(page),
    }


def attach_markers(ayahs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy ayah dicts and add qpcMarker without touching cached verse text."""
    if not ayahs:
        return ayahs
    surah = int(ayahs[0].get("surah") or 0)
    mapping: dict[str, dict[str, Any]] = {}
    try:
        mapping = ensure_surah_markers(surah)
    except Exception:
        mapping = {}
    out: list[dict[str, Any]] = []
    for a in ayahs:
        rec = dict(a)
        info = None
        raw = mapping.get(str(int(rec.get("ayah") or 0)))
        if raw:
            try:
                cp = int(str(raw["cp"]), 16)
                page = int(raw["page"])
                info = {"page": page, "cp": f"{cp:04X}", "char": chr(cp), "font": font_family(page)}
            except (KeyError, ValueError, TypeError):
                info = None
        if info:
            rec["qpcMarker"] = info
        out.append(rec)
    return out


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@lru_cache(maxsize=8)
def _ft_face(path_str: str) -> freetype.Face:
    return freetype.Face(path_str)


@lru_cache(maxsize=256)
def glyph_advance(page: int, codepoint: int, font_size: float) -> float:
    """Inline width of a QCF end-glyph at CSS font-size.

    Chrome sizes the ornament at 1.42em but the inline box is the
    glyph advance, not a 1.42em square. Reserving the square shifted
    the whole RTL verse a few pixels left of Preview.
    """
    path = ensure_page_font(int(page))
    size = max(float(font_size), 4.0)
    with _raster_lock:
        face = _ft_face(str(path))
        gid = face.get_char_index(int(codepoint))
        if gid == 0:
            raise QpcError(f"page {page} has no glyph for U+{int(codepoint):04X}")
        face.set_char_size(int(round(size * 64)))
        face.load_glyph(gid, freetype.FT_LOAD_DEFAULT)
        return float(face.glyph.advance.x) / 64.0


def render_end_glyph(
    page: int, codepoint: int, font_size: float, color: str,
) -> tuple[Image.Image, int, int]:
    """Rasterize one QCF v2 ayah-end glyph at CSS font-size.

    Returns (patch, bitmap_left, bitmap_top) so the caller can sit the
    glyph on the same baseline as the verse — same as Preview's
    vertical-align: baseline. Never scales the ornament to fill a box.
    """
    path = ensure_page_font(page)
    with _raster_lock:
        face = _ft_face(str(path))
        gid = face.get_char_index(codepoint)
        if gid == 0:
            raise QpcError(f"page {page} has no glyph for U+{codepoint:04X}")

        rgb = _hex_rgb(color)
        face.set_char_size(int(round(max(float(font_size), 4.0) * 64)))
        flags = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_LIGHT
        face.load_glyph(gid, flags)
        slot = face.glyph
        bmp = slot.bitmap
        if not bmp.rows or not bmp.width or not bmp.buffer:
            raise QpcError(f"empty glyph U+{codepoint:04X} on page {page}")
        alpha = Image.frombytes("L", (bmp.width, bmp.rows), bytes(bmp.buffer))
        patch = Image.new("RGBA", alpha.size, (*rgb, 255))
        patch.putalpha(alpha)
        r, g, b, a = patch.split()
        a = a.point([int(round(min(255.0, ((i / 255.0) ** 0.88) * 255.0))) for i in range(256)])
        return Image.merge("RGBA", (r, g, b, a)), int(slot.bitmap_left), int(slot.bitmap_top)
