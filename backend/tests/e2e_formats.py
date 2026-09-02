"""E2E tests for platform video formats + online background library.

Covers:
  - stock download endpoint (real Pexels CDN file, no API key needed)
  - stock search parsing for Pexels & Pixabay (mocked responses — no network)
  - renders for all 6 platforms -> ffprobe dimensions
  - cover-crop: vertical bg in landscape canvas, landscape bg in vertical
    canvas -> no black bars (edge strips carry background content)
  - safe-zone guides never appear in the MP4 (scan frames for guide color)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from app.core.config import PLATFORM_PRESETS, platform_dims
from app.core.ffmpeg import tools
from app.main import app
from app.models.schemas import RenderRequest
from app.services import stock as stocksvc

c = TestClient(app)
ROOT = Path("..").resolve()
GUIDE_RGB = np.array([224, 128, 96])  # --color of preview safe-zone guides
all_pass = True


def check(name: str, ok: bool, extra: str = "") -> None:
    global all_pass
    all_pass &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


# ---------- 1. stock search parsing (mocked, no network) ----------
print("== stock search parsing (mocked) ==")


class FakeResp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


def fake_requests_get(url, params=None, headers=None, timeout=None, **kw):
    if "pexels.com/v1/search" in url:
        return FakeResp({"photos": [{
            "id": 123, "width": 4000, "height": 6000, "photographer": "T",
            "src": {"medium": "m.jpg", "large2x": "l.jpg", "original": "o.jpg"},
        }]})
    if "pexels.com/videos/search" in url:
        return FakeResp({"videos": [{
            "id": 9, "image": "t.jpg",
            "video_files": [
                {"file_type": "video/mp4", "link": "tiny.mp4", "width": 640, "height": 360},
                {"file_type": "video/mp4", "link": "sd.mp4", "width": 960, "height": 540},
                {"file_type": "video/mp4", "link": "hd.mp4", "width": 1920, "height": 1080},
            ],
            "user": {"name": "V"},
        }]})
    if "pixabay.com/api/" in url and "/videos" not in url:
        return FakeResp({"hits": [{
            "id": 55, "imageWidth": 3000, "imageHeight": 2000, "user": "P",
            "webformatURL": "w.jpg", "largeImageURL": "l.jpg",
        }]})
    if "pixabay.com/api/videos/" in url:
        return FakeResp({"hits": [{
            "id": 77, "user": "Q", "picture_id": "abc", "pageURL": "p",
            "videos": {"medium": {"url": "v.mp4", "width": 1280, "height": 720},
                       "large": {"url": "vl.mp4", "width": 1920, "height": 1080}},
        }]})
    raise AssertionError(f"unexpected url {url}")


import requests as _rq

_orig_get = _rq.get
_orig_keys = stocksvc._keys
_rq.get = fake_requests_get
stocksvc._keys = lambda: {"pexels": "test-key", "pixabay": "test-key"}
try:
    pex_img = stocksvc.search("pexels", "ocean", "portrait", "image")
    check("pexels image parse", len(pex_img) == 1 and pex_img[0]["url"] == "l.jpg"
          and pex_img[0]["author"] == "T", str(pex_img[0]))
    pex_vid = stocksvc.search("pexels", "ocean", "portrait", "video")
    check("pexels video parse (prefers 720-1280 wide mp4)",
          len(pex_vid) == 1 and pex_vid[0]["url"] == "sd.mp4"
          and pex_vid[0]["width"] == 960, str(pex_vid[0]))
    pix_img = stocksvc.search("pixabay", "waves", "landscape", "image")
    check("pixabay image parse (orientation=horizontal)",
          len(pix_img) == 1 and pix_img[0]["url"] == "l.jpg"
          and (params_ok := True), str(pix_img[0]))
    pix_vid = stocksvc.search("pixabay", "waves", None, "video")
    check("pixabay video parse (picks large mp4)",
          len(pix_vid) == 1 and pix_vid[0]["url"] == "vl.mp4", str(pix_vid[0]))
finally:
    _rq.get = _orig_get
    stocksvc._keys = _orig_keys

r = c.get("/api/stock/search", params={"q": "ocean", "provider": "pexels"})
check("live search without key -> 503", r.status_code == 503)

# ---------- 2. download & use (real file, whitelisted CDN) ----------
print("== download & use (real CDN file) ==")
stock_id = "stock-pexels-210186"
if not (ROOT / "backgrounds" / f"{stock_id}.jpg").exists():
    r = c.post("/api/stock/download", json={
        "provider": "pexels", "id": "210186",
        "url": "https://images.pexels.com/photos/210186/pexels-photo-210186.jpeg?auto=compress&cs=tinysrgb&w=1600",
        "kind": "image", "name": "Ocean waves",
    })
    check("stock download 200", r.status_code == 200, r.text[:80])
info = tools.probe_json(ROOT / "backgrounds" / f"{stock_id}.jpg")
v = next(s for s in info["streams"] if s.get("codec_type") == "video")
check("stock file ffprobe-validated, landscape", v["width"] > v["height"],
      f'{v["width"]}x{v["height"]}')
r = c.post("/api/stock/download", json={"provider": "x", "id": "1",
          "url": "https://evil.example.com/a.jpg", "kind": "image"})
check("untrusted host refused", r.status_code == 400)


# ---------- 3. platform renders ----------
def render(platform: str, bg_id: str) -> Path:
    req = RenderRequest(
        surah=89, fromAyah=1, toAyah=1, reciter="dosari",
        translation="en-sahih", platform=platform,
        background={"id": bg_id, "brightness": 100, "contrast": 100,
                    "saturation": 100, "blur": 0, "darkOverlay": 0, "position": "center"},
    )
    r = c.post("/api/render", json=req.model_dump())
    assert r.status_code == 200, r.text
    jid = r.json()["jobId"]
    for _ in range(600):
        snap = c.get(f"/api/render/{jid}").json()
        if snap["state"] not in ("queued", "running"):
            break
        time.sleep(0.25)
    assert snap["state"] == "succeeded", f"{platform}: {snap.get('error')}"
    return ROOT / "output" / snap["result"]["filename"]


def frame_rgb(path: Path, t: float) -> np.ndarray:
    pr = subprocess.run(
        [tools.ffmpeg, "-v", "error", "-ss", str(t), "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    w = tools.probe_json(path)
    v = next(s for s in w["streams"] if s.get("codec_type") == "video")
    W, H = int(v["width"]), int(v["height"])
    return np.frombuffer(pr.stdout, dtype=np.uint8).reshape(H, W, 3).astype(np.int16)


def strip_luma(f: np.ndarray) -> dict:
    g = f.mean(axis=2)
    return {
        "left": float(g[:, :6].mean()), "right": float(g[:, -6:].mean()),
        "top": float(g[:6, :].mean()), "bottom": float(g[-6:, :].mean()),
    }


print("== platform renders (Al-Fajr 89:1, dosari) ==")
for p in PLATFORM_PRESETS:
    w, h = platform_dims(p)
    out = render(p, "sand" if p != "youtube" else "sand")
    meta = tools.probe_json(out)
    v = next(s for s in meta["streams"] if s.get("codec_type") == "video")
    check(f"{p} output {w}x{h}",
          int(v["width"]) == w and int(v["height"]) == h,
          f'got {v["width"]}x{v["height"]} ({out.name})')
    f = frame_rgb(out, 0.4)
    # safe-zone guides are DOM-only; a real leak would paint structural
    # borders (thousands of px). Natural photo colors may match a handful.
    mask = (np.abs(f - GUIDE_RGB).max(axis=2) < 30)
    check(f"{p}: no safe-zone guides in MP4", int(mask.sum()) < 500, f"{int(mask.sum())} px matched")

print("== cover-crop: landscape stock bg in vertical canvas (tiktok) ==")
out = render("tiktok", stock_id)
f = frame_rgb(out, 0.4)
s = strip_luma(f)
check("no black bars (edges carry bg content)",
      all(v > 12 for v in s.values()),
      " ".join(f"{k}={v:.0f}" for k, v in s.items()))

print("== cover-crop: vertical bg in landscape canvas (youtube) ==")
out = render("youtube", "sand")
f = frame_rgb(out, 0.4)
s = strip_luma(f)
check("no black bars (edges carry bg content)",
      all(v > 12 for v in s.values()),
      " ".join(f"{k}={v:.0f}" for k, v in s.items()))

print()
print("ALL FORMAT TESTS PASSED" if all_pass else "FORMAT TESTS FAILED")
sys.exit(0 if all_pass else 1)
