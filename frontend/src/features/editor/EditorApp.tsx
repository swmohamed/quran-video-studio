import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AudioDuration,
  Ayah,
  BackgroundEntry,
  EditorSettings,
  FontCatalog,
  HealthReport,
  JobSnapshot,
  Preset,
  Reciter,
  StockItem,
  SurahMeta,
  TranslationMeta,
} from "../../types";
import { api } from "../../lib/api";
import { applyPreset, loadSettings, saveSettings } from "../../lib/settings";
import { PLATFORM_ORDER, PLATFORM_PRESETS, platformPreset } from "../../lib/formats";
import { ayahIndexAtTime, ensureClips, makeClip, timeAtAyahIndex, timelineFromDuration } from "../../lib/bgTimeline";
import { prefetchQpcPages } from "../../lib/qpcFonts";
import { fmtDuration } from "../../lib/time";
import { LogoMark } from "../../components/Logo";
import { PreviewStage } from "./PreviewStage";
import { BackgroundTimeline } from "./BackgroundTimeline";
import { ContentPanel } from "./panels/ContentPanel";
import { BackgroundPanel } from "./panels/BackgroundPanel";
import { TextPanel } from "./panels/TextPanel";

type Tab = "content" | "background" | "text";

const POLL_MS = 500;

export function EditorApp() {
  const [settings, setSettings] = useState<EditorSettings>(() => loadSettings());
  const [surahs, setSurahs] = useState<SurahMeta[]>([]);
  const [ayahs, setAyahs] = useState<Ayah[]>([]);
  const [reciters, setReciters] = useState<Reciter[]>([]);
  const [translations, setTranslations] = useState<TranslationMeta[]>([]);
  const [backgrounds, setBackgrounds] = useState<BackgroundEntry[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [fonts, setFonts] = useState<FontCatalog | undefined>();
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [tab, setTab] = useState<Tab>("content");
  const [previewIndex, setPreviewIndex] = useState(0);
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [starting, setStarting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [audioDur, setAudioDur] = useState<AudioDuration | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [seekGeneration, setSeekGeneration] = useState(0);
  const pollRef = useRef<number | null>(null);

  // ---- data loading ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, s, r, t, b, p, f] = await Promise.all([
          api.health(),
          api.surahs(),
          api.reciters(),
          api.translations(),
          api.backgrounds(),
          api.presets(),
          api.fonts(),
        ]);
        if (cancelled) return;
        setHealth(h);
        setSurahs(s.surahs);
        setReciters(r.reciters);
        setTranslations(t.translations);
        setBackgrounds(b.backgrounds);
        setPresets(p.presets);
        setFonts(f);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // verse text for current surah
  useEffect(() => {
    let cancelled = false;
    setAyahs([]);
    api
      .surah(settings.surah)
      .then((d) => {
        if (!cancelled) setAyahs(d.ayahs);
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(`Could not load verses: ${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, [settings.surah]);

  // persist settings
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  // selected recitation length — drives background ranking
  useEffect(() => {
    let cancelled = false;
    const handle = window.setTimeout(() => {
      api
        .audioDuration({
          surah: settings.surah,
          fromAyah: settings.fromAyah,
          toAyah: settings.toAyah,
          reciter: settings.reciter,
        })
        .then((d) => {
          if (!cancelled) setAudioDur(d);
        })
        .catch(() => {
          if (!cancelled) setAudioDur(null);
        });
    }, 280);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [settings.surah, settings.fromAyah, settings.toAyah, settings.reciter]);

  // persist a single-clip timeline from the current background id
  useEffect(() => {
    if (!backgrounds.length) return;
    setSettings((s) => {
      if (s.background.clips?.length) return s;
      const entry = backgrounds.find((b) => b.id === s.background.id);
      if (!entry) return s;
      return { ...s, background: { ...s.background, clips: [makeClip(entry)] } };
    });
  }, [backgrounds]);

  // keep range valid for surah; keep preview index in range
  const surahMeta = useMemo(() => surahs.find((s) => s.number === settings.surah), [surahs, settings.surah]);
  const lastSurahRef = useRef<number | null>(null);
  useEffect(() => {
    if (!surahMeta) return;
    const prev = lastSurahRef.current;
    lastSurahRef.current = settings.surah;
    const max = surahMeta.ayahCount;
    if (prev !== null && prev !== settings.surah) {
      // user switched surah: offer its opening verses
      setSettings((s) => ({ ...s, fromAyah: 1, toAyah: Math.min(7, max) }));
    } else {
      // first mount with persisted settings (or same surah): just clamp
      setSettings((s) => {
        const fromAyah = Math.min(s.fromAyah, max);
        const toAyah = Math.min(Math.max(s.toAyah, fromAyah), max);
        return fromAyah === s.fromAyah && toAyah === s.toAyah ? s : { ...s, fromAyah, toAyah };
      });
    }
  }, [settings.surah, surahMeta?.ayahCount]);

  const selectedAyahs = useMemo(
    () => ayahs.filter((a) => a.ayah >= settings.fromAyah && a.ayah <= settings.toAyah),
    [ayahs, settings.fromAyah, settings.toAyah],
  );
  useEffect(() => {
    prefetchQpcPages(selectedAyahs.map((a) => a.qpcMarker?.page));
  }, [selectedAyahs]);
  useEffect(() => {
    setPreviewIndex((i) => Math.min(Math.max(0, i), Math.max(0, selectedAyahs.length - 1)));
  }, [selectedAyahs.length]);

  const activeTranslation = translations.find((t) => t.id === settings.translation);
  const translationText = useMemo(() => {
    if (!activeTranslation?.languageCode) return null;
    const a = selectedAyahs[previewIndex];
    return a ? (a.translations[activeTranslation.languageCode] ?? null) : null;
  }, [activeTranslation, selectedAyahs, previewIndex]);

  const bgEntry = useMemo(
    () => backgrounds.find((b) => b.id === settings.background.id),
    [backgrounds, settings.background.id],
  );

  // ---- mutations ----
  const patch = useCallback((p: Partial<EditorSettings>) => setSettings((s) => ({ ...s, ...p })), []);
  const patchBg = useCallback(
    (p: Partial<EditorSettings["background"]>) =>
      setSettings((s) => ({ ...s, background: { ...s.background, ...p } })),
    [],
  );
  const patchText = useCallback(
    (p: Partial<EditorSettings["text"]>) => setSettings((s) => ({ ...s, text: { ...s.text, ...p } })),
    [],
  );

  const onFrom = (n: number) =>
    setSettings((s) => ({ ...s, fromAyah: n, toAyah: Math.max(n, s.toAyah) }));
  const onTo = (n: number) =>
    setSettings((s) => ({ ...s, toAyah: n, fromAyah: Math.min(n, s.fromAyah) }));

  const syncIndexFromTime = useCallback((t: number, dur: AudioDuration | null) => {
    const tl = dur ? timelineFromDuration(dur) : null;
    if (tl) setPreviewIndex(ayahIndexAtTime(tl, t));
  }, []);

  const seekPlayhead = useCallback((t: number) => {
    const next = Math.max(0, t);
    setPlayhead(next);
    setSeekGeneration((g) => g + 1);
    syncIndexFromTime(next, audioDur);
  }, [audioDur, syncIndexFromTime]);

  const onPreviewAyah = useCallback((i: number) => {
    setPreviewIndex(i);
    const tl = audioDur ? timelineFromDuration(audioDur) : null;
    if (tl) setPlayhead(timeAtAyahIndex(tl, i));
  }, [audioDur]);

  const onUpload = async (file: File) => {
    const entry = await api.uploadBackground(file);
    setBackgrounds((prev) => {
      setSettings((s) => ({
        ...s,
        background: {
          ...s.background,
          id: entry.id,
          clips: [...ensureClips(s.background, prev), makeClip(entry)],
        },
      }));
      return [...prev, entry];
    });
  };

  const onStockDownload = async (item: StockItem) => {
    const entry = await api.stockDownload(item); // backend saves + ffprobe-validates
    setBackgrounds((prev) => {
      const next = prev.some((b) => b.id === entry.id) ? prev : [...prev, entry];
      setSettings((s) => ({
        ...s,
        background: {
          ...s.background,
          id: entry.id,
          clips: [...ensureClips(s.background, prev), makeClip(entry)],
        },
      }));
      return next;
    });
    return entry;
  };

  // ---- render job ----
  const canRender =
    !!surahMeta &&
    selectedAyahs.length > 0 &&
    selectedAyahs.length <= 30 &&
    health?.ffmpeg.ok &&
    health?.dataOk &&
    (!bgEntry || true);

  const startRender = async () => {
    setStarting(true);
    setJob(null);
    try {
      const { jobId } = await api.render(settings);
      setJob({ id: jobId, state: "queued", stage: "Queued", progress: 0, detail: "", error: null, result: null });
      const poll = window.setInterval(async () => {
        try {
          const snap = await api.job(jobId);
          setJob(snap);
          if (snap.state !== "queued" && snap.state !== "running") {
            window.clearInterval(poll);
            setStarting(false);
          }
        } catch (e) {
          window.clearInterval(poll);
          setStarting(false);
          setJob({
            id: jobId, state: "failed", stage: "Lost contact", progress: 0,
            detail: "", error: e instanceof Error ? e.message : String(e), result: null,
          });
        }
      }, POLL_MS);
      pollRef.current = poll;
    } catch (e) {
      setStarting(false);
      setJob({
        id: "?", state: "failed", stage: "Could not start", progress: 0, detail: "",
        error: e instanceof Error ? e.message : String(e), result: null,
      });
    }
  };

  const cancelRender = async () => {
    if (!job || !job.id || job.id === "?") return;
    try {
      await api.cancelJob(job.id);
    } catch {
      /* job may have finished */
    }
  };

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  const busy = job?.state === "queued" || job?.state === "running";

  const surahLabel = surahMeta
    ? `${surahMeta.englishName} · ${surahMeta.number} · ${settings.fromAyah}–${settings.toAyah}`
    : "";
  const reciterLabel = reciters.find((r) => r.id === settings.reciter)?.name ?? settings.reciter;
  const fmt = platformPreset(settings.platform);

  const durationLabel = audioDur
    ? `${fmtDuration(audioDur.duration)}${audioDur.estimated ? " est." : ""}`
    : null;
  const orientLabel =
    fmt.orientation === "portrait" ? "Vertical" : fmt.orientation === "landscape" ? "Landscape" : "Square";

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <a href="#preview" className="skip-link">Skip to preview</a>
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-3 lg:h-14 lg:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <LogoMark className="h-9 w-9 shrink-0 text-gold" title="Quran Video Studio" />
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-[13px] font-semibold tracking-wide text-ink lg:text-[14px]">
              Quran Video Studio
            </h1>
            <p className="hidden truncate text-[12px] text-ink-3 sm:block">
              {fmt.label} · {fmt.width}×{fmt.height} · {fmt.aspect}
            </p>
          </div>
        </div>
        <div className="ms-auto flex items-center gap-3 text-[12px] text-ink-3">
          <SystemStatus health={health} />
        </div>
      </header>

      {health && !health.ffmpeg.ok ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px] text-danger">
          FFmpeg was not found — video export is unavailable.{" "}
          {health.ffmpeg.error ?? "Install it (e.g. winget install Gyan.FFmpeg), then restart the app."}
        </div>
      ) : null}
      {health && !health.dataOk ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px] text-danger">
          Quran text cache missing — {health.dataError}
        </div>
      ) : null}
      {loadError ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[13px] text-danger">
          {loadError} — is the backend running on port 8000?
        </div>
      ) : null}

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="flex min-h-0 min-w-0 flex-col lg:min-h-0 lg:flex-1">
          <PreviewStage
            surahMeta={surahMeta}
            ayahs={selectedAyahs}
            previewIndex={previewIndex}
            onPreviewIndexChange={onPreviewAyah}
            translationText={translationText}
            text={settings.text}
            bgEntry={bgEntry}
            backgrounds={backgrounds}
            bgSettings={settings.background}
            playhead={playhead}
            audioDuration={audioDur?.duration ?? 0}
            onPlayhead={setPlayhead}
            seekGeneration={seekGeneration}
            job={job}
            onReset={() => setJob(null)}
            selection={{
              surah: settings.surah,
              fromAyah: settings.fromAyah,
              toAyah: settings.toAyah,
              reciter: settings.reciter,
            }}
            platform={settings.platform}
          />
          <BackgroundTimeline
            backgrounds={backgrounds}
            settings={settings.background}
            onChange={patchBg}
            audioDuration={audioDur?.duration ?? null}
            playhead={playhead}
            onSeek={seekPlayhead}
            onOpenLibrary={() => setTab("background")}
          />
        </div>

        <aside
          className="flex min-h-0 w-full flex-1 flex-col border-t border-line bg-surface lg:w-[23.5rem] lg:flex-none lg:border-s lg:border-t-0 xl:w-[25rem]"
          aria-label="Video settings"
        >
          <div className="border-b border-line px-4 py-2.5">
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <h2 className="qvs-kicker">Video format</h2>
              <span className="text-[12px] text-ink-3">{orientLabel}</span>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <select
                value={settings.platform}
                onChange={(e) => patch({ platform: e.target.value })}
                aria-label="Video format"
                className="qvs-input min-w-0 flex-1"
              >
                {PLATFORM_ORDER.map((p) => {
                  const m = PLATFORM_PRESETS[p];
                  const orient =
                    m.orientation === "portrait" ? "Vertical" :
                    m.orientation === "landscape" ? "Landscape" : "Square";
                  return (
                    <option key={p} value={p}>
                      {m.label} · {m.width}×{m.height} · {m.aspect} · {orient}
                    </option>
                  );
                })}
              </select>
              <select
                value={settings.resolution}
                onChange={(e) => patch({ resolution: e.target.value as "light" | "fhd" | "uhd" })}
                aria-label="Export resolution"
                title="Light: best for small players/WhatsApp · 4K: best when enlarged on big screens"
                className="qvs-input sm:w-[9.5rem] sm:flex-none"
              >
                <option value="light">{Math.round(fmt.width / 2)}×{Math.round(fmt.height / 2)} · Light</option>
                <option value="fhd">{fmt.width}×{fmt.height}</option>
                <option value="uhd">{fmt.width * 2}×{fmt.height * 2} · 4K</option>
              </select>
            </div>
            {settings.resolution !== "light" && (
              <label className="mt-2 flex min-h-8 cursor-pointer select-none items-center gap-2" title="Also save a smaller copy — looks better than shrinking the big file in WhatsApp or small players">
                <input
                  type="checkbox"
                  checked={settings.withLight}
                  onChange={(e) => patch({ withLight: e.target.checked })}
                  className="h-3.5 w-3.5 accent-gold"
                />
                <span className="text-[12px] text-ink-2">
                  Also export Light copy · {Math.round(fmt.width / 2)}×{Math.round(fmt.height / 2)}
                </span>
              </label>
            )}
            <div className="mt-2 flex items-center gap-2">
              <span className="shrink-0 text-[12px] text-ink-3">Quality</span>
              <div role="radiogroup" aria-label="Export quality" className="qvs-seg flex-1">
                {([
                  ["small", "Small file"],
                  ["high", "Standard"],
                  ["max", "Best"],
                ] as ["small" | "high" | "max", string][]).map(([q, label]) => (
                  <button
                    key={q}
                    type="button"
                    role="radio"
                    aria-checked={settings.quality === q}
                    title={
                      q === "small"
                        ? "Smaller file — still tuned to keep the text clean"
                        : q === "max"
                          ? "Maximum quality (larger file, slower render)"
                          : "Balanced quality and size (recommended)"
                    }
                    onClick={() => patch({ quality: q })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <h2 className="qvs-kicker mt-3 mb-1.5">Style preset</h2>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Style preset">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={false}
                  title={p.description}
                  onClick={() => setSettings((s) => applyPreset(s, p))}
                  className="min-h-8 rounded-xs border border-line bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-ink-2 transition-colors hover:border-gold/60 hover:text-ink"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          <div className="border-b border-line px-4 py-2">
            <div role="tablist" aria-label="Settings sections" className="qvs-seg">
              {([
                ["content", "Content"],
                ["background", "Background"],
                ["text", "Text"],
              ] as [Tab, string][]).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  id={`tab-${id}`}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div
            className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4"
          >
            <div
              role="tabpanel"
              aria-labelledby="tab-content"
              hidden={tab !== "content"}
            >
              <ContentPanel
                surahs={surahs}
                surah={settings.surah}
                onSurah={(n) => patch({ surah: n })}
                fromAyah={settings.fromAyah}
                toAyah={settings.toAyah}
                onFrom={onFrom}
                onTo={onTo}
                ayahCount={surahMeta?.ayahCount ?? Math.max(settings.toAyah, settings.fromAyah, 1)}
                reciters={reciters}
                reciter={settings.reciter}
                onReciter={(id) => patch({ reciter: id })}
                translations={translations}
                translation={settings.translation}
                onTranslation={(id) => patch({ translation: id })}
                audioDuration={audioDur}
              />
            </div>
            <div
              role="tabpanel"
              aria-labelledby="tab-background"
              hidden={tab !== "background"}
            >
              <BackgroundPanel
                backgrounds={backgrounds}
                settings={settings.background}
                onChange={patchBg}
                onUpload={onUpload}
                onDownload={onStockDownload}
                platform={settings.platform}
                audioDuration={audioDur?.duration ?? null}
              />
            </div>
            <div
              role="tabpanel"
              aria-labelledby="tab-text"
              hidden={tab !== "text"}
            >
              <TextPanel
                text={settings.text}
                onChange={patchText}
                fonts={fonts}
              />
            </div>
          </div>

          <div className="border-t border-line bg-surface px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <div className="mb-2 flex items-baseline justify-between gap-2 text-[12px] text-ink-3">
              <span className="truncate">{surahLabel}</span>
              <span className="shrink-0 tabular-nums">
                {durationLabel ? `${durationLabel} · ` : ""}
                {reciterLabel}
              </span>
            </div>
            {busy ? (
              <div className="flex flex-col gap-2">
                <div
                  className="h-1.5 w-full overflow-hidden rounded-full bg-line"
                  role="progressbar"
                  aria-valuenow={Math.round((job?.progress ?? 0) * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Render progress"
                >
                  <div
                    className="h-full rounded-full bg-gold transition-[width] duration-300"
                    style={{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <p aria-live="polite" className="truncate text-[13px] text-ink">
                    {job?.stage} — {Math.round((job?.progress ?? 0) * 100)}%
                    {job?.detail ? <span className="text-ink-3"> · {job.detail}</span> : null}
                  </p>
                  <button
                    type="button"
                    onClick={cancelRender}
                    className="qvs-btn qvs-btn-ghost h-8 shrink-0 px-2.5 text-[12px] hover:border-danger/60 hover:text-danger"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                disabled={!canRender || starting}
                onClick={startRender}
                aria-busy={starting}
                className="qvs-btn qvs-btn-primary h-11 w-full text-[14px]"
              >
                {starting ? "Starting…" : job?.state === "failed" ? "Retry Render" : "Generate Video"}
              </button>
            )}
            {job?.state === "failed" && job.error ? (
              <p role="alert" className="mt-2 break-words text-[12px] leading-snug text-danger">
                {job.error}
              </p>
            ) : null}
            {job?.state === "canceled" ? (
              <p className="mt-2 text-[12px] text-ink-3">Render canceled.</p>
            ) : null}
          </div>
        </aside>
      </main>
    </div>
  );
}

function SystemStatus({ health }: { health: HealthReport | null }) {
  if (!health) return <span>checking system…</span>;
  const items: [string, boolean][] = [
    ["FFmpeg", health.ffmpeg.ok],
    ["Quran data", health.dataOk],
  ];
  return (
    <>
      {items.map(([label, ok]) => (
        <span
          key={label}
          className="flex items-center gap-1"
          aria-label={`${label} ${ok ? "ready" : "unavailable"}`}
        >
          <span aria-hidden="true" className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : "bg-danger"}`} />
          <span aria-hidden="true">{label}</span>
        </span>
      ))}
    </>
  );
}
