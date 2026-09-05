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
from PIL import Image, ImageFilter

_ONE_64 = 64.0
# Raster at device pixels. A 2× BOX downsample averaged four coverage
# samples and made stems softer than Chrome's 1× grayscale AA.
_GLYPH_SS = 1
# Mild coverage curve: Chrome/Skia grayscale AA (antialiased) is slightly
# heavier in the midtones than linear FreeType coverage.
_AA_LUT = [int(round(min(255.0, ((i / 255.0) ** 0.88) * 255.0))) for i in range(256)]


def ink_halo(img: Image.Image, radius: int) -> Image.Image:
    """Dark 1-px-class halo under glyphs so thin strokes survive small players.
    Applied at the raster size — never drawn small then enlarged."""
    if radius < 1 or img.mode != "RGBA" or img.width < 2 or img.height < 2:
        return img
    k = min(9, radius * 2 + 1)
    if k % 2 == 0:
        k += 1
    alpha = img.getchannel("A")
    dilated = alpha.filter(ImageFilter.MaxFilter(k))
    halo = Image.new("RGBA", img.size, (8, 7, 6, 0))
    halo.putalpha(dilated.point(lambda p: min(210, int(p))))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(halo)
    out.alpha_composite(img)
    return out


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def crisp_rgba(img: Image.Image) -> Image.Image:
    """Tighten grayscale coverage so stems match CSS antialiased."""
    if img.mode != "RGBA":
        return img
    r, g, b, a = img.split()
    return Image.merge("RGBA", (r, g, b, a.point(_AA_LUT)))


def _box_to_native(
    img: Image.Image,
    size: tuple[int, int],
    ink: tuple[int, int, int, int] | None,
) -> Image.Image:
    """2× → native without dirtying cream ink at glyph edges.

    Independent RGBA BOX averages transparent (0,0,0,0) into RGB, which
    turns coverage AA into a grey fringe. Chrome keeps the CSS color in
    RGB and only varies alpha. Solid-ink glyphs downsample alpha only;
    mixed-color (outline halo) uses premultiplied RGBa.
    """
    if img.size == size:
        return img
    if ink is not None:
        alpha = img.getchannel("A").resize(size, Image.Resampling.BOX)
        out = Image.new("RGBA", size, ink)
        out.putalpha(alpha)
        return out
    return img.convert("RGBa").resize(size, Image.Resampling.BOX).convert("RGBA")


