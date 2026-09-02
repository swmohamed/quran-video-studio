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

Responsive composition: every render targets a platform canvas (W x H).
Typography keeps the visual identity anchored to the SHORT edge (all
presets have a 1080px short edge, so font sizes stay constant); card
width, margins, header position and max card height adapt to the canvas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from app.core.config import FONTS_DIR
from app.models.schemas import TextSettings
from app.renderer.shaping import TextBlockSpec, render_text_block
from app.services import fonts as fontsvc
from app.services.quran import get_surah

HEADER_TOP_PCT = 0.078      # header top as fraction of canvas height (150/1920)
GAP_AR_TR = 52
MAX_CARD_HEIGHT_PCT = 0.5625  # 1080/1920 — same proportion of height as before
MIN_ARABIC = 42
MIN_TRANSLATION = 26

# --- Quranic ayah-end marker (drawn, not Unicode) ---------------------------
# Thin ornamental rosette: double ring + 8 radiating petal dots, numeral in
# the Arabic text color. Proportions mirror the browser preview
# (globals.css .qvs-ayah-marker) so preview and export stay pixel-consistent.
# All values are fractions of the marker box side S (= 1.3 × Arabic size).
MARKER_BOX = 1.3      # marker box side, in em of the Arabic font size
MARKER_GAP = 0.35     # gap between verse end and marker, in em
MARKER_RING = 0.62    # outer ring diameter / S
MARKER_RING2 = 0.52   # inner ring diameter / S
MARKER_STROKE = 0.045  # ring stroke / S
MARKER_PETALS = 8     # radiating petal dots around the ring
MARKER_PETAL_ORBIT = 0.74  # petal orbit diameter / S
MARKER_PETAL_R = 0.055    # petal dot radius / S
MARKER_NUM = {1: 0.44, 2: 0.40, 3: 0.33}  # number font size / em by digit count

_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def arabic_indic(n: int) -> str:
    return str(n).translate(_ARABIC_INDIC)


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _block(text: str, font_path: Path, size: float, color: str, max_w: int, line_h: float,
           rtl: bool, opacity: int = 255, tail_width: float = 0.0, tail_gap: float = 0.0,
           spec_out: list | None = None) -> Image.Image:
    spec = TextBlockSpec(
        text=text, font_path=font_path, size=size, color=color,
        max_width=max_w, line_height=line_h,
        direction="rtl" if rtl else "ltr",
        script="Arab" if rtl else "Latn",
        language="ar" if rtl else "en",
        opacity=opacity,
        tail_width=tail_width, tail_gap=tail_gap,
    )
    img = render_text_block(spec)
    if spec_out is not None:
        spec_out.append(spec)
    return img


