"""Arabic/Latin text shaping + rasterization.

Pillow on this platform lacks Raqm, so we build the proven stack directly:
uharfbuzz (HarfBuzz: joining, ligatures, diacritic mark positioning)
+ freetype-py (glyph rasterization) + Pillow (compositing).

This gives correct RTL, Arabic shaping, and stacked diacritics for Uthmani
Quran text without requiring browser rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import freetype
import uharfbuzz as hb
from PIL import Image

_ONE_64 = 64.0


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


class ShapedFont:
    """A font at a pixel size, shaped by HarfBuzz, rasterized by FreeType."""

    def __init__(self, path: Path, size: float, weight: int | None = None) -> None:
        self.path = path
        self.size = float(size)
        data = path.read_bytes()

        face = hb.Face(data)
        self.hb_font = hb.Font(face)
        # scale so that reported advances are in 26.6 fixed point of pixels
        self.hb_font.scale = (int(self.size * _ONE_64), int(self.size * _ONE_64))
        if weight is not None:
            try:
                self.hb_font.set_variations({"wght": weight})
            except Exception:
                pass

        self.ft_face = freetype.Face(str(path))
        self.ft_face.set_pixel_sizes(0, int(round(self.size)))
        if weight is not None:
            try:
                self.ft_face.set_var_design_coordinates({"Weight": float(weight)})
            except Exception:
                pass

        m = self.ft_face.size
        self.ascent = m.ascender / _ONE_64
        self.descent = m.descender / _ONE_64  # negative
        self.line_height = self.ascent - self.descent

    def shape(self, text: str, direction: str, script: str, language: str):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.direction = direction
        buf.script = script
        buf.language = language
        hb.shape(self.hb_font, buf, {})
        infos, poss = buf.glyph_infos, buf.glyph_positions
        out = []
        for info, pos in zip(infos, poss):
            out.append(
                (
                    int(info.codepoint),  # glyph id
                    pos.x_advance / _ONE_64,
                    pos.y_advance / _ONE_64,
                    pos.x_offset / _ONE_64,
                    pos.y_offset / _ONE_64,
                )
            )
        return out

    def advance_width(self, text: str, direction: str, script: str, language: str) -> float:
        return sum(g[1] for g in self.shape(text, direction, script, language))

    def _draw_glyphs(self, glyphs, color: tuple[int, int, int, int]) -> tuple[Image.Image, float, float, float, float]:
        """Render shaped glyphs onto an oversized canvas.

        Returns (image, ink_left, ink_top, advance_total, ink_height).
        """
        pad = int(self.size * 1.2) + 8
        total_w = int(sum(g[1] for g in glyphs)) + pad * 2
        h = int(self.line_height * 2 + self.size * 1.6) + pad
        baseline = int(self.ascent + self.size * 0.8) + 8
        img = Image.new("RGBA", (max(total_w, 4), max(h, 4)), (0, 0, 0, 0))
        px = pad
        min_x, min_y, max_x, max_y = 10**9, 10**9, -10**9, -10**9
        for gid, _adv, _yadv, xoff, yoff in glyphs:
            try:
                self.ft_face.load_glyph(gid, freetype.FT_LOAD_RENDER)
            except Exception:
                px += _adv
                continue
            slot = self.ft_face.glyph
            bmp = slot.bitmap
            if bmp.rows and bmp.width and bmp.buffer:
                x0 = int(round(px + xoff + slot.bitmap_left))
                y0 = int(round(baseline - yoff - slot.bitmap_top))
                # coverage mask -> colored RGBA patch
                rows, cols = bmp.rows, bmp.width
                alpha = Image.frombytes("L", (cols, rows), bytes(bmp.buffer))
                patch = Image.new("RGBA", (cols, rows), color)
                patch.putalpha(alpha)
                img.alpha_composite(patch, (x0, y0))
                min_x, min_y = min(min_x, x0), min(min_y, y0)
                max_x = max(max_x, x0 + cols)
                max_y = max(max_y, y0 + rows)
            px += _adv
        if max_x < min_x:  # empty
            min_x = min_y = max_x = max_y = 0
        return img, min_x, min_y, px - pad, max_y - min_y


class TextBlockSpec:
    def __init__(
        self,
        text: str,
        font_path: Path,
        size: float,
        color: str,
        max_width: int,
        line_height: float,
        direction: str = "ltr",
        script: str = "Latn",
        language: str = "en",
        weight: int | None = None,
        align: str = "center",
        opacity: int = 255,
        tail_width: float = 0.0,
        tail_gap: float = 0.0,
    ) -> None:
        self.text = text
        self.font_path = font_path
        self.size = size
        self.color = color
        self.max_width = max_width
        self.line_height = line_height
        self.direction = direction
        self.script = script
        self.language = language
        self.weight = weight
        self.align = align
        self.opacity = opacity
        # Reserved, unbreakable space appended AFTER the text (end of flow:
        # left side for RTL). Mirrors an inline-block in the browser layout.
        self.tail_width = tail_width
        self.tail_gap = tail_gap
        # Filled after rendering: tail box (x, y, w, h) in the returned image.
        self.tail_rect: tuple[int, int, int, int] | None = None


def wrap_words(font: ShapedFont, text: str, max_width: int) -> list[str]:
    """Greedy word wrap using shaped word widths (joining never crosses spaces)."""
    words = [w for w in text.split(" ") if w != ""]
    if not words:
        return [text] if text else []
    lines: list[str] = []
    cur = words[0]
    cur_w = font.advance_width(cur, "rtl" if font_is_rtl(text) else "ltr", *_script_for(text))
    for w in words[1:]:
        ww = font.advance_width(w, "rtl" if font_is_rtl(text) else "ltr", *_script_for(text))
        space_w = font.advance_width(" ", "rtl" if font_is_rtl(text) else "ltr", *_script_for(text))
        if cur_w + space_w + ww <= max_width:
            cur = f"{cur} {w}"
            cur_w += space_w + ww
        else:
            lines.append(cur)
            cur, cur_w = w, ww
    lines.append(cur)
    return lines


def font_is_rtl(text: str) -> bool:
    return any("\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f" for c in text)


def _script_for(text: str) -> tuple[str, str]:
    if font_is_rtl(text):
        return ("Arab", "ar")
    return ("Latn", "en")


def render_text_block(spec: TextBlockSpec) -> Image.Image:
    """Wrap + shape + rasterize a text block; returns a tightly-cropped RGBA image.
    If spec.tail_width > 0, an unbreakable empty box is reserved at the END of
    the text flow (left edge for RTL) — like a trailing inline-block in HTML —
    and its position in the final image is written to spec.tail_rect."""
    direction = spec.direction
    script, language = spec.script, spec.language
    rgb = _hex_to_rgb(spec.color)
    color = (rgb[0], rgb[1], rgb[2], spec.opacity)

    font = ShapedFont(spec.font_path, spec.size, spec.weight)
    # Reserve room for the tail by wrapping tighter: the marker rides glued
    # to the LAST word (like a nowrap span in the browser preview), so it can
    # never be orphaned on a line of its own.
    tail_total = int(round(spec.tail_width + spec.tail_gap)) if spec.tail_width else 0
    eff_w = spec.max_width - tail_total if (spec.max_width and tail_total) else spec.max_width
    lines = wrap_words(font, spec.text, eff_w) if spec.max_width else [spec.text]
    carry_idx = len(lines) - 1 if (tail_total and lines) else -1

    line_advance = font.line_height * spec.line_height
    tail_w = int(round(spec.tail_width))
    tail_gap = int(round(spec.tail_gap))
    # generous canvas then crop: marks (fatha/shadda stacks) can exceed metrics
    layer_w = int(max(spec.max_width + spec.size, spec.size * 4, tail_w * 2))
    layer_h = int(line_advance * len(lines) + font.size * 1.5) + 16
    canvas = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    top = int(font.size * 0.7) + 8
    tail_box: tuple[int, int, int, int] | None = None
    for li, line in enumerate(lines):
        has_tail = li == carry_idx and tail_w > 0
        line_img = None
        ink_l = ink_t = 0
        ink_h = 0.0
        adv = 0.0
        if line.strip():
            glyphs = font.shape(line, direction, script, language)
            line_img, ink_l, ink_t, adv, ink_h = font._draw_glyphs(glyphs, color)

        # content width INCLUDING the trailing tail box (centered as one unit)
        content_w = int(adv) + (tail_gap + tail_w if has_tail else 0)
        content_x0 = int((layer_w - content_w) / 2)  # centered like an inline run

        if line_img is not None:
            if direction == "rtl":
                # text starts at the RIGHT edge of the content box
                x = content_x0 + content_w
                canvas.alpha_composite(line_img, (x - int(adv) - int(ink_l), top - int(ink_t)))
            else:
                x = content_x0
                canvas.alpha_composite(line_img, (x - int(ink_l), top - int(ink_t)))

        if has_tail:
            # tail sits at the flow END: left for RTL, right for LTR
            tx = content_x0 if direction == "rtl" else content_x0 + content_w - tail_w
            cy = top + ink_h / 2
            tail_box = (tx, int(cy - tail_w / 2), tx + tail_w, int(cy - tail_w / 2) + tail_w)

        top += int(line_advance)

    bbox = canvas.getbbox()
    if tail_box is not None:
        b = (min(bbox[0], tail_box[0]), min(bbox[1], tail_box[1]),
             max(bbox[2], tail_box[2]), max(bbox[3], tail_box[3])) if bbox else tuple(tail_box)
        bbox = b
    out = canvas.crop(bbox) if bbox else Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    if tail_box is not None and bbox:
        spec.tail_rect = (tail_box[0] - bbox[0], tail_box[1] - bbox[1],
                          tail_box[2] - tail_box[0], tail_box[3] - tail_box[1])
    return out
