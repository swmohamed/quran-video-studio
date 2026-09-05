import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type {
  Ayah,
  BackgroundEntry,
  BackgroundSettings,
  JobSnapshot,
  PreviewTimeline,
  SurahMeta,
  TextSettings,
  VersesSeg,
} from "../../types";
import { VersePreview } from "./VersePreview";
import { api } from "../../lib/api";
import { SAFE_ZONES, platformPreset } from "../../lib/formats";
import { fmtDuration } from "../../lib/time";

export type SafePlatform = keyof typeof SAFE_ZONES;
type PreviewMode = "static" | "preparing" | "playing";

function fmtTime(s: number): string {
  return fmtDuration(s);
}

export function PreviewStage({
  surahMeta,
  ayahs,
  previewIndex,
  onPreviewIndexChange,
  translationText,
  text,
  bgEntry,
  backgrounds,
  bgSettings,
  playhead,
  audioDuration,
  onPlayhead,
  seekGeneration,
  job,
  onReset,
  selection,
  platform: formatId = "tiktok",
}: {
  surahMeta: SurahMeta | undefined;
  ayahs: Ayah[];
  previewIndex: number;
  onPreviewIndexChange: (i: number) => void;
  translationText: string | null;
  text: TextSettings;
  bgEntry: BackgroundEntry | undefined;
  backgrounds: BackgroundEntry[];
  bgSettings: BackgroundSettings;
  playhead: number;
  audioDuration: number;
  onPlayhead: (t: number) => void;
  seekGeneration: number;
  job: JobSnapshot | null;
  onReset: () => void;
  selection: { surah: number; fromAyah: number; toAyah: number; reciter: string };
  platform?: string;
}) {
  const preset = platformPreset(formatId);
  const STAGE_W = preset.width;
  const STAGE_H = preset.height;
  const zonesForFormat = SAFE_ZONES[formatId];

  const wrapRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.3);
  const [safeZone, setSafeZone] = useState(false);
  const [platform, setPlatform] = useState<SafePlatform>("tiktok");

  // ---- live playback state ----
  const [mode, setMode] = useState<PreviewMode>("static");
  const [timeline, setTimeline] = useState<PreviewTimeline | null>(null);
  const [playIndex, setPlayIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [playError, setPlayError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const genRef = useRef(0);
  const playbackRef = useRef<{ stop: () => void } | null>(null);
  const stopRef = useRef<() => void>(() => {});

  const selKey = `${selection.surah}:${selection.fromAyah}-${selection.toAyah}:${selection.reciter}`;

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      setScale(Math.min(w / STAGE_W, h / STAGE_H));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [STAGE_W, STAGE_H]);

  useEffect(() => {
    try {
      setSafeZone(localStorage.getItem("qvs.preview.safeZone") === "1");
      const p = localStorage.getItem("qvs.preview.platform") as SafePlatform | null;
      if (p && p in SAFE_ZONES) setPlatform(p);
    } catch { /* noop */ }
  }, []);

  // follow the selected video format: social formats have their own zones
  useEffect(() => {
    if (formatId && formatId in SAFE_ZONES) setPlatform(formatId as SafePlatform);
  }, [formatId]);

  const toggleSafeZone = () => {
    setSafeZone((v) => {
      try {
        localStorage.setItem("qvs.preview.safeZone", v ? "0" : "1");
      } catch { /* noop */ }
      return !v;
    });
  };

  const choosePlatform = (p: SafePlatform) => {
    setPlatform(p);
    try {
      localStorage.setItem("qvs.preview.platform", p);
    } catch { /* noop */ }
  };

  // stop playback when selection changes
  useEffect(() => {
    stopRef.current();
  }, [selKey]);

  // stop playback when the user seeks the background timeline
  useEffect(() => {
    if (seekGeneration > 0) stopRef.current();
  }, [seekGeneration]);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      stopRef.current();
    };
  }, []);

  const stopPlayback = useCallback(() => {
    genRef.current++;
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    const handle = playbackRef.current;
    playbackRef.current = null;
    if (handle) handle.stop();
    setMode("static");
    setElapsed(0);
  }, []);
  stopRef.current = stopPlayback;

  /** Timer-based advance for estimated (silent) timelines. */
  const playSegmentTimed = useCallback(
    (tl: PreviewTimeline, i: number) => {
      const segs = tl.segments as VersesSeg[];
      if (i >= segs.length) {
        stopPlayback();
        return;
      }
      const gen = ++genRef.current;
      setPlayIndex(i);
      const seg = segs[i];
      const before = segs.slice(0, i).reduce((acc, s) => acc + s.duration, 0);
      const t0 = performance.now();
      const tick = () => {
        if (genRef.current !== gen) return;
        const next = before + Math.min(seg.duration, (performance.now() - t0) / 1000);
        setElapsed(next);
        onPlayhead(next);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      timerRef.current = window.setTimeout(() => {
        if (genRef.current !== gen) return;
        playSegmentTimed(tl, i + 1);
      }, seg.duration * 1000);
    },
    [stopPlayback, onPlayhead],
  );

  /**
   * Gapless recitation playback that mirrors the export pipeline exactly:
   * the backend returns per-ayah offset/duration (encoder padding removed,
   * natural reciter pauses preserved); we decode each verse once and
   * schedule the trimmed spans back-to-back on one AudioContext clock.
   */
  const playGapless = useCallback(async (tl: PreviewTimeline) => {
    const segs = tl.segments as VersesSeg[];
    const AC: typeof AudioContext =
      window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AC();
    const nodes: AudioBufferSourceNode[] = [];
    let stopped = false;
    const handle = {
      stop: () => {
        stopped = true;
        for (const n of nodes) {
          try {
            n.stop();
          } catch { /* already ended */ }
        }
        ctx.close().catch(() => undefined);
      },
    };
    playbackRef.current = handle;

    await ctx.resume();
    const buffers: AudioBuffer[] = [];
    for (const seg of segs) {
      const resp = await fetch(seg.audioUrl);
      if (!resp.ok) throw new Error(`audio fetch ${resp.status}`);
      const bytes = await resp.arrayBuffer();
      buffers.push(await ctx.decodeAudioData(bytes));
    }
    if (stopped) return;

    // schedule the processed spans contiguously (same boundaries as the render)
    const lead = 0.08;
    const t0 = ctx.currentTime + lead;
    const starts: number[] = [];
    let t = t0;
    segs.forEach((seg, i) => {
      starts.push(t);
      const src = ctx.createBufferSource();
      src.buffer = buffers[i];
      src.connect(ctx.destination);
      src.start(t, seg.offset, seg.duration);
      nodes.push(src);
      t += seg.duration; // zero-gap: next ayah begins immediately
    });
    const total = t - t0;
    const gen = ++genRef.current;
    const tick = () => {
      if (genRef.current !== gen || stopped) return;
      const elapsed = ctx.currentTime - t0;
      if (elapsed <= 0) {
        requestAnimationFrame(tick);
        return;
      }
      const now = Math.min(total, Math.max(0, elapsed));
      setElapsed(now);
      onPlayhead(now);
      // current segment = last scheduled start we have passed
      let segIdx = 0;
      for (let k = 0; k < starts.length; k++) {
        if (elapsed >= starts[k] - t0) segIdx = k;
      }
      setPlayIndex((prev) => (prev === segIdx ? prev : segIdx));
      if (elapsed < total + 0.25) {
        requestAnimationFrame(tick);
      } else {
        stopPlayback();
      }
    };
    requestAnimationFrame(tick);
  }, [stopPlayback, onPlayhead]);

  /**
   * Continuous full-surah mode: ONE audio stream, seeked to the range start.
   * Nothing is stitched — the browser streams the exact same continuous
   * recording the render slices, so pauses/breaths are the original ones.
   */
  const playSurah = useCallback(async (tl: PreviewTimeline) => {
    if (!tl.url || tl.offset === undefined || tl.duration === undefined) {
      throw new Error("surah timeline missing url/offset");
    }
    const audio = new Audio();
    audio.preload = "auto";
    audio.src = tl.url;
    let stopped = false;
    const handle = {
      stop: () => {
        stopped = true;
        audio.pause();
        audio.src = "";
      },
    };
    playbackRef.current = handle;

    await new Promise<void>((resolve, reject) => {
      const ok = () => resolve();
      audio.addEventListener("loadedmetadata", ok, { once: true });
      audio.addEventListener("error", () => reject(new Error("surah audio failed to load")), { once: true });
      audio.load();
      window.setTimeout(() => reject(new Error("surah audio load timeout")), 20000);
    });
    if (stopped) return;

    audio.currentTime = tl.offset;
    await audio.play();

    const boundaries = tl.segments.map((s) => ({ ayah: s.ayah, at: s.at ?? 0 }));
    const gen = ++genRef.current;
    const tick = () => {
      if (genRef.current !== gen || stopped) return;
      const elapsed = audio.currentTime - tl.offset!;
      if (elapsed < 0) {
        requestAnimationFrame(tick);
        return;
      }
      const now = Math.min(tl.duration!, Math.max(0, elapsed));
      setElapsed(now);
      onPlayhead(now);
      let segIdx = 0;
      for (let k = 0; k < boundaries.length; k++) {
        if (elapsed >= boundaries[k].at) segIdx = k;
      }
      setPlayIndex((prev) => (prev === segIdx ? prev : segIdx));
      if (elapsed < tl.duration! - 0.05) {
        requestAnimationFrame(tick);
      } else {
        stopPlayback();
      }
    };
    requestAnimationFrame(tick);
  }, [stopPlayback, onPlayhead]);

  const startPlayback = async () => {
    setPlayError(null);
    setMode("preparing");
    setPlayIndex(0);
    let tl: PreviewTimeline | null = null;
    try {
      tl = await api.previewTimeline(selection);
    } catch (e) {
      // offline / download failed -> estimated pacing so the preview still plays
      const estimated: PreviewTimeline = {
        mode: "verses",
        surah: selection.surah,
        reciter: selection.reciter,
        estimated: true,
        total: 0,
        segments: ayahs.map((a) => {
          const words = a.arabic.trim().split(/\s+/).length;
          return {
            ayah: a.ayah,
            offset: 0,
            duration: Math.min(9, Math.max(2.5, 1.4 + words * 0.55)),
            audioUrl: "",
          };
        }),
      };
      estimated.total = Math.round((estimated.segments as VersesSeg[]).reduce((s, x) => s + x.duration, 0) * 10) / 10;
      setTimeline(estimated);
      setPlayError(
        e instanceof Error && e.message ? e.message : "Could not prepare recitation audio.",
      );
      setMode("playing");
      playSegmentTimed(estimated, 0);
      return;
    }
    setTimeline(tl);
    try {
      if (tl.mode === "surah") {
        await playSurah(tl);
      } else {
        await playGapless(tl);
      }
      setMode("playing");
    } catch {
      // decode/playback problem (e.g. unsupported codec): fall back to measured timers
      stopRef.current();
      setMode("playing");
      playSegmentTimed(tl, 0);
    }
  };

  const current = mode === "playing" && timeline ? ayahs[playIndex] : ayahs[previewIndex];
  const succeeded = job?.state === "succeeded";
  const playingAyahNo = mode === "playing" && timeline ? timeline.segments[playIndex]?.ayah : null;

  return (
    <section
      id="preview"
      className="qvs-stage-well flex h-[min(36dvh,22rem)] min-h-0 shrink-0 flex-col border-b-0 lg:h-auto lg:min-h-0 lg:flex-1"
      aria-label="Video preview"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 lg:px-4">
        {mode === "static" ? (
          <div className="flex items-center gap-1" role="group" aria-label="Preview ayah">
            <button
              type="button"
              onClick={() => onPreviewIndexChange(Math.max(0, previewIndex - 1))}
              disabled={previewIndex <= 0}
              aria-label="Previous ayah in selection"
              className="qvs-btn qvs-btn-ghost h-9 w-9 p-0 disabled:opacity-40"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M10 3 5 8l5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <span className="min-w-14 text-center text-[13px] tabular-nums text-ink">
              {current ? `${current.surah}:${current.ayah}` : "—"}
            </span>
            <button
              type="button"
              onClick={() => onPreviewIndexChange(Math.min(ayahs.length - 1, previewIndex + 1))}
              disabled={previewIndex >= ayahs.length - 1}
              aria-label="Next ayah in selection"
              className="qvs-btn qvs-btn-ghost h-9 w-9 p-0 disabled:opacity-40"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="m6 3 5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span aria-live="off" className="text-[12.5px] tabular-nums text-ink">
              {fmtTime(elapsed)} / {timeline ? fmtTime(timeline.total) : "0:00"}
            </span>
          </div>
        )}
        <span className="hidden text-[11px] text-ink-3 sm:inline">
          {ayahs.length
            ? mode === "playing"
              ? `Playing ${playIndex + 1} of ${ayahs.length} · ${playingAyahNo ? `${selection.surah}:${playingAyahNo}` : ""}`
              : `${previewIndex + 1} of ${ayahs.length} selected ayahs`
            : "No ayahs selected"}
        </span>

        {/* play / stop + safe zones */}
        <div className="ms-auto flex items-center gap-2">
          {mode === "static" ? (
            <button
              type="button"
              onClick={startPlayback}
              disabled={!ayahs.length}
              className="qvs-btn h-9 border border-gold/40 bg-gold/10 px-3 text-[13px] font-semibold text-gold hover:bg-gold/20 disabled:opacity-40"
            >
              <svg width="11" height="12" viewBox="0 0 11 12" fill="currentColor" aria-hidden="true">
                <path d="M0 0.8c0-.6.7-1 1.2-.6l9 5.1c.5.3.5 1 0 1.3l-9 5.1c-.5.3-1.2-.1-1.2-.7V0.8Z" />
              </svg>
              Play preview
            </button>
          ) : (
            <button
              type="button"
              onClick={stopPlayback}
              className="qvs-btn qvs-btn-ghost h-9 px-3 text-[13px] hover:border-danger/60 hover:text-danger"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                <rect width="10" height="10" rx="1.5" />
              </svg>
              {mode === "preparing" ? "Cancel" : "Stop"}
            </button>
          )}
          <label
            className={`flex items-center gap-1.5 text-[12px] ${zonesForFormat ? "cursor-pointer text-ink-2" : "cursor-not-allowed text-ink-3/50"}`}
            title={zonesForFormat ? undefined : `${preset.label} has no platform UI safe zone — nothing to avoid`}
          >
            <input
              type="checkbox"
              checked={safeZone}
              onChange={toggleSafeZone}
              disabled={!zonesForFormat}
              className="h-3.5 w-3.5 accent-[var(--color-gold)]"
            />
            Safe zones
          </label>
          {safeZone ? (
            <div role="radiogroup" aria-label="Safe zone platform" className="flex overflow-hidden rounded-sm border border-line">
              {(Object.keys(SAFE_ZONES) as SafePlatform[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  role="radio"
                  aria-checked={platform === p}
                  onClick={() => choosePlatform(p)}
                  className={`px-2 py-1 text-[11px] font-medium ${platform === p ? "bg-line-strong text-ink" : "text-ink-2 hover:text-ink"}`}
                >
                  {SAFE_ZONES[p].label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {/* playback progress + notices */}
      {mode !== "static" && timeline ? (
        <div className="border-b border-line px-4 py-1.5">
          <div className="h-1 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-gold"
              style={{ width: `${Math.min(100, (elapsed / (timeline.total || 1)) * 100)}%` }}
            />
          </div>
          {mode === "preparing" ? (
            <p className="mt-1 text-[11px] text-ink-3" aria-live="polite">
              Preparing recitation audio — downloading and measuring each ayah…
            </p>
          ) : null}
          {timeline.estimated && mode === "playing" ? (
            <p className="mt-1 text-[11px] text-ink-3" role="status">
              Estimated pacing (audio unavailable: {playError}). Rendered video will use measured audio timing.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* stage */}
      <div ref={wrapRef} className="relative min-h-0 flex-1 overflow-hidden px-3 pb-0 pt-3 lg:px-5 lg:pt-4">
        {succeeded && job?.result ? (
          <ResultView job={job} onReset={onReset} />
        ) : (
          <div className="flex h-full items-end justify-center pb-0">
            <div
              className="relative overflow-hidden rounded-md border border-line"
              style={{ width: STAGE_W * scale, height: STAGE_H * scale, boxShadow: "var(--shadow-stage)" }}
            >
              <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", width: STAGE_W, height: STAGE_H }}>
                <VersePreview
                  surahMeta={surahMeta}
                  ayah={current}
                  translationText={translationText}
                  text={text}
                  bgEntry={bgEntry}
                  backgrounds={backgrounds}
                  bgSettings={bgSettings}
                  width={STAGE_W}
                  height={STAGE_H}
                  playhead={mode === "playing" ? elapsed : playhead}
                  audioDuration={audioDuration}
                  playing={mode === "playing"}
                />
              </div>
              {safeZone && zonesForFormat
                ? SAFE_ZONES[platform].boxes.map((z, i) => (
                    <div
                      key={i}
                      aria-hidden="true"
                      className="pointer-events-none absolute border border-dashed border-[#e08060] bg-[#e08060]/8"
                      style={{
                        top: z.top ? `${z.top}%` : undefined,
                        bottom: z.bottom ? `${z.bottom}%` : undefined,
                        insetInlineEnd: z.end ? `${z.end}%` : undefined,
                        insetInlineStart: z.start ? `${z.start}%` : undefined,
                        left: !z.start && !z.end ? 0 : undefined,
                        right: !z.start && !z.end ? 0 : undefined,
                        ...(z.top && !z.bottom ? { height: `${z.top}%`, top: 0 } : {}),
                        ...(z.bottom && !z.top ? { height: `${z.bottom}%`, bottom: 0 } : {}),
                      }}
                    >
                      {z.note ? (
                        <span className="absolute inset-x-0 top-1 text-center text-[10px] font-medium text-[#e08060]">
                          {z.note}
                        </span>
                      ) : null}
                    </div>
                  ))
                : null}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function ResultView({ job, onReset }: { job: JobSnapshot; onReset: () => void }) {
  const r = job.result!;
  return (
    <div className="scroll-thin flex h-full flex-col gap-4 overflow-y-auto">
      <div className="flex items-center gap-2 text-ok" role="status">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
          <path d="m5 8.2 2 2L11 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="text-[13.5px] font-medium">Video generated successfully</p>
      </div>
      <div className="mx-auto w-full max-w-[min(100%,380px)] overflow-hidden rounded-md border border-line bg-black">
        <video
          key={r.filename}
          src={r.url}
          controls
          playsInline
          className="block w-full"
          style={{ aspectRatio: r.resolution.replace("x", "/") }}
        />
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <a
          href={api.downloadUrl(job.id)}
          download={r.filename}
          className="qvs-btn qvs-btn-primary h-9 px-4"
        >
          Download MP4
        </a>
        {r.lightFilename && r.lightUrl && (
          <a
            href={r.lightUrl}
            download={r.lightFilename}
            className="inline-flex h-9 items-center rounded-sm border border-gold/50 bg-surface-2 px-4 text-[13px] font-medium text-gold transition-colors hover:bg-gold/15"
            title="Smaller 540-class copy — shares and plays better in WhatsApp and small windows"
          >
            Download Light · {r.lightResolution}
            {r.lightSizeBytes ? ` · ${(r.lightSizeBytes / 1024 / 1024).toFixed(1)} MB` : ""}
          </a>
        )}
        {r.dualFilename && r.dualUrl && (
          <a
            href={r.dualUrl}
            download={r.dualFilename}
            className="inline-flex h-9 items-center rounded-sm border border-line-strong bg-surface-2 px-4 text-[13px] font-medium text-ink-2 transition-colors hover:border-gold/60"
            title="One MP4 with BOTH video tracks — HD (default) + Light. Switch track manually in VLC: Video ▸ Video Track"
          >
            Download All-in-One
            {r.dualSizeBytes ? ` · ${(r.dualSizeBytes / 1024 / 1024).toFixed(1)} MB` : ""}
          </a>
        )}
        <button
          type="button"
          onClick={onReset}
          className="inline-flex h-9 items-center rounded-sm border border-line-strong bg-surface-2 px-4 text-[13px] font-medium text-ink transition-colors hover:border-gold/60"
        >
          Create Another
        </button>
      </div>
      <dl className="mx-auto grid w-full max-w-[520px] grid-cols-2 gap-x-6 gap-y-2 rounded-md border border-line bg-surface px-4 py-3 text-[12.5px] sm:grid-cols-3">
        <Meta label="Duration" value={`${r.duration.toFixed(1)}s`} />
        <Meta label="Resolution" value={r.resolution} />
        <Meta label="Size" value={`${(r.sizeBytes / 1024 / 1024).toFixed(1)} MB`} />
        <Meta label="Codecs" value={`${r.videoCodec} + ${r.audioCodec}`} />
        <Meta label="Frame rate" value="30 fps" />
        <Meta label="Ayahs" value={`${r.fromAyah}–${r.toAyah}`} />
      </dl>
      <p className="mx-auto max-w-[520px] text-[11px] leading-relaxed text-ink-3">
        Saved to <code className="text-ink-2">output/{r.filename}</code> · verse sync measured with ffprobe
        ({r.ayahSegments.length} segments)
      </p>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="tabular-nums text-ink">{value}</dd>
    </div>
  );
}
