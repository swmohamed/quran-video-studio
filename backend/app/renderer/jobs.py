"""Render job orchestration: staged pipeline with real progress, cancel, verification."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import (
    FADE_SECONDS,
    MAX_AYAHS_PER_RENDER,
    OUTPUT_DIR,
    ROOT,
    TEMP_DIR,
    platform_dims,
    rel_to_root,
)
from app.core.ffmpeg import tools
from app.models.schemas import RenderRequest
from app.renderer import audio as raudio
from app.renderer import background as rbg
from app.renderer import bg_timeline as bgtl
from app.renderer import text as rtext
from app.renderer.encode import EncodeError, run_encode
from app.renderer.timeline import Segment, total_duration
from app.services import reciters as recsvc
from app.services import surah_audio
from app.services.quran import get_ayat, get_surah, get_translation


class JobError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    request: RenderRequest
    state: str = "queued"  # queued|running|succeeded|failed|canceled
    stage: str = "Queued"
    progress: float = 0.0
    detail: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    result: dict[str, Any] | None = None
    proc: subprocess.Popen | None = None
    cancel_requested: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "detail": self.detail,
            "error": self.error,
            "result": self.result,
        }


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()

STAGE_WEIGHTS = [
    ("prepare", 0.04),
    ("audio", 0.14),
    ("timeline", 0.02),
    ("cards", 0.15),
    ("encode", 0.57),
    ("verify", 0.08),
]


def create_job(req: RenderRequest) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], request=req)
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job.state not in ("queued", "running"):
        return False
    job.cancel_requested = True
    proc = job.proc
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    job.state = "canceled"
    job.stage = "Canceled"
    return True


def _stage_progress(job: Job, stage_key: str) -> float:
    done = 0.0
    for key, w in STAGE_WEIGHTS:
        if key == stage_key:
            return done
        done += w
    return done


def _update(job: Job, stage_key: str, label: str, frac: float, detail: str = "") -> None:
    base = _stage_progress(job, stage_key)
    weight = dict(STAGE_WEIGHTS)[stage_key]
    job.stage = label
    job.detail = detail
    job.progress = min(0.999, base + weight * max(0.0, min(1.0, frac)))
    _check_cancel(job)


def _check_cancel(job: Job) -> None:
    if job.cancel_requested:
        raise JobError("Render canceled")


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "video"


def _save_rgba_png(img: Any, path: Path) -> None:
    """Lossless RGBA PNG — never JPEG, never a flattened RGB copy."""
    if getattr(img, "mode", "RGBA") != "RGBA":
        img = img.convert("RGBA")
    img.save(path, format="PNG", compress_level=1)


def _run(job: Job) -> None:
    req = job.request
    tmp = TEMP_DIR / job.id
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        job.state = "running"
        _update(job, "prepare", "Preparing", 0.3, "Validating request")

        count = req.toAyah - req.fromAyah + 1
        if count > MAX_AYAHS_PER_RENDER:
            raise JobError(f"Selection is {count} ayahs; the maximum per render is {MAX_AYAHS_PER_RENDER}.")
        ayat = get_ayat(req.surah, req.fromAyah, req.toAyah)
        recsvc.get_reciter(req.reciter)
        translation_meta = get_translation(req.translation)
        bgtl.resolve_clips(req.background)
        out_w, out_h = platform_dims(req.platform)
        if req.resolution == "uhd":
            out_w, out_h = out_w * 2, out_h * 2
        elif req.resolution == "light":
            out_w, out_h = out_w // 2, out_h // 2
        ty_scale = rtext.composition_scale(out_w, out_h)
        # FHD matches Preview at native 1080×1920. LIGHT still supersamples.
        ss = rtext.text_supersample(req.resolution, req.text.arabic.size)
        ov_w, ov_h = out_w * ss, out_h * ss
        ov_scale = ty_scale * ss

        _update(job, "prepare", "Preparing", 1.0, f"{len(ayat)} ayahs, reciter {req.reciter}")

        # --- audio: prefer ONE continuous full-surah recording + exact timestamps ---
        audio_paths: list[Path] = []
        combined_wav: Path | None = None
        audio_mode = "verses"
        rec = recsvc.get_reciter(req.reciter)
        provider_cfg = surah_audio.reciter_provider(rec)
        if provider_cfg:
            try:
                _update(job, "audio", "Preparing continuous recitation", 0.2,
                        "Using full-surah recording with official timestamps")
                surah_file, info = surah_audio.ensure_surah(req.reciter, provider_cfg, req.surah, rec)
                file_dur = tools.probe_duration(surah_file)
                start_s, end_s, bounds = surah_audio.range_bounds(
                    req.fromAyah, req.toAyah, get_surah(req.surah)["ayahCount"], info, file_dur,
                    use_word=rec.get("surahBoundary") == "word",
                )
                seg_wav = tmp / "segment.wav"
                proc = tools.run(
                    ["-i", str(surah_file), "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}",
                     "-vn", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "-y", str(seg_wav)],
                    timeout=300,
                )
                if proc.returncode != 0 or not seg_wav.exists():
                    raise surah_audio.SurahAudioError("segment extraction failed")
                audio_total = tools.probe_duration(seg_wav)
                expected = end_s - start_s
                if abs(audio_total - expected) > 0.35:
                    raise surah_audio.SurahAudioError(
                        f"timestamp mismatch: extracted {audio_total:.2f}s vs expected {expected:.2f}s"
                    )
                combined_wav = seg_wav
                segments = []
                for i, (ayah, rel) in enumerate(bounds):
                    next_rel = bounds[i + 1][1] if i + 1 < len(bounds) else audio_total
                    segments.append(Segment(surah=req.surah, ayah=ayah, audio_path=seg_wav,
                                             duration=next_rel - rel, start=rel, end=next_rel))
                audio_mode = "surah"
                surah_start_s = start_s
                _update(job, "audio", "Preparing continuous recitation", 1.0,
                        f"One continuous segment {audio_total:.1f}s (no joins)")
            except Exception as exc:  # noqa: BLE001
                _update(job, "audio", "Preparing audio", 0.5,
                        f"Full-surah mode unavailable ({exc}); using verse-by-verse")

        if audio_mode == "verses":
            for i, a in enumerate(ayat):
                _update(job, "audio", "Fetching recitation audio", i / len(ayat),
                        f"Ayah {a['ayah']} of {req.toAyah}")
                audio_paths.append(recsvc.download_ayah(req.reciter, req.surah, a["ayah"]))

            _update(job, "audio", "Building continuous audio", 0.4,
                    "Decoding verses, preserving natural tails")
            combined_wav = tmp / "recitation.wav"
            spans, audio_total = raudio.build_continuous(audio_paths, combined_wav)
            _update(job, "audio", "Building continuous audio", 1.0,
                    f"{len(spans)} ayahs joined with zero gap ({audio_total:.1f}s)")

            segments = [
                Segment(surah=req.surah, ayah=a["ayah"], audio_path=combined_wav,
                        duration=sp.duration, start=sp.start, end=sp.end)
                for a, sp in zip(ayat, spans)
            ]
        total = total_duration(segments)
        if total <= 0:
            raise JobError("Measured audio duration is zero; cannot render.")
        _update(job, "timeline", "Building timeline", 1.0,
                f"Total duration {total:.1f}s across {len(segments)} ayahs")

        # --- persistent composition + text-only ayah overlays ---
        def translation_for(a: dict) -> str | None:
            if not translation_meta.get("languageCode"):
                return None
            return a["translations"].get(translation_meta["languageCode"])

        _update(job, "cards", "Rendering composition", 0.1, "Laying out persistent frame")
        layout = rtext.compute_layout(req.surah, ayat, translation_for, req.text, ov_w, ov_h, ov_scale)
        persistent_png = tmp / "persistent.png"
        _save_rgba_png(
            rtext.render_persistent_frame(req.surah, req.text, layout, ov_w, ov_h, ov_scale),
            persistent_png,
        )

        for i, seg in enumerate(segments):
            _check_cancel(job)
            _update(job, "cards", "Rendering verses", i / len(segments),
                    f"Typesetting ayah {seg.ayah} ({i + 1}/{len(segments)})")
            overlay = rtext.render_ayah_overlay(ayat[i], translation_for(ayat[i]), req.text, layout, ov_w, ov_h, ov_scale)
            card_path = tmp / f"card_{i:03d}.png"
            _save_rgba_png(overlay, card_path)
            seg.card_path = card_path
        _update(job, "cards", "Rendering verses", 1.0)

        # --- background + audio inputs (single continuous track) ---
        _update(job, "encode", "Encoding video", 0.0, "Starting FFmpeg")
        bg_args = bgtl.prepare_input_args(req.background, total, tmp, out_w, out_h)
        bg_filter = rbg.background_filter(req.background, out_w, out_h)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        surah_name = _slug(get_surah_name(req.surah))
        out_name = f"{surah_name}-{req.surah}-{req.fromAyah}-{req.toAyah}-{req.reciter}-{stamp}.mp4"
        out_path = OUTPUT_DIR / out_name

        def on_encode_progress(frac: float) -> None:
            _update(job, "encode", "Encoding video", frac,
                    f"{int(frac * 100)}% \u00b7 {int(total * frac)}s of {int(total)}s")

        def register(proc: subprocess.Popen) -> None:
            job.proc = proc

        run_encode(
            bg_filter, bg_args, combined_wav, persistent_png, segments,
            total, out_path,
            on_encode_progress, register,
            quality=req.quality,
            overlay_scale=(out_w, out_h) if ss > 1 else None,
        )

        # --- verify ---
        _update(job, "verify", "Verifying output", 0.3, "ffprobe checks")
        info = tools.probe_json(out_path)
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if v is None or a is None:
            raise JobError("Rendered file is missing a video or audio stream.")
        if v.get("codec_name") != "h264":
            raise JobError(f"Unexpected video codec: {v.get('codec_name')}")
        if a.get("codec_name") != "aac":
            raise JobError(f"Unexpected audio codec: {a.get('codec_name')}")
        if int(v.get("width", 0)) != out_w or int(v.get("height", 0)) != out_h:
            raise JobError(f"Unexpected resolution: {v.get('width')}x{v.get('height')}")
        final_dur = float(info["format"]["duration"])
        if abs(final_dur - total) > 0.75:
            raise JobError(
                f"Duration mismatch: video {final_dur:.2f}s vs expected {total:.2f}s"
            )
        _update(job, "verify", "Verifying output", 1.0, "All checks passed")

        # --- optional Light copy (540-class) for WhatsApp / small players ---
        light_result: dict = {}
        if req.withLight and req.resolution != "light":
            base_w, base_h = platform_dims(req.platform)
            lw, lh = base_w // 2, base_h // 2
            lty = rtext.composition_scale(lw, lh)
            lss = rtext.text_supersample("light", req.text.arabic.size)
            lovw, lovh = lw * lss, lh * lss
            lovs = lty * lss
            _update(job, "encode", "Encoding Light copy", 0.0, "540-class version for WhatsApp & small players")
            llayout = rtext.compute_layout(req.surah, ayat, translation_for, req.text, lovw, lovh, lovs)
            lpersist = tmp / "persistent_light.png"
            _save_rgba_png(
                rtext.render_persistent_frame(req.surah, req.text, llayout, lovw, lovh, lovs),
                lpersist,
            )
            lsegs = []
            for i, seg in enumerate(segments):
                _check_cancel(job)
                _update(job, "encode", "Encoding Light copy", 0.05 + 0.1 * i / len(segments),
                        f"Typesetting light copy ayah {seg.ayah}")
                lc = tmp / f"card_light_{i:03d}.png"
                _save_rgba_png(
                    rtext.render_ayah_overlay(
                        ayat[i], translation_for(ayat[i]), req.text, llayout, lovw, lovh, lovs,
                    ),
                    lc,
                )
                lsegs.append(Segment(surah=seg.surah, ayah=seg.ayah, audio_path=seg.audio_path,
                                     duration=seg.duration, start=seg.start, end=seg.end, card_path=lc))
            lout_name = out_name.replace(".mp4", "-light.mp4")
            lout_path = OUTPUT_DIR / lout_name
            lbg_filter = rbg.background_filter(req.background, lw, lh)
            run_encode(
                lbg_filter, bg_args, combined_wav, lpersist, lsegs,
                total, lout_path,
                lambda f: _update(job, "encode", "Encoding Light copy", 0.1 + 0.9 * f,
                                  f"Light copy {int(f * 100)}%"),
                register,
                quality=req.quality,
                overlay_scale=(lw, lh),
            )
            linfo = tools.probe_json(lout_path)
            lv = next((s for s in linfo.get("streams", []) if s.get("codec_type") == "video"), None)
            if lv is None or int(lv.get("width", 0)) != lw or int(lv.get("height", 0)) != lh:
                raise JobError(f"Light copy resolution unexpected: {(lv or {}).get('width')}x{(lv or {}).get('height')}")
            if abs(float(linfo["format"]["duration"]) - total) > 0.75:
                raise JobError("Light copy duration mismatch")
            light_result = {
                "lightFilename": lout_name,
                "lightUrl": f"/static/output/{lout_name}",
                "lightSizeBytes": lout_path.stat().st_size,
                "lightResolution": f"{lw}x{lh}",
            }
            # --- single MP4 containing BOTH video tracks (normal + light) ---
            d_name = out_name.replace(".mp4", "-dual.mp4")
            d_path = OUTPUT_DIR / d_name
            mux = tools.run(
                ["-i", str(out_path), "-i", str(lout_path),
                 "-map", "0:v:0", "-map", "0:a:0", "-map", "1:v:0",
                 "-c", "copy",
                 "-disposition:v:0", "default",
                 "-metadata:s:v:0", f"title=HD {out_w}x{out_h}",
                 "-metadata:s:v:1", "title=Light {lw}x{lh}",
                 "-movflags", "+faststart", "-y", str(d_path)],
                timeout=300,
            )
            if mux.returncode != 0 or not d_path.exists():
                raise JobError("dual-track mux failed")
            light_result.update({
                "dualFilename": d_name,
                "dualUrl": f"/static/output/{d_name}",
                "dualSizeBytes": d_path.stat().st_size,
            })
            _update(job, "encode", "Encoding Light copy", 1.0)

        job.result = {
            "filename": out_name,
            "url": f"/static/output/{out_name}",
            "path": rel_to_root(out_path),
            "duration": round(final_dur, 2),
            "expectedDuration": round(total, 2),
            "sizeBytes": out_path.stat().st_size,
            "resolution": f"{out_w}x{out_h}",
            "platform": req.platform,
            "resolutionTier": req.resolution,
            "quality": req.quality,
            "videoCodec": v.get("codec_name"),
            "audioCodec": a.get("codec_name"),
            "surah": req.surah,
            "fromAyah": req.fromAyah,
            "toAyah": req.toAyah,
            "reciter": req.reciter,
            "translation": translation_meta["name"] if translation_meta.get("languageCode") else "None",
            "ayahSegments": [
                {"ayah": s.ayah, "start": round(s.start, 3), "end": round(s.end, 3),
                 "duration": round(s.duration, 3)}
                for s in segments
            ],
            **light_result,
        }
        job.state = "succeeded"
        job.stage = "Done"
        job.progress = 1.0
        job.detail = "Video generated successfully"

        # diagnostic exports: final continuous WAV + boundary timestamp report
        try:
            diag = ROOT / "temp" / "audio_tests"
            diag.mkdir(parents=True, exist_ok=True)
            shutil.copy2(combined_wav, diag / "final_recitation.wav")
            report = {
                "video": out_name,
                "audioMode": audio_mode,
                "surahStart": round(surah_start_s, 3) if audio_mode == "surah" else None,
                "surahFile": str(surah_file) if audio_mode == "surah" else None,
                "width": out_w,
                "height": out_h,
                "totalDuration": round(total, 3),
                "boundaries": [
                    {"ayah": s.ayah, "start": round(s.start, 3), "end": round(s.end, 3)}
                    for s in segments
                ],
            }
            (diag / "timestamps.json").write_text(
                json.dumps(report, indent=1), encoding="utf-8"
            )
        except Exception:
            pass  # diagnostics must never fail the render
    except JobError as exc:
        job.state = "failed" if not job.cancel_requested else "canceled"
        job.error = str(exc)
        job.stage = "Canceled" if job.cancel_requested else "Failed"
    except EncodeError as exc:
        if job.cancel_requested:
            job.state = "canceled"
            job.stage = "Canceled"
        else:
            job.state = "failed"
            job.stage = "Encoding failed"
            job.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        job.state = "failed"
        job.stage = "Failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.proc = None
        shutil.rmtree(tmp, ignore_errors=True)


def get_surah_name(n: int) -> str:
    from app.services.quran import get_surah

    return get_surah(n)["englishName"]