def draw_ayah_marker(img: Image.Image, box: tuple[int, int, int, int],
                     number: int, color: str, num_font_path: Path) -> None:
    """Draw the Quranic verse-end marker into `box` (x, y, w, h): a thin
    ornamental rosette — double ring + 8 radiating petal dots — with the
    ayah number (Arabic-Indic digits, same ink color) centered inside."""
    x, y, w, h = box
    s = min(w, h)  # marker box side
    cx, cy = x + w / 2, y + h / 2
    rgba = _hex_rgb(color) + (255,)
    d = ImageDraw.Draw(img)

    # outer ring
    r = s * MARKER_RING / 2
    stroke = max(2, int(round(s * MARKER_STROKE)))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba, width=stroke)
    # inner ring
    r2 = s * MARKER_RING2 / 2
    if r2 > 4:
        d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=rgba,
                  width=max(1, int(round(s * MARKER_STROKE * 0.6))))
    # radiating petal dots (rosette)
    orbit = s * MARKER_PETAL_ORBIT / 2
    pr = s * MARKER_PETAL_R
    for k in range(MARKER_PETALS):
        ang = math.radians(k * 360 / MARKER_PETALS)
        px, py = cx + math.cos(ang) * orbit, cy + math.sin(ang) * orbit
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=rgba)

    # ayah number, Arabic-Indic digits, centered (digits need no shaping)
    digits = len(str(number))
    fs = int(round(s * MARKER_NUM.get(digits, MARKER_NUM[3]) / MARKER_BOX))
    try:
        f = ImageFont.truetype(str(num_font_path), fs)
        num = arabic_indic(number)
        l, t, rr, b = f.getbbox(num)
        tw, th = rr - l, b - t
        d.text((cx - tw / 2 - l, cy - th / 2 - t), num, font=f, fill=rgba)
    except Exception:
        pass  # never let the marker break the render


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
    for the longest verse, position clamped below the header. Geometry
    adapts to the platform canvas (width x height); typography scales with
    the short edge (1.0 at 1080, 2.0 at 4K exports)."""
    card = ts.card
    ar = ts.arabic
    tr = ts.translation

    # Card width: percentage of canvas width, but on wide canvases (landscape)
    # capped so text lines keep a comfortable reading width.
    card_w = int(width * card.widthPct / 100)
    if width > height:  # landscape: cap card width against the short edge
        card_w = min(card_w, int(height * 1.15))
    pad = int(card.padding * scale)
    inner_w = card_w - 2 * pad

    header_top = _header_top(ts, height)
    header_bottom = header_top
    if ts.header.show:
        y = header_top
        if ts.header.showArabic:
            y += int(64 * scale * 1.77) + int(18 * scale)
        if ts.header.showEnglish:
            y += int(30 * scale * 1.22) + int(8 * scale)
        header_bottom = y

    min_top = header_bottom + int(60 * scale) if ts.header.show else int(80 * scale)
    max_card_h = int(height * MAX_CARD_HEIGHT_PCT)

    ar_size = float(ar.size) * scale
    tr_size = float(tr.size) * scale
    min_ar = MIN_ARABIC * scale
    min_tr = MIN_TRANSLATION * scale
    while True:
        worst = 0.0
        for a in ayat:
            h = _measure_height(a, translation_for(a), ts, ar_size, tr_size, inner_w, scale)
            worst = max(worst, h)
        total_h = worst + 2 * pad if card.visible else worst + int(24 * scale)
        if total_h <= max_card_h or ar_size <= min_ar:
            break
        ar_size = max(min_ar, ar_size - 4 * scale)
        tr_size = max(min_tr, tr_size - 2 * scale)

    card_h = int(round(total_h))
    card_top = int(height * card.positionPct / 100 - card_h / 2)
    card_top = max(card_top, min_top)
    card_top = min(card_top, height - card_h - int(60 * scale))

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
    tail = MARKER_BOX * ar_size if ts.showAyahNumber else 0.0
    gap = MARKER_GAP * ar_size if ts.showAyahNumber else 0.0
    ar_img = _block(
        ayah_rec["arabic"], fontsvc.font_path(ts.arabic.font, "arabic"), ar_size,
        ts.arabic.color, inner_w, ts.arabic.lineHeight, rtl=True,
        tail_width=tail, tail_gap=gap,
    )
    h = ar_img.height
    if translation_text:
        t_img = _block(
            translation_text, fontsvc.font_path(ts.translation.font, "latin"), tr_size,
            ts.translation.color, inner_w, ts.translation.lineHeight, rtl=False,
        )
        h += GAP_AR_TR * scale + t_img.height
    return h


def render_persistent_frame(surah: int, ts: TextSettings, layout: Layout,
                            width: int, height: int, scale: float = 1.0) -> Image.Image:
    """Header + card — composited over the background for the ENTIRE video."""
    meta = get_surah(surah)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # header
    if ts.header.show:
        y = _header_top(ts, height)
        if ts.header.showArabic:
            b = _block(meta["arabicName"], FONTS_DIR / "Amiri-Bold.ttf", int(64 * scale),
                       "#e8d9b0", width - int(160 * scale), 1.7, rtl=True)
            canvas.alpha_composite(b, ((width - b.width) // 2, y))
            y += b.height + int(18 * scale)
        latin_bits = []
        if ts.header.showEnglish:
            latin_bits.append(meta["englishName"].upper())
        if latin_bits:
            b = _block("  \u00b7  ".join(latin_bits), FONTS_DIR / "Inter.ttf", int(30 * scale),
                       "#b9b2a2", width - int(200 * scale), 1.4, rtl=False, opacity=210)
            canvas.alpha_composite(b, ((width - b.width) // 2, y))

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
    inner_w = layout.card_w - 2 * pad

    blocks: list[tuple[Image.Image, int]] = []  # (image, gap_before)
    tail = MARKER_BOX * layout.ar_size if ts.showAyahNumber else 0.0
    tgap = MARKER_GAP * layout.ar_size if ts.showAyahNumber else 0.0
    specs: list = []
    a_img = _block(ayah_rec["arabic"], fontsvc.font_path(ts.arabic.font, "arabic"),
                   layout.ar_size, ts.arabic.color, inner_w, ts.arabic.lineHeight, rtl=True,
                   tail_width=tail, tail_gap=tgap, spec_out=specs)
    if specs and specs[0].tail_rect is not None:
        draw_ayah_marker(a_img, specs[0].tail_rect, ayah_rec["ayah"],
                         ts.arabic.color, fontsvc.font_path(ts.arabic.font, "arabic"))
    blocks.append((a_img, 0))
    if translation_text:
        t_img = _block(translation_text, fontsvc.font_path(ts.translation.font, "latin"),
                       layout.tr_size, ts.translation.color, inner_w, ts.translation.lineHeight,
                       rtl=False)
        blocks.append((t_img, int(GAP_AR_TR * scale)))

    content_h = sum(b.height for b, _ in blocks) + sum(g for _, g in blocks[1:])
    y = layout.inner_top + (layout.inner_h - content_h) // 2
    for img, gap in blocks:
        y += gap
        canvas.alpha_composite(img, ((width - img.width) // 2, y))
        y += img.height
    return canvas
