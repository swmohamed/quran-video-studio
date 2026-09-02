"""End-to-end backend render test.
Usage: python tests/e2e_render.py [reciter_id] [from_ayah] [to_ayah]"""
import sys
import time

sys.path.insert(0, ".")

RECITER = sys.argv[1] if len(sys.argv) > 1 else "alafasy"
FROM_A = int(sys.argv[2]) if len(sys.argv) > 2 else 6
TO_A = int(sys.argv[3]) if len(sys.argv) > 3 else 12

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import RenderRequest

c = TestClient(app)

req = RenderRequest(
    surah=89, fromAyah=FROM_A, toAyah=TO_A,
    reciter=RECITER, translation="en-sahih",
    background={"id": "night-sky"},
)
print(f"reciter: {RECITER}  range: {FROM_A}->{TO_A}")
r = c.post("/api/render", json=req.model_dump())
print("POST /api/render ->", r.status_code, r.json())
job_id = r.json()["jobId"]

last = None
while True:
    time.sleep(0.4)
    s = c.get(f"/api/render/{job_id}").json()
    key = (s["state"], s["stage"], round(s["progress"], 2))
    if key != last:
        print(f"[{s['state']:9s}] {s['stage']:22s} {s['progress']*100:5.1f}%  {s['detail']}")
        last = key
    if s["state"] in ("succeeded", "failed", "canceled"):
        break

print("\nfinal:", s["state"])
if s.get("error"):
    print("ERROR:", s["error"])
if s.get("result"):
    res = s["result"]
    print("file:", res["filename"])
    print("duration:", res["duration"], "expected:", res["expectedDuration"])
    print("resolution:", res["resolution"], "codecs:", res["videoCodec"], res["audioCodec"])
    print("size:", round(res["sizeBytes"] / 1024 / 1024, 2), "MB")
    print("segments:", [(g["ayah"], g["start"], round(g["duration"], 2)) for g in res["ayahSegments"]])
    dl = c.get(f"/api/render/{job_id}/download")
    print("download:", dl.status_code, len(dl.content), "bytes")
