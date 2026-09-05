"""Unit tests: stock duration/orientation ranking + encode trim-to-audio."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.renderer.background import background_filter, background_input_args
from app.renderer.encode import QUALITY_TIERS, build_args, build_filter_complex
from app.renderer.text import text_supersample
from app.models.schemas import BackgroundSettings
from app.services.stock import classify_orientation, rank_stock_items
from app.services.stock_smart import expand_video_queries, suitability_bucket, tags_from_pexels_video

all_pass = True


def check(name: str, ok: bool, extra: str = "") -> None:
    global all_pass
    all_pass &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


print("== orientation classify ==")
check("9:16 portrait", classify_orientation(1080, 1920) == "portrait")
check("16:9 landscape", classify_orientation(1920, 1080) == "landscape")
check("1:1 square", classify_orientation(1080, 1080) == "square")
check("4:5 portrait", classify_orientation(1080, 1350) == "portrait")
check("unknown", classify_orientation(None, 1080) is None)

print("== duration ranking (audio 42s) ==")
items = [
    {"id": "10", "kind": "video", "duration": 10, "orientation": "portrait", "width": 1080, "height": 1920},
    {"id": "90", "kind": "video", "duration": 90, "orientation": "portrait", "width": 1080, "height": 1920},
    {"id": "45", "kind": "video", "duration": 45, "orientation": "portrait", "width": 1080, "height": 1920},
    {"id": "25", "kind": "video", "duration": 25, "orientation": "portrait", "width": 1080, "height": 1920},
    {"id": "50", "kind": "video", "duration": 50, "orientation": "portrait", "width": 1080, "height": 1920},
    {"id": "60", "kind": "video", "duration": 60, "orientation": "portrait", "width": 1080, "height": 1920},
]
ranked = rank_stock_items(items, audio_duration=42, target_orientation="portrait")
order = [i["id"] for i in ranked]
check(
    "suitable first, closest first, shorts last",
    order == ["45", "50", "60", "90", "25", "10"],
    str(order),
)

print("== fractional audio vs integer clip ==")
frac = [
    {"id": "40", "kind": "video", "duration": 40, "orientation": "portrait"},
    {"id": "44", "kind": "video", "duration": 44, "orientation": "portrait"},
]
frac_ranked = rank_stock_items(frac, audio_duration=40.09, target_orientation="portrait")
check(
    "40s clip matches 40.09s audio (1s tolerance)",
    [i["id"] for i in frac_ranked] == ["40", "44"],
    str([i["id"] for i in frac_ranked]),
)

print("== orientation is secondary (audio 42s) ==")
mixed = [
    {"id": "50p", "kind": "video", "duration": 50, "orientation": "portrait"},
    {"id": "45l", "kind": "video", "duration": 45, "orientation": "landscape"},
]
mixed_ranked = rank_stock_items(mixed, audio_duration=42, target_orientation="portrait")
check(
    "closer duration beats orientation mismatch",
    [i["id"] for i in mixed_ranked] == ["45l", "50p"],
    str([i["id"] for i in mixed_ranked]),
)

print("== images rank by orientation only ==")
photos = [
    {"id": "land", "kind": "image", "duration": None, "orientation": "landscape"},
    {"id": "port", "kind": "image", "duration": None, "orientation": "portrait"},
]
photo_ranked = rank_stock_items(photos, audio_duration=42, target_orientation="portrait")
check(
    "portrait photo first",
    [i["id"] for i in photo_ranked] == ["port", "land"],
    str([i["id"] for i in photo_ranked]),
)

print("== video smart query expansion ==")

def _exp(q: str) -> list[str]:
    return expand_video_queries(q)

ocean = _exp("ocean")
check("ocean keeps exact query first", ocean[0] == "ocean", str(ocean))
check("ocean adds cinematic/peaceful variants",
      "cinematic ocean" in ocean and ("peaceful sea" in ocean or "moody coastline" in ocean), str(ocean))
check("ocean uses a small query set", 2 <= len(ocean) <= 4, str(ocean))

clouds = _exp("clouds")
check("clouds expands to slow/cinematic", clouds[0] == "clouds" and any("cloud" in x for x in clouds[1:]), str(clouds))

night = _exp("night sky")
check("night sky stays the primary query", night[0] == "night sky", str(night))
check("night sky adds stars", any("star" in x for x in night), str(night))

mountains = _exp("mountains")
check("mountains adds cinematic/foggy", mountains[0] == "mountains" and (
    "cinematic mountains" in mountains or "foggy mountains" in mountains), str(mountains))
check("mountains adds lake or valley",
      "mountain lake" in mountains or "peaceful valley" in mountains, str(mountains))

lake = _exp("lake")
check("lake keeps exact query first", lake[0] == "lake", str(lake))
coast = _exp("coast")
check("coast expands to shoreline/ocean", coast[0] == "coast" and any(
    "shore" in x or "ocean" in x or "coast" in x for x in coast[1:]), str(coast))
aerial = _exp("aerial")
check("aerial expands to landscape", aerial[0] == "aerial" and any("aerial" in x for x in aerial[1:]), str(aerial))

rain = _exp("rain")
check("rain adds gentle/cinematic", rain[0] == "rain" and (
    "gentle rain" in rain or "cinematic rain" in rain), str(rain))

mosque = _exp("mosque")
check("mosque adds exterior/sunset", mosque[0] == "mosque" and (
    "mosque exterior" in mosque or "mosque sunset" in mosque), str(mosque))

stormy = _exp("stormy ocean")
check("custom stormy ocean is not reduced to ocean", stormy[0] == "stormy ocean", str(stormy))
check("stormy ocean adds cinematic variant", "cinematic stormy ocean" in stormy, str(stormy))
check("stormy ocean does not collapse to bare ocean", "ocean" not in stormy[1:], str(stormy))

print("== quran suitability ranking ==")
suited = [
    {"id": "crowd", "kind": "video", "duration": 45, "orientation": "portrait",
     "width": 1080, "height": 1920, "tags": "crowd people talking party"},
    {"id": "calm", "kind": "video", "duration": 45, "orientation": "portrait",
     "width": 1080, "height": 1920, "tags": "calm peaceful ocean waves cinematic"},
    {"id": "short-calm", "kind": "video", "duration": 10, "orientation": "portrait",
     "width": 1080, "height": 1920, "tags": "calm peaceful ocean"},
]
suited_ranked = rank_stock_items(suited, audio_duration=42, target_orientation="portrait", user_query="ocean")
suited_ids = [i["id"] for i in suited_ranked]
check("peaceful ocean before crowd at same duration", suited_ids[0] == "calm", str(suited_ids))
check("crowd is kept, only deprioritized", "crowd" in suited_ids, str(suited_ids))
check("duration still prefers long-enough calm over short calm",
      suited_ids.index("calm") < suited_ids.index("short-calm"), str(suited_ids))

check("pexels slug tags", tags_from_pexels_video(
    {"url": "https://www.pexels.com/video/slow-ocean-waves-at-sunset-12345/"}
) == "slow ocean waves at sunset")
check("crowd bucket is deprioritized", suitability_bucket(
    {"kind": "video", "tags": "crowd people talking"}, "ocean") == 2)
check("calm ocean preferred", suitability_bucket(
    {"kind": "video", "tags": "calm peaceful cinematic ocean"}, "ocean") == 0)

print("== background follows audio length ==")
args = background_input_args(Path("clip.mp4"), 72.0)
check("videos loop with -stream_loop -1", args[:3] == ["-stream_loop", "-1", "-i"])
img_args = background_input_args(Path("still.jpg"), 20.0)
check("images loop with -loop 1", img_args[0] == "-loop" and img_args[1] == "1")

enc = build_args(
    bg_filter="[0:v]null[bgv]",
    bg_args=["-stream_loop", "-1", "-i", "clip.mp4"],
    audio_path=Path("a.wav"),
    persistent_png=Path("p.png"),
    segments=[],
    total=20.0,
    out_path=Path("out.mp4"),
)
# last -t before output path is the final duration cap
t_flags = [enc[i + 1] for i, a in enumerate(enc) if a == "-t"]
check("encode -t matches audio duration", "20.000" in t_flags, str(t_flags))
check("high quality is CRF 16 medium", QUALITY_TIERS["high"] == {"crf": 16, "preset": "medium"})
check("x264 high profile", "-profile:v" in enc and enc[enc.index("-profile:v") + 1] == "high")
check("pix_fmt yuv420p", "-pix_fmt" in enc and enc[enc.index("-pix_fmt") + 1] == "yuv420p")
check("aac 192k", enc[enc.index("-c:a") + 1] == "aac" and enc[enc.index("-b:a") + 1] == "192k")

bg = background_filter(BackgroundSettings(), 1080, 1920)
check("background cover-crop uses lanczos once",
      bg.count("flags=lanczos+accurate_rnd+full_chroma_int") == 1, bg)
check("background stays full-chroma RGB until overlay",
      "format=gbrp" in bg and "format=yuv420p" not in bg and "format=yuv444p" not in bg, bg)
check("fps is on the background only", "fps=30" in bg, bg)

fc = build_filter_complex("[0:v]null[bgv]", [], 0.12, overlay_scale=(1080, 1920))
check("supersample text is rgba then one lanczos",
      "format=rgba,scale=1080:1920:flags=lanczos+accurate_rnd+full_chroma_int" in fc, fc)
check("overlays compose in gbrp", "overlay=x=0:y=0:shortest=0:format=gbrp" in fc, fc)
check("overlays keep straight alpha", ":alpha=straight" in fc, fc)
check("single final yuv420p after overlays",
      fc.count("format=yuv420p") == 1 and "format=yuv420p[vout]" in fc, fc)
check("full-range RGB into limited yuv", "in_range=full" in fc and "out_range=tv" in fc, fc)
check("bt709 tags on the composed stream", "color_primaries=bt709" in fc and "range=tv" in fc, fc)
check("no fps after text overlays", "fps=" not in fc, fc)
check("FHD raster is native (matches Preview)", text_supersample("fhd", 68) == 1)
check("UHD raster is native", text_supersample("uhd", 68) == 1)
check("LIGHT still supersamples small type", text_supersample("light", 68) >= 2)
from app.renderer.shaping import _GLYPH_SS, TextBlockSpec, render_text_block
from app.core.config import FONTS_DIR
check("glyphs raster at device pixels", _GLYPH_SS == 1)
latin_spec = TextBlockSpec(
    text="When the sky has split",
    font_path=FONTS_DIR / "Amiri-Regular.ttf",
    size=40, color="#d8d2c4", max_width=800, line_height=1.5,
    direction="ltr", script="Latn", language="en",
)
latin = render_text_block(latin_spec)
check("latin line box follows CSS line-height",
      abs(latin_spec.layout_height - 60) <= 2, str(latin_spec.layout_height))
from app.renderer.text import MARKER_BOX, MARKER_GAP, _marker_slot
from app.services import qpc as qpcsvc
check("marker size matches CSS 1.42em", MARKER_BOX == 1.42)
check("marker gap matches CSS 0.12em", MARKER_GAP == 0.12)
info84 = qpcsvc.marker_for(84, 1)
adv84 = qpcsvc.glyph_advance(int(info84["page"]), ord(info84["char"]), 1.42 * 68)
check("84:1 marker advance is narrower than 1.42em square", 70 <= adv84 <= 90, str(adv84))
_fs, _adv, _gap = _marker_slot(84, 1, 68.0)
check("layout reserves glyph advance not 1.42em", abs(_adv - adv84) < 0.1, str(_adv))
check("layout still paints marker at 1.42em", abs(_fs - 1.42 * 68) < 0.01, str(_fs))
check("marker gap uses the marker em not the verse em",
      abs(_gap - 0.12 * 1.42 * 68) < 0.05, str(_gap))
from app.renderer.text import INLINE_PAD
from app.services.quran import get_ayat
from app.services import fonts as fontsvc
ayah84 = get_ayat(84, 1, 1)[0]
verse_spec = TextBlockSpec(
    text=ayah84["arabic"],
    font_path=fontsvc.font_path("amiri", "arabic"),
    size=68, color="#f5f1e8", max_width=900, line_height=1.85,
    direction="rtl", script="Arab", language="ar",
    tail_width=_adv, tail_gap=_gap,
)
verse_img = render_text_block(verse_spec)
check("84:1 used height matches Chrome 128", verse_spec.layout_height == 128,
      str(verse_spec.layout_height))
check("84:1 inline width is the CSS run ~490", abs(verse_spec.layout_width - 490) <= 2,
      str(verse_spec.layout_width))
check("preview padding-inline is 4", INLINE_PAD == 4)
from app.renderer.text import HEADER_EN_TRACKING, HEADER_EN_WEIGHT
check("English header tracking matches CSS 0.08em", HEADER_EN_TRACKING == 0.08)
check("English header weight matches Preview 500", HEADER_EN_WEIGHT == 500)
tracked = TextBlockSpec(
    text="ALINSHIQAAQ",
    font_path=FONTS_DIR / "Inter.ttf",
    size=30, color="#f5f1e8", max_width=800, line_height=1.2,
    direction="ltr", script="Latn", language="en",
    letter_spacing=0.08 * 30,
)
plain = TextBlockSpec(
    text="ALINSHIQAAQ",
    font_path=FONTS_DIR / "Inter.ttf",
    size=30, color="#f5f1e8", max_width=800, line_height=1.2,
    direction="ltr", script="Latn", language="en",
)
tracked_img = render_text_block(tracked)
plain_img = render_text_block(plain)
check("letter-spacing widens English header", tracked_img.width > plain_img.width + 10,
      f"tracked={tracked_img.width} plain={plain_img.width}")

print("== audio duration from timestamps ==")
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.get("/api/preview/duration", params={
    "surah": 89, "fromAyah": 6, "toAyah": 12, "reciter": "alafasy",
})
check("GET /api/preview/duration 200", r.status_code == 200, r.text[:160])
if r.status_code == 200:
    body = r.json()
    check("duration is a positive number", isinstance(body.get("duration"), (int, float)) and body["duration"] > 5, str(body))
    check("uses timestamps when available", body.get("source") in ("timestamps", "verses", "estimate"), str(body.get("source")))
    segs = body.get("segments") or []
    check("duration includes ayah segments", isinstance(segs, list) and len(segs) >= 1, str(segs)[:160])
    if segs:
        check("segment 0 starts at 0", segs[0].get("at", -1) == 0, str(segs[0]))

print()
print("ALL PASS" if all_pass else "SOME FAILED")
sys.exit(0 if all_pass else 1)
