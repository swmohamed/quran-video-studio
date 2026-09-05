"""Composition rendering — persistent layers + text-only ayah overlays.

Architecture (professional-editor model):
  - ONE persistent frame for the whole video: Surah header + translucent
    card. It never fades, never resets, never disappears.
  - ONE text overlay per ayah containing ONLY the changing content
    (Arabic verse, ayah reference, translation) on transparency. These
    cross-fade subtly (120ms) at audio boundaries.
  - Layout (card geometry + font sizes) is computed ONCE for the whole
    selection so typography is identical across ayahs — only text content
    changes, never size or position of the container.

Responsive composition: the design is authored at 1080×1920. Every other
output format uses a uniform scale from composition_scale() so type, marker,
header, padding and gaps grow or shrink together without stretching.
Text is rasterized at the overlay pixel size (native output, or 2× with
lanczos downscale in FFmpeg) — never drawn small and then enlarged.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from app.core.config import FONTS_DIR
from app.models.schemas import TextSettings
from app.renderer.shaping import TextBlockSpec, render_text_block, ink_halo
from app.services import fonts as fontsvc
from app.services import qpc as qpcsvc
from app.services.quran import get_surah

DESIGN_W = 1080
DESIGN_H = 1920
GAP_AR_TR = 32
INLINE_PAD = 4  # Preview: padding-inline 4px on the verse and translation
MAX_CARD_HEIGHT_PCT = 0.68
MIN_ARABIC = 42
MIN_TRANSLATION = 26
HEADER_EN_RATIO = 30 / 64  # English header vs Arabic header at the design size
# Preview: letterSpacing 0.08em, fontWeight 500 on Inter English header
HEADER_EN_TRACKING = 0.08
HEADER_EN_WEIGHT = 500

# Ayah-end marker: QCF v2 page font glyph (Quran.com p{N}-v2 / code_v2 end
# word). The number is part of that glyph. Noto U+06DD is only a fallback
# when the page font or mapping cannot be loaded.
MARKER_FONT = FONTS_DIR / "NotoNaskhArabic.ttf"
# CSS: .qvs-ayah-marker-qpc { font-size: 1.42em } + margin-inline-start: 0.12em
# Fallback .qvs-ayah-marker is 1.12em. Inline width is the glyph advance.
MARKER_BOX = 1.42
MARKER_FALLBACK = 1.12
MARKER_GAP = 0.12

_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def composition_scale(width: int, height: int) -> float:
    """Uniform typography scale from the 1080×1920 design. Never stretches.

    True 9:16 (and taller): exact design fit.
    Shorter canvases (4:5, 1:1, 16:9): height-fit letterbox leaves unused
    card space — lift toward the short-edge identity so type stays readable,
    still smaller than on the vertical original, still uniform.
    """
    sx = width / DESIGN_W
    sy = height / DESIGN_H
    uniform = min(sx, sy)
    design_aspect = DESIGN_H / DESIGN_W
    if height / max(width, 1) >= design_aspect * 0.98:
        return uniform
    short = min(width, height) / 1080.0
    lifted = uniform + 0.45 * (short - uniform)
    return min(short, lifted)


def text_supersample(resolution: str, arabic_size: float) -> int:
    """Internal raster scale only. Visible design size stays `arabic_size`.

    FHD/UHD rasterize at native output size — same as the 1080×1920
    browser Preview. Lanczos-downsampling a 3× overlay was softening
    diacritics compared with Chrome. LIGHT (540-class) still supersamples
    because those glyphs are actually small.
    """
    if resolution != "light":
        return 1
    size = float(arabic_size or 0)
    if size <= 50:
        return 4
    if size <= 68:
        return 3
    return 2


def arabic_indic(n: int) -> str:
    return str(n).translate(_ARABIC_INDIC)


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _header_ar_size(ts: TextSettings, scale: float) -> float:
    return float(getattr(ts.header, "size", 64) or 64) * scale


def _header_en_size(ts: TextSettings, scale: float) -> float:
    return max(14.0 * scale, _header_ar_size(ts, scale) * HEADER_EN_RATIO)


def _header_gap(ts: TextSettings, scale: float) -> int:
    return int(round(float(getattr(ts.header, "gap", 18) or 18) * scale))


def _header_line_height(ts: TextSettings) -> float:
    return max(0.0, min(5.0, float(getattr(ts.header, "lineHeight", 1.2) or 0.0)))


def _outline_on(ts: TextSettings) -> bool:
    return bool(getattr(ts, "outline", False))


def _spec_layout_h(spec, img: Image.Image) -> int:
    h = getattr(spec, "layout_height", 0) if spec is not None else 0
    return int(h) if h else img.height


def _spec_crop_top(spec) -> int:
    return int(getattr(spec, "crop_top", 0) or 0) if spec is not None else 0


def _spec_crop_left(spec) -> int:
    return int(getattr(spec, "crop_left", 0) or 0) if spec is not None else 0


def _place_x(canvas_w: int, spec, img: Image.Image, scale: float) -> int:
    """Center the CSS inline box, then offset by left overflow + padding-inline."""
    pad = int(round(INLINE_PAD * scale))
    lw = int(getattr(spec, "layout_width", 0) or 0) if spec is not None else 0
    if lw <= 0:
        lw = img.width
    return (canvas_w - (lw + 2 * pad)) // 2 + pad - _spec_crop_left(spec)


def _user_offset(ts_layer: Any, width: int, height: int) -> tuple[int, int]:
    ox = float(getattr(ts_layer, "offsetX", 0) or 0)
    oy = float(getattr(ts_layer, "offsetY", 0) or 0)
    return int(round(width * ox / 100.0)), int(round(height * oy / 100.0))


def _block(text: str, font_path: Path, size: float, color: str, max_w: int, line_h: float,
           rtl: bool, opacity: int = 255, tail_width: float = 0.0, tail_gap: float = 0.0,
           outline: bool = False, spec_out: list | None = None,
           weight: int | None = None, letter_spacing: float = 0.0) -> Image.Image:
    spec = TextBlockSpec(
        text=text, font_path=font_path, size=size, color=color,
        max_width=max_w, line_height=line_h,
        direction="rtl" if rtl else "ltr",
        script="Arab" if rtl else "Latn",
        language="ar" if rtl else "en",
        weight=weight,
        opacity=opacity,
        tail_width=tail_width, tail_gap=tail_gap,
        outline=outline,
        letter_spacing=letter_spacing,
    )
    img = render_text_block(spec)
    if spec_out is not None:
        spec_out.append(spec)
    return img


def _marker_slot(surah: int | None, number: int | None, ar_size: float) -> tuple[float, float, float]:
    """Return (font_size, inline_advance, gap) matching Preview CSS.

    The QCF ornament is painted at 1.42em. The reserved inline box is the
    glyph advance (~0.88em here), not a 1.42em square. Using the square
    as tail width shifted the RTL verse left of Chrome.
    """
    # margin-inline-start: 0.12em is on the marker, so em = marker font-size.
    if surah and number:
        info = qpcsvc.marker_for(int(surah), int(number))
        if info:
            font_size = MARKER_BOX * ar_size
            gap = MARKER_GAP * font_size
            try:
                adv = qpcsvc.glyph_advance(int(info["page"]), ord(info["char"]), font_size)
                return font_size, max(4.0, float(adv)), gap
            except Exception:
                return font_size, font_size, gap
    font_size = MARKER_FALLBACK * ar_size
    return font_size, font_size, MARKER_GAP * font_size


def draw_ayah_marker(img: Image.Image, box: tuple[int, int, int, int],
                     number: int, color: str, num_font_path: Path,
                     surah: int | None = None, outline: bool = False,
                     baseline: int | None = None,
                     font_size: float | None = None) -> None:
    """Draw the Quranic verse-end ornament into `box`.

    Matches Preview: QCF glyph at 1.42em, baseline-aligned, not scaled to
    fill the reserved slot. Falls back to Noto U+06DD + Arabic-Indic digits.
    """
    x, y, w, h = box
    size = float(font_size) if font_size else float(w)
    if size < 4:
        return
    glyph: Image.Image | None = None
    bearing_left = 0
    bearing_top = 0
    if surah:
        info = qpcsvc.marker_for(int(surah), int(number))
        if info:
            try:
                glyph, bearing_left, bearing_top = qpcsvc.render_end_glyph(
                    int(info["page"]), ord(info["char"]), size, color,
                )
            except Exception:
                glyph = None
    if glyph is None:
        font = MARKER_FONT if MARKER_FONT.exists() else num_font_path
        try:
            glyph = _block(
                "\u06DD" + arabic_indic(number), font, size, color,
                max(int(size * 4), w + 8), 1.0, rtl=True, outline=outline,
            )
            bearing_left = max(0, (max(w, 1) - glyph.width) // 2)
            bearing_top = glyph.height
        except Exception:
            return
    if baseline is None:
        baseline = y + int(round((h if h > 0 else max(w, size)) * 0.8))
    px = x + int(bearing_left)
    py = int(baseline) - int(bearing_top)
    if outline:
        glyph = ink_halo(glyph, max(1, int(round(size * 0.04))))
    img.alpha_composite(glyph, (px, py))


@dataclass
class Layout:
    """Fixed geometry shared by the persistent frame and every ayah overlay."""
    card_left: int
    card_top: int
    card_w: int
    card_h: int
    inner_top: int
    inner_h: int
    ar_size: float
    tr_size: float
    header_bottom: int


def _header_top(ts: TextSettings, height: int) -> int:
    """Header top position: user-controlled % of canvas height."""
    return max(24, int(height * ts.header.topPct / 100))


def compute_layout(
    surah: int,
    ayat: list[dict[str, Any]],
    translation_for: Callable[[dict[str, Any]], str | None],
    ts: TextSettings,
    width: int,
    height: int,
    scale: float = 1.0,
) -> Layout:
    """Worst-fit auto-size: one typography for all ayahs, card tall enough
    for the longest verse, position clamped below the header. Geometry and
    type sizes follow the 1080×1920 design via `scale` (see composition_scale)."""
    card = ts.card
    ar = ts.arabic
    tr = ts.translation

    # Card width: percentage of canvas width, but on wide canvases (landscape)
    # capped so text lines keep a comfortable reading width.
    card_w = int(width * card.widthPct / 100)
    if width > height:  # landscape: cap card width against the short edge
        card_w = min(card_w, int(height * 1.15))
    pad = int(card.padding * scale)
    inner_w = card_w - 2 * pad - 2 * int(round(INLINE_PAD * scale))

    header_top = _header_top(ts, height)
    header_bottom = header_top
    if ts.header.show:
        y = header_top
        gap = _header_gap(ts, scale)
        if ts.header.showArabic:
            y += int(_header_ar_size(ts, scale) * _header_line_height(ts)) + gap
        if ts.header.showEnglish:
            y += int(_header_en_size(ts, scale) * _header_line_height(ts)) + int(8 * scale)
        header_bottom = y

    min_top = header_bottom + int(36 * scale) if ts.header.show else int(48 * scale)
    max_card_h = int(height * MAX_CARD_HEIGHT_PCT)

    # User-selected sizes are the source of truth. composition_scale() maps
    # the 1080×1920 design onto the output canvas; it does not grow type.
    ar_size = float(ar.size) * scale
    tr_size = float(tr.size) * scale
    min_ar = min(MIN_ARABIC * scale, ar_size)
    min_tr = min(MIN_TRANSLATION * scale, tr_size)
    while True:
        worst = 0.0
        for a in ayat:
            h = _measure_height(a, translation_for(a), ts, ar_size, tr_size, inner_w, scale)
            worst = max(worst, h)
        total_h = worst + 2 * pad if card.visible else worst + int(24 * scale)
        if total_h <= max_card_h or (ar_size <= min_ar and tr_size <= min_tr):
            break
        if ar_size > min_ar:
            ar_size = max(min_ar, ar_size - 4 * scale)
        if tr_size > min_tr:
            tr_size = max(min_tr, tr_size - 2 * scale)
        if ar_size <= min_ar and tr_size <= min_tr:
            break

    card_h = int(round(total_h))
    card_top = int(round(height * card.positionPct / 100 - card_h / 2))
    card_top = max(card_top, min_top)
    card_top = min(card_top, height - card_h - int(40 * scale))

    return Layout(
        card_left=(width - card_w) // 2,
        card_top=card_top,
        card_w=card_w,
        card_h=card_h,
        inner_top=card_top + (pad if card.visible else int(12 * scale)),
        inner_h=max(1, card_h - 2 * (pad if card.visible else int(12 * scale))),
        ar_size=ar_size,
        tr_size=tr_size,
        header_bottom=header_bottom,
    )


def _measure_height(
    ayah_rec: dict[str, Any],
    translation_text: str | None,
    ts: TextSettings,
    ar_size: float,
    tr_size: float,
    inner_w: int,
    scale: float = 1.0,
) -> float:
    # Arabic line count via aspect estimate: shaped width ≈ size * 0.52 per char
    # is unreliable for Arabic; use the real shaper (fast enough at layout time).
    if ts.showAyahNumber:
        _fs, tail, gap = _marker_slot(ayah_rec.get("surah"), ayah_rec.get("ayah"), ar_size)
    else:
        tail = gap = 0.0
    specs: list = []
    ar_img = _block(
        ayah_rec["arabic"], fontsvc.font_path(ts.arabic.font, "arabic"), ar_size,
        ts.arabic.color, inner_w, ts.arabic.lineHeight, rtl=True,
        tail_width=tail, tail_gap=gap, outline=_outline_on(ts), spec_out=specs,
    )
    h = float(_spec_layout_h(specs[0] if specs else None, ar_img))
    if translation_text:
        tspecs: list = []
        t_img = _block(
            translation_text, fontsvc.font_path(ts.translation.font, "latin"), tr_size,
            ts.translation.color, inner_w, ts.translation.lineHeight, rtl=False,
            outline=_outline_on(ts), spec_out=tspecs,
        )
        h += GAP_AR_TR * scale + _spec_layout_h(tspecs[0] if tspecs else None, t_img)
    return h


def render_persistent_frame(surah: int, ts: TextSettings, layout: Layout,
                            width: int, height: int, scale: float = 1.0) -> Image.Image:
    """Header + card — composited over the background for the ENTIRE video."""
    meta = get_surah(surah)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # header
    if ts.header.show:
        y = _header_top(ts, height)
        gap = _header_gap(ts, scale)
        ink = getattr(ts.header, "color", None) or "#f5f1e8"
        hlh = _header_line_height(ts)
        if ts.header.showArabic:
            specs: list = []
            b = _block(meta["arabicName"], FONTS_DIR / "Amiri-Bold.ttf", _header_ar_size(ts, scale),
                       ink, width - int(160 * scale), hlh, rtl=True, outline=_outline_on(ts),
                       spec_out=specs)
            sp = specs[0] if specs else None
            canvas.alpha_composite(b, ((width - b.width) // 2, y - _spec_crop_top(sp)))
            y += _spec_layout_h(sp, b) + gap
        if ts.header.showEnglish:
            specs = []
            en_size = _header_en_size(ts, scale)
            b = _block(meta["englishName"].upper(), FONTS_DIR / "Inter.ttf", en_size,
                       ink, width - int(200 * scale), hlh, rtl=False, outline=_outline_on(ts),
                       spec_out=specs, weight=HEADER_EN_WEIGHT,
                       letter_spacing=HEADER_EN_TRACKING * en_size)
            sp = specs[0] if specs else None
            canvas.alpha_composite(b, ((width - b.width) // 2, y - _spec_crop_top(sp)))

    # card
    card = ts.card
    if card.visible and card.opacity > 0:
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        rgb = _hex_rgb(card.color)
        alpha = int(255 * card.opacity / 100)
        box = (layout.card_left, layout.card_top,
               layout.card_left + layout.card_w, layout.card_top + layout.card_h)
        d.rounded_rectangle(
            box, radius=int(card.radius * scale), fill=(rgb[0], rgb[1], rgb[2], alpha),
            outline=_hex_rgb(card.borderColor) + (255,) if card.borderWidth else None,
            width=int(card.borderWidth * scale) or 1 if card.borderWidth else 0,
        )
        canvas.alpha_composite(overlay)

    return canvas


def render_ayah_overlay(
    ayah_rec: dict[str, Any],
    translation_text: str | None,
    ts: TextSettings,
    layout: Layout,
    width: int,
    height: int,
    scale: float = 1.0,
) -> Image.Image:
    """Text-ONLY overlay (verse + ayah marker + translation), centered inside
    the persistent card's inner area. Transparent everywhere else."""
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pad = int((ts.card.padding if ts.card.visible else 12) * scale)
    inner_w = layout.card_w - 2 * pad - 2 * int(round(INLINE_PAD * scale))

    marker_size = 0.0
    if ts.showAyahNumber:
        marker_size, tail, tgap = _marker_slot(
            ayah_rec.get("surah"), ayah_rec.get("ayah"), layout.ar_size,
        )
    else:
        tail = tgap = 0.0
    specs: list = []
    a_img = _block(ayah_rec["arabic"], fontsvc.font_path(ts.arabic.font, "arabic"),
                   layout.ar_size, ts.arabic.color, inner_w, ts.arabic.lineHeight, rtl=True,
                   tail_width=tail, tail_gap=tgap, spec_out=specs, outline=_outline_on(ts))
    a_spec = specs[0] if specs else None
    t_img = None
    t_spec = None
    if translation_text:
        tspecs: list = []
        t_img = _block(translation_text, fontsvc.font_path(ts.translation.font, "latin"),
                       layout.tr_size, ts.translation.color, inner_w, ts.translation.lineHeight,
                       rtl=False, outline=_outline_on(ts), spec_out=tspecs)
        t_spec = tspecs[0] if tspecs else None

    ar_h = _spec_layout_h(a_spec, a_img)
    tr_h = _spec_layout_h(t_spec, t_img) if t_img is not None else 0
    gap = int(GAP_AR_TR * scale) if t_img is not None else 0
    content_h = ar_h + (gap + tr_h if t_img is not None else 0)
    y = layout.inner_top + (layout.inner_h - content_h) // 2

    ax_off, ay_off = _user_offset(ts.arabic, width, height)
    ax = _place_x(width, a_spec, a_img, scale) + ax_off
    ay = y - _spec_crop_top(a_spec) + ay_off
    canvas.alpha_composite(a_img, (ax, ay))
    if a_spec is not None and a_spec.tail_rect is not None:
        bx, by, bw, bh = a_spec.tail_rect
        base = a_spec.tail_baseline
        draw_ayah_marker(
            canvas, (ax + bx, ay + by, bw, bh),
            ayah_rec["ayah"], ts.arabic.color, fontsvc.font_path(ts.arabic.font, "arabic"),
            surah=ayah_rec.get("surah"), outline=_outline_on(ts),
            baseline=(ay + base) if base is not None else None,
            font_size=marker_size or None,
        )
    y += ar_h
    if t_img is not None:
        y += gap
        tx_off, ty_off = _user_offset(ts.translation, width, height)
        canvas.alpha_composite(
            t_img,
            (
                _place_x(width, t_spec, t_img, scale) + tx_off,
                y - _spec_crop_top(t_spec) + ty_off,
            ),
        )
    return canvas