def _apply_variations(ft_face, hb_font, size: float, weight: int | None) -> None:
    """Match CSS font-optical-sizing:auto + font-weight on variable fonts."""
    try:
        axes = ft_face.get_variation_info().axes
    except Exception:
        return
    if not axes:
        return
    coords: list[float] = []
    hb_vars: dict[str, float] = {}
    for ax in axes:
        tag = str(ax.tag)
        val = float(ax.default)
        if tag == "opsz":
            val = min(float(ax.maximum), max(float(ax.minimum), float(size)))
        elif tag == "wght" and weight is not None:
            val = min(float(ax.maximum), max(float(ax.minimum), float(weight)))
        coords.append(val)
        hb_vars[tag] = val
    try:
        ft_face.set_var_design_coords(tuple(coords))
    except Exception:
        pass
    try:
        hb_font.set_variations(hb_vars)
    except Exception:
        pass


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

        self.ft_face = freetype.Face(str(path))
        # 26.6 fractional pixels — keeps glyph size exact under non-integer
        # composition scales instead of snapping to a whole pixel then stretching.
        self.ft_face.set_char_size(int(round(self.size * 64)))
        _apply_variations(self.ft_face, self.hb_font, self.size, weight)
        self.ft_face.set_char_size(int(round(self.size * 64)))

        m = self.ft_face.size
        self.ascent = m.ascender / _ONE_64
        self.descent = m.descender / _ONE_64  # negative
        self.line_height = self.ascent - self.descent

    def shape(self, text: str, direction: str, script: str, language: str,
              letter_spacing: float = 0.0):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.direction = direction
        buf.script = script
        buf.language = language
        hb.shape(self.hb_font, buf, {})
        infos, poss = buf.glyph_infos, buf.glyph_positions
        track = float(letter_spacing or 0.0)
        out = []
        for info, pos in zip(infos, poss):
            x_adv = pos.x_advance / _ONE_64
            if track and x_adv != 0:
                x_adv += track
            out.append(
                (
                    int(info.codepoint),  # glyph id
                    x_adv,
                    pos.y_advance / _ONE_64,
                    pos.x_offset / _ONE_64,
                    pos.y_offset / _ONE_64,
                )
            )
        return out

    def advance_width(self, text: str, direction: str, script: str, language: str,
                      letter_spacing: float = 0.0) -> float:
        return sum(g[1] for g in self.shape(text, direction, script, language, letter_spacing))

    def _draw_glyphs(self, glyphs, color: tuple[int, int, int, int], outline: bool = False) -> tuple[Image.Image, float, float, float, float, float]:
        """Render shaped glyphs onto an oversized canvas.

        Glyphs are rasterized at device pixels with FT LIGHT (CSS
        -webkit-font-smoothing: antialiased). Coverage is then mildly
        tightened to match Skia midtones. No BOX/Lanczos resize.

        Returns (image, ink_left, ink_top, advance_total, ink_height, baseline_y).
        """
        pad = int(self.size * 1.2) + 8
        total_w = int(sum(g[1] for g in glyphs)) + pad * 2
        h = int(self.line_height * 2 + self.size * 1.6) + pad
        baseline = int(self.ascent + self.size * 0.8) + 8
        tw, th = max(total_w, 4), max(h, 4)
        ss = _GLYPH_SS
        img = Image.new("RGBA", (tw * ss, th * ss), (0, 0, 0, 0))
        px = float(pad)
        min_x, min_y, max_x, max_y = 10**9, 10**9, -10**9, -10**9
        self.ft_face.set_char_size(int(round(self.size * ss * 64)))
        try:
            for gid, _adv, _yadv, xoff, yoff in glyphs:
                try:
                    flags = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_LIGHT
                    self.ft_face.load_glyph(gid, flags)
                except Exception:
                    px += _adv
                    continue
                slot = self.ft_face.glyph
                bmp = slot.bitmap
                if bmp.rows and bmp.width and bmp.buffer:
                    x0 = int(round((px + xoff) * ss + slot.bitmap_left))
                    y0 = int(round((baseline - yoff) * ss - slot.bitmap_top))
                    rows, cols = bmp.rows, bmp.width
                    alpha = Image.frombytes("L", (cols, rows), bytes(bmp.buffer))
                    patch = Image.new("RGBA", (cols, rows), color)
                    patch.putalpha(alpha)
                    img.alpha_composite(patch, (x0, y0))
                    min_x, min_y = min(min_x, x0), min(min_y, y0)
                    max_x = max(max_x, x0 + cols)
                    max_y = max(max_y, y0 + rows)
                px += _adv
        finally:
            self.ft_face.set_char_size(int(round(self.size * 64)))
        if max_x < min_x:  # empty
            min_x = min_y = max_x = max_y = 0
            native = _box_to_native(img, (tw, th), None if outline else color)
            return native, min_x, min_y, px - pad, 0.0, baseline / ss
        if outline:
            radius = max(2, int(round(self.size * 0.03))) * ss
            img = ink_halo(img, radius)
        img = _box_to_native(img, (tw, th), None if outline else color)
        img = crisp_rgba(img)
        return img, min_x / ss, min_y / ss, px - pad, (max_y - min_y) / ss, baseline / ss


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
        outline: bool = False,
        letter_spacing: float = 0.0,
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
        self.outline = bool(outline)
        self.letter_spacing = float(letter_spacing or 0.0)
        # Filled after rendering: tail box (x, y, w, h) in the returned image.
        self.tail_rect: tuple[int, int, int, int] | None = None
        self.tail_baseline: int | None = None
        # CSS line-box height vs extra ink kept above it (overflow: visible).
        self.layout_height: int = 0
        self.crop_top: int = 0
        # CSS inline size (advances + tail). crop_left is ink overflow
        # to the left of that box — same as overflow: visible.
        self.layout_width: int = 0
        self.crop_left: int = 0


