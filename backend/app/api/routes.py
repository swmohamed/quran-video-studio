"""HTTP API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import BACKGROUNDS_DIR, OUTPUT_DIR, RECITERS_DIR, UPLOADS_DIR
from app.core.ffmpeg import tools
from app.models.schemas import PreviewTimelineRequest, RenderRequest
from app.renderer.audio import analyze_playback
from app.services import surah_audio
from app.services.quran import get_surah as _get_surah_meta
from app.renderer import jobs
from app.services import backgrounds as bgsvc
from app.services import fonts as fontsvc
from app.services import stock as stocksvc
from app.services import quran as qsvc
from app.services import reciters as recsvc
from app.services import qpc as qpcsvc
from app.services.quran import QuranDataError
from app.core.config import DEFAULT_PLATFORM, PLATFORM_PRESETS

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    try:
        qsvc.surahs()
        data_ok, data_err = True, None
    except QuranDataError as exc:
        data_ok, data_err = False, str(exc)
    return {
        "ffmpeg": tools.check(),
        "dataOk": data_ok,
        "dataError": data_err,
        "fonts": {"amiri": (fontsvc.font_path("amiri", "arabic").exists()),
                  "inter": (fontsvc.font_path("inter", "latin").exists())},
    }


@router.get("/surahs")
def surahs() -> dict:
    return {"surahs": qsvc.surahs()}


@router.get("/surahs/{number}")
def surah(number: int) -> dict:
    if not 1 <= number <= 114:
        raise HTTPException(404, "Surah number must be 1-114.")
    meta = qsvc.get_surah(number)
    ayahs = qsvc._verses_file(number)["ayahs"]
    try:
        ayahs = qpcsvc.attach_markers(ayahs)
    except Exception:
        ayahs = [dict(a) for a in ayahs]
    return {"surah": meta, "ayahs": ayahs}


@router.get("/reciters")
def reciters() -> dict:
    return {"reciters": recsvc.list_reciters()}


@router.get("/translations")
def translations() -> dict:
    return {"translations": qsvc.translations(), "quranTextSource": qsvc.quran_source_note()}


@router.get("/presets")
def presets() -> dict:
    return {"presets": qsvc.presets()}


@router.get("/fonts")
def fonts() -> dict:
    return fontsvc.catalog()


@router.get("/qpc/font/{page}")
def qpc_font(page: int) -> FileResponse:
    """QCF v2 page font (p{N}-v2), downloaded on demand and cached locally."""
    if not 1 <= page <= 604:
        raise HTTPException(404, "Mushaf page must be 1-604.")
    try:
        path = qpcsvc.ensure_page_font(page)
    except qpcsvc.QpcError as exc:
        raise HTTPException(502, str(exc)) from exc
    return FileResponse(
        path,
        media_type="font/ttf",
        filename=f"p{page}.ttf",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/backgrounds")
def backgrounds() -> dict:
    return {"backgrounds": bgsvc.list_backgrounds()}


@router.get("/platforms")
def platforms() -> dict:
    """Video format presets (TikTok/Shorts/Reels/YouTube/Portrait/Square)."""
    return {"platforms": PLATFORM_PRESETS, "default": DEFAULT_PLATFORM}


@router.get("/stock/status")
def stock_status() -> dict:
    stocksvc.ensure_keys_template()
    keys = stocksvc._keys()
    return {"providers": {"pexels": bool(keys["pexels"]), "pixabay": bool(keys["pixabay"])}}


@router.get("/stock/search")
def stock_search(q: str, provider: str = "pexels", orientation: str | None = None,
                 kind: str = "image", audioDuration: float | None = None) -> dict:
    try:
        items = stocksvc.search(
            provider, q.strip()[:60], orientation, kind,
            audio_duration=audioDuration,
        )
    except stocksvc.StockError as exc:
        raise HTTPException(503, str(exc))
    return {
        "provider": provider,
        "kind": kind,
        "audioDuration": audioDuration,
        "items": items,
    }


class StockDownloadRequest(BaseModel):
    provider: str
    id: str
    url: str
    kind: str = "image"
    name: str | None = None


@router.post("/stock/download")
def stock_download(req: StockDownloadRequest) -> dict:
    try:
        entry = stocksvc.download(req.provider, req.id, req.url, req.kind, req.name)
    except stocksvc.StockError as exc:
        raise HTTPException(400, str(exc))
    return entry


@router.post("/background/upload")
async def upload_background(file: UploadFile = File(...)) -> dict:
    return await _save(file)


async def _save(file: UploadFile) -> dict:
    # UploadFile.read in threadpool via save_upload is sync; wrap in thread
    import anyio

    return await anyio.to_thread.run_sync(bgsvc.save_upload, file)


@router.post("/render")
def render(req: RenderRequest) -> dict:
    count = req.toAyah - req.fromAyah + 1
    if count < 1:
        raise HTTPException(400, "Ayah range is empty.")
    if count > 30:
        raise HTTPException(400, f"{count} ayahs selected; maximum is 30.")
    job = jobs.create_job(req)
    return {"jobId": job.id}


_span_cache: dict[tuple, list] = {}


def _estimate_verse_seconds(arabic: str) -> float:
    words = len((arabic or "").strip().split())
    return min(9.0, max(2.5, 1.4 + words * 0.55))


@router.get("/preview/duration")
def preview_duration(
    surah: int, fromAyah: int, toAyah: int, reciter: str = "alafasy",
) -> dict:
    """Selected recitation length in seconds — source of truth for background ranking.

    Prefers official verse timestamps (no audio download). Falls back to
    cached verse files, then a word-count estimate.
    """
    count = toAyah - fromAyah + 1
    if count < 1 or count > 30:
        raise HTTPException(400, "Ayah range must be 1-30 ayahs.")
    try:
        rec = recsvc.get_reciter(reciter)
        ayat = qsvc.get_ayat(surah, fromAyah, toAyah)
    except (QuranDataError, recsvc.ReciterError) as exc:
        raise HTTPException(400, str(exc))

    provider_cfg = surah_audio.reciter_provider(rec)
    if provider_cfg:
        try:
            provider, pid = provider_cfg
            info = surah_audio.fetch_timings(provider, pid, surah, rec)
            start_s, end_s, bounds = surah_audio.range_bounds(
                fromAyah, toAyah, _get_surah_meta(surah)["ayahCount"], info,
                use_word=rec.get("surahBoundary") == "word",
            )
            return {
                "duration": round(end_s - start_s, 3),
                "estimated": False,
                "source": "timestamps",
                "segments": [{"ayah": a, "at": round(rel, 3)} for a, rel in bounds],
            }
        except Exception:  # noqa: BLE001 — fall through
            pass

    paths = [recsvc.local_audio_path(reciter, surah, a["ayah"]) for a in ayat]
    if paths and all(p.exists() and p.stat().st_size > 1024 for p in paths):
        try:
            segs = []
            acc = 0.0
            for a, p in zip(ayat, paths):
                d = tools.probe_duration(p)
                segs.append({"ayah": a["ayah"], "at": round(acc, 3), "duration": round(d, 3)})
                acc += d
            return {"duration": round(acc, 3), "estimated": False, "source": "verses", "segments": segs}
        except Exception:  # noqa: BLE001
            pass

    segs = []
    acc = 0.0
    for a in ayat:
        d = _estimate_verse_seconds(a.get("arabic") or "")
        segs.append({"ayah": a["ayah"], "at": round(acc, 3), "duration": round(d, 1)})
        acc += d
    return {"duration": round(acc, 1), "estimated": True, "source": "estimate", "segments": segs}


@router.post("/preview/timeline")
def preview_timeline(req: PreviewTimelineRequest) -> dict:
    """Live-playback timeline. Prefers ONE continuous full-surah recording
    with official timestamps; falls back to the verse-by-verse pipeline."""
    count = req.toAyah - req.fromAyah + 1
    if count < 1 or count > 30:
        raise HTTPException(400, "Ayah range must be 1-30 ayahs.")
    try:
        ayat = qsvc.get_ayat(req.surah, req.fromAyah, req.toAyah)
        rec = recsvc.get_reciter(req.reciter)
    except (QuranDataError, recsvc.ReciterError) as exc:
        raise HTTPException(400, str(exc))

    # --- continuous full-surah mode ---
    provider_cfg = surah_audio.reciter_provider(rec)
    if provider_cfg:
        try:
            path, info = surah_audio.ensure_surah(req.reciter, provider_cfg, req.surah, rec)
            start_s, end_s, bounds = surah_audio.range_bounds(
                req.fromAyah, req.toAyah, _get_surah_meta(req.surah)["ayahCount"], info,
                use_word=rec.get("surahBoundary") == "word",
            )
            return {
                "mode": "surah",
                "surah": req.surah,
                "reciter": req.reciter,
                "url": f"/static/surah/{req.reciter}/{req.surah:03d}.mp3",
                "offset": round(start_s, 3),
                "duration": round(end_s - start_s, 3),
                "total": round(end_s - start_s, 3),
                "segments": [{"ayah": a, "at": round(rel, 3)} for a, rel in bounds],
                "estimated": False,
            }
        except Exception:  # noqa: BLE001 — fall back to verses
            pass

    # --- verse-by-verse fallback ---
    paths = []
    try:
        for a in ayat:
            paths.append(recsvc.download_ayah(req.reciter, req.surah, a["ayah"]))
        key = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        cached = _span_cache.get(key)
        if cached is None:
            cached = analyze_playback(paths)
            if len(_span_cache) > 32:
                _span_cache.clear()
            _span_cache[key] = cached
        spans = cached
    except recsvc.ReciterError as exc:
        raise HTTPException(502, str(exc))
    except Exception as exc:  # decode failure
        raise HTTPException(502, f"Audio preparation failed: {exc}")
    segments = [
        {
            "ayah": a["ayah"],
            "offset": round(sp.offset, 4),
            "duration": round(sp.duration, 4),
            "audioUrl": f"/static/audio/{req.reciter}/{recsvc.ayah_filename(req.surah, a['ayah'])}",
        }
        for a, sp in zip(ayat, spans)
    ]
    return {
        "mode": "verses",
        "surah": req.surah,
        "reciter": req.reciter,
        "segments": segments,
        "total": round(sum(s["duration"] for s in segments), 3),
        "estimated": False,
    }


@router.get("/render/{job_id}")
def render_status(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown render job.")
    return job.snapshot()


@router.post("/render/{job_id}/cancel")
def render_cancel(job_id: str) -> dict:
    if not jobs.cancel_job(job_id):
        raise HTTPException(400, "Job not active.")
    return {"ok": True}


@router.get("/render/{job_id}/download")
def render_download(job_id: str) -> FileResponse:
    job = jobs.get_job(job_id)
    if not job or not job.result:
        raise HTTPException(404, "No rendered file for this job.")
    path = OUTPUT_DIR / job.result["filename"]
    if not path.exists():
        raise HTTPException(404, "Rendered file no longer exists.")
    return FileResponse(path, media_type="video/mp4", filename=job.result["filename"])
