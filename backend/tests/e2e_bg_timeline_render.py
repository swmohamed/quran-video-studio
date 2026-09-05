"""Render a short MP4 from a trimmed, reordered background timeline."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from app.core.config import BACKGROUNDS_DIR
from app.core.ffmpeg import tools
from app.main import app
from app.models.schemas import BackgroundClip, BackgroundSettings, RenderRequest, TextSettings
from app.renderer import bg_timeline as bgtl
from app.services.backgrounds import resolve_background

client = TestClient(app)

ids = ["night-sky", "ocean", "dawn"]
for bid in ids:
    resolve_background(bid)

srcs = []
for bid in ids:
    p = resolve_background(bid)
    d = tools.probe_duration(p)
    srcs.append((bid, p, d, p.stat().st_mtime_ns, p.stat().st_size))
    print(f"source {bid}: {d:.2f}s  {p.name}")

clips_meta = []
for bid, p, d, _, _ in srcs:
    start = min(1.2, max(0.0, d * 0.15))
    end = min(d, start + max(3.5, min(6.0, d * 0.35)))
    clips_meta.append(BackgroundClip(id=f"clip-{bid}", sourceId=bid, trimStart=start, trimEnd=end))
    print(f"  trim {bid}: {start:.2f}-{end:.2f} ({end - start:.2f}s used)")

# reorder: ocean, dawn, night-sky
order = ["ocean", "dawn", "night-sky"]
clips_meta = [next(c for c in clips_meta if c.sourceId == bid) for bid in order]
print("order:", [c.sourceId for c in clips_meta])

tmp = Path("temp") / "bg_timeline_e2e"
tmp.mkdir(parents=True, exist_ok=True)
resolved = bgtl.resolve_clips(BackgroundSettings(id="ocean", clips=clips_meta))
seq = tmp / "sequence.mp4"
t0 = time.time()
bgtl.compose_sequence(resolved, False, seq, 540, 960)
print(f"compose {time.time() - t0:.1f}s  probe={tools.probe_duration(seq):.2f}s  expect={bgtl.sequence_duration(resolved, False):.2f}s")

req = RenderRequest(
    surah=108,
    fromAyah=1,
    toAyah=3,
    reciter="alafasy",
    translation="en-sahih",
    platform="tiktok",
    resolution="light",
    quality="small",
    withLight=False,
    background=BackgroundSettings(
        id="ocean",
        clips=clips_meta,
        crossfade=False,
        darkOverlay=42,
    ),
    text=TextSettings(
        arabic={"font": "amiri", "size": 68, "color": "#f5f1e8", "lineHeight": 1.85, "offsetX": 8, "offsetY": -6},
        translation={"font": "amiri", "size": 40, "color": "#d8d2c4", "lineHeight": 1.5, "offsetX": -6, "offsetY": 10},
    ),
)
print("POST /api/render")
r = client.post("/api/render", json=req.model_dump())
print(r.status_code, r.json())
job_id = r.json()["jobId"]
last = None
while True:
    time.sleep(0.5)
    s = client.get(f"/api/render/{job_id}").json()
    key = (s["state"], s["stage"], round(s["progress"], 2))
    if key != last:
        print(f"[{s['state']:9s}] {s['stage']:22s} {s['progress']*100:5.1f}%  {s['detail']}")
        last = key
    if s["state"] in ("succeeded", "failed", "canceled"):
        break

print("final:", s["state"])
if s.get("error"):
    print("ERROR:", s["error"])
    sys.exit(1)
res = s["result"]
print("file:", res["filename"])
print("duration:", res["duration"], "expected:", res["expectedDuration"])
print("resolution:", res["resolution"])

# originals must be untouched
for bid, p, d, mtime, size in srcs:
    now = p.stat()
    if now.st_mtime_ns != mtime or now.st_size != size:
        print("MUTATED SOURCE", bid)
        sys.exit(1)
print("source files unchanged")

if abs(res["duration"] - res["expectedDuration"]) > 0.75:
    print("duration mismatch")
    sys.exit(1)
print("OK")