def wrap_words(font: ShapedFont, text: str, max_width: int,
               letter_spacing: float = 0.0) -> list[str]:
    """Greedy word wrap using shaped word widths (joining never crosses spaces)."""
    words = [w for w in text.split(" ") if w != ""]
    if not words:
        return [text] if text else []
    lines: list[str] = []
    cur = words[0]
    dirn = "rtl" if font_is_rtl(text) else "ltr"
    script, lang = _script_for(text)
    cur_w = font.advance_width(cur, dirn, script, lang, letter_spacing)
    for w in words[1:]:
        ww = font.advance_width(w, dirn, script, lang, letter_spacing)
        space_w = font.advance_width(" ", dirn, script, lang, letter_spacing)
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
    lines = wrap_words(font, spec.text, eff_w, spec.letter_spacing) if spec.max_width else [spec.text]
    carry_idx = len(lines) - 1 if (tail_total and lines) else -1

    # CSS unitless line-height is font-size × the factor, with the font
    # content box (ascent+descent) centered in that line box. A tight ink
    # crop was ~15px shorter than Preview and shifted the verse down.
    n_lines = max(len(lines), 1)
    line_advance = spec.size * max(0.0, float(spec.line_height))
    tail_w = float(spec.tail_width or 0.0)
    tail_gap = float(spec.tail_gap or 0.0)
    half_lead = (line_advance - font.line_height) / 2.0
    overflow = int(spec.size * 0.85) + 8
    layer_w = int(max(spec.max_width + spec.size, spec.size * 4, tail_w * 2, 4))
    line_box_h = line_advance * n_lines
    layer_h = max(4, int(round(line_box_h)) + overflow * 2 + 16)
    canvas = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    origin = float(overflow)
    tail_box: tuple[int, int, int, int] | None = None
    run_left = layer_w
    run_right = 0.0
    max_run_w = 0.0
    for li, line in enumerate(lines):
        line_top = origin + li * line_advance
        css_baseline = line_top + half_lead + font.ascent
        has_tail = li == carry_idx and tail_w > 0
        line_img = None
        ink_l = ink_t = 0.0
        ink_h = 0.0
        adv = 0.0
        dest_y = int(round(line_top))
        if line.strip():
            glyphs = font.shape(line, direction, script, language, spec.letter_spacing)
            line_img, ink_l, ink_t, adv, ink_h, base_y = font._draw_glyphs(
                glyphs, color, outline=spec.outline,
            )
            dest_y = int(round(css_baseline - base_y))

        # CSS inline size: glyph advances + trailing marker. Keep subpixels
        # until blit so we do not widen the run by integer truncation.
        content_w = adv + ((tail_gap + tail_w) if has_tail else 0.0)
        content_x0 = (layer_w - content_w) / 2.0
        run_left = min(run_left, content_x0)
        run_right = max(run_right, content_x0 + content_w)
        max_run_w = max(max_run_w, content_w)

        if line_img is not None:
            if direction == "rtl":
                # text starts at the RIGHT edge of the content box
                x_right = content_x0 + content_w
                canvas.alpha_composite(
                    line_img,
                    (int(round(x_right - adv - ink_l)), dest_y),
                )
            else:
                canvas.alpha_composite(
                    line_img,
                    (int(round(content_x0 - ink_l)), dest_y),
                )

        if has_tail:
            # CSS inline marker: margin-inline-start gap, vertical-align baseline,
            # line-height 1. Do not center a square on the ink — that made the
            # ornament larger and dropped it below Preview.
            tx = content_x0 if direction == "rtl" else content_x0 + content_w - tail_w
            em = float(tail_w)
            ty = int(round(css_baseline - em))
            tail_box = (int(round(tx)), ty, int(round(tx + tail_w)), int(round(ty + em)))

    ink = canvas.getbbox()
    y0 = origin
    y1 = origin + line_box_h
    x0 = run_left if max_run_w else 0.0
    x1 = run_right if max_run_w else 1.0
    if ink:
        # Keep the CSS inline / line box; only expand when marks overflow.
        y0 = min(y0, ink[1])
        y1 = max(y1, ink[3])
        x0 = min(x0, ink[0])
        x1 = max(x1, ink[2])
    if tail_box is not None:
        # Reserve width for the inline marker. CSS overflow:visible must not
        # grow the line box, so do not expand height by the empty em square.
        x0 = min(x0, tail_box[0])
        x1 = max(x1, tail_box[2])
    bbox = (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))
    if bbox[2] <= bbox[0]:
        bbox = (bbox[0], bbox[1], bbox[0] + 1, bbox[3])
    if bbox[3] <= bbox[1]:
        bbox = (bbox[0], bbox[1], bbox[2], bbox[1] + 1)
    out = canvas.crop(bbox)
    # Chrome offsetHeight for 68px / 1.85 is 128 when a 1.42em QCF marker
    # sits on the line (computed line-height is 125.8). Without the
    # marker, the used box is just the line-height.
    used_h = line_box_h + (2.0 if tail_w else 0.0)
    spec.layout_height = max(1, int(round(used_h)))
    spec.crop_top = max(0, int(round(origin - bbox[1])))
    spec.layout_width = max(1, int(round(max_run_w))) if max_run_w else out.width
    spec.crop_left = max(0, int(round(run_left - bbox[0]))) if max_run_w else 0
    if tail_box is not None:
        spec.tail_rect = (tail_box[0] - bbox[0], tail_box[1] - bbox[1],
                          tail_box[2] - tail_box[0], tail_box[3] - tail_box[1])
        spec.tail_baseline = int(round(css_baseline)) - bbox[1]
    return out
