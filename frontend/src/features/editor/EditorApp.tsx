import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
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
import { PreviewStage } from "./PreviewStage";
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

  const onUpload = async (file: File) => {
    const entry = await api.uploadBackground(file);
    setBackgrounds((prev) => [...prev, entry]);
    patchBg({ id: entry.id });
  };

  const onStockDownload = async (item: StockItem) => {
    const entry = await api.stockDownload(item); // backend saves + ffprobe-validates
    setBackgrounds((prev) => (prev.some((b) => b.id === entry.id) ? prev : [...prev, entry]));
    patchBg({ id: entry.id });
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

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <div className="flex flex-col leading-tight">
            <span className="text-[14px] font-semibold tracking-wide">Quran Video Studio</span>
            <span className="text-[10.5px] text-ink-3">
              {fmt.label} · {fmt.width} × {fmt.height} · {fmt.aspect}
            </span>
          </div>
        </div>
        <div className="ms-auto flex items-center gap-3 text-[11px] text-ink-3">
          <SystemStatus health={health} />
        </div>
      </header>

      {health && !health.ffmpeg.ok ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[12.5px] text-danger">
          FFmpeg was not found — video export is unavailable.{" "}
          {health.ffmpeg.error ?? "Install it (e.g. winget install Gyan.FFmpeg), then restart the app."}
        </div>
      ) : null}
      {health && !health.dataOk ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[12.5px] text-danger">
          Quran text cache missing — {health.dataError}
        </div>
      ) : null}
      {loadError ? (
        <div role="alert" className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[12.5px] text-danger">
          {loadError} — is the backend running on port 8000?
        </div>
      ) : null}

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <PreviewStage
          surahMeta={surahMeta}
          ayahs={selectedAyahs}
          previewIndex={previewIndex}
          onPreviewIndexChange={setPreviewIndex}
          translationText={translationText}
          text={settings.text}
          bgEntry={bgEntry}
          bgSettings={settings.background}
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

        {/* settings column */}
        <aside
          className="flex min-h-0 w-full shrink-0 flex-col border-t border-line lg:w-[400px] lg:border-s lg:border-t-0"
          aria-label="Video settings"
        >
          {/* video format + style presets */}
          <div className="border-b border-line px-4 py-3">
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">Video format</h2>
              <span className="text-[10.5px] text-ink-3">{fmt.orientation}</span>
            </div>
            <div className="flex gap-1.5">
              <select
                value={settings.platform}
                onChange={(e) => patch({ platform: e.target.value })}
                aria-label="Video format"
                className="h-9 min-w-0 flex-1 rounded-sm border border-line bg-surface-2 px-2.5 text-[12.5px] text-ink outline-none focus:border-gold/60"
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
                className="h-9 shrink-0 rounded-sm border border-line bg-surface-2 px-2 text-[12.5px] text-ink outline-none focus:border-gold/60"
              >
                <option value="light">{Math.round(fmt.width / 2)}×{Math.round(fmt.height / 2)} · Light</option>
                <option value="fhd">{fmt.width}×{fmt.height}</option>
                <option value="uhd">{fmt.width * 2}×{fmt.height * 2} · 4K</option>
              </select>
            </div>
            {settings.resolution !== "light" && (
              <label className="mt-1.5 flex cursor-pointer select-none items-center gap-2" title="Also save a smaller 540×960 version — looks better than shrinking the big file in WhatsApp or small players">
                <input
                  type="checkbox"
                  checked={settings.withLight}
                  onChange={(e) => patch({ withLight: e.target.checked })}
                  className="h-3.5 w-3.5 accent-gold"
                />
                <span className="text-[11.5px] text-ink-2">
                  Also export Light copy · {Math.round(fmt.width / 2)}×{Math.round(fmt.height / 2)} (WhatsApp)
                </span>
              </label>
            )}
            <div className="mt-1.5 flex items-center gap-1.5">
              <span className="text-[10.5px] text-ink-3">Quality</span>
              <div role="radiogroup" aria-label="Export quality" className="flex flex-1 overflow-hidden rounded-sm border border-line">
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
                    className={`flex-1 px-2 py-1 text-[11px] font-medium ${
                      settings.quality === q ? "bg-line-strong text-ink" : "text-ink-2 hover:text-ink"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="mb-2 mt-4 flex items-baseline justify-between">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-3">Style preset</h2>
            </div>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Style preset">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={false}
                  title={p.description}
                  onClick={() => setSettings((s) => applyPreset(s, p))}
                  className="rounded-xs border border-line bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-ink-2 transition-colors hover:border-gold/60 hover:text-ink"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          {/* tabs */}
          <div className="border-b border-line px-4 py-2" role="tablist" aria-label="Settings sections">
            <div className="flex h-9 items-stretch rounded-sm border border-line bg-surface-2 p-0.5">
              {([
                ["content", "Content"],
                ["background", "Background"],
                ["text", "Text"],
              ] as [Tab, string][]).map(([id, label]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                  className={`flex-1 rounded-xs text-[12.5px] font-medium transition-colors ${
                    tab === id ? "bg-line-strong text-ink" : "text-ink-2 hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {tab === "content" ? (
              <ContentPanel
                surahs={surahs}
                surah={settings.surah}
                onSurah={(n) => patch({ surah: n })}
                fromAyah={settings.fromAyah}
                toAyah={settings.toAyah}
                onFrom={onFrom}
                onTo={onTo}
                ayahCount={surahMeta?.ayahCount ?? 7}
                reciters={reciters}
                reciter={settings.reciter}
                onReciter={(id) => patch({ reciter: id })}
                translations={translations}
                translation={settings.translation}
                onTranslation={(id) => patch({ translation: id })}
              />
            ) : null}
            {tab === "background" ? (
              <BackgroundPanel
                backgrounds={backgrounds}
                settings={settings.background}
                onChange={patchBg}
                onUpload={onUpload}
                onDownload={onStockDownload}
                platform={settings.platform}
              />
            ) : null}
            {tab === "text" ? (
              <TextPanel
                text={settings.text}
                onChange={patchText}
                fonts={fonts}
              />
            ) : null}
          </div>

          {/* render bar */}
          <div className="border-t border-line bg-surface px-4 py-3">
            <div className="mb-2 flex items-baseline justify-between gap-2 text-[11.5px] text-ink-3">
              <span className="truncate">{surahLabel}</span>
              <span className="shrink-0">{reciterLabel}</span>
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
                  <p aria-live="polite" className="truncate text-[12px] text-ink">
                    {job?.stage} — {Math.round((job?.progress ?? 0) * 100)}%
                    {job?.detail ? <span className="text-ink-3"> · {job.detail}</span> : null}
                  </p>
                  <button
                    type="button"
                    onClick={cancelRender}
                    className="shrink-0 rounded-xs border border-line-strong px-2.5 py-1 text-[11.5px] text-ink-2 hover:border-danger/60 hover:text-danger"
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
                className="h-10 w-full rounded-sm bg-gold text-[13.5px] font-semibold text-gold-ink transition-colors hover:bg-gold-strong disabled:cursor-not-allowed disabled:opacity-50"
              >
                {starting ? "Starting…" : job?.state === "failed" ? "Retry Render" : "Generate Video"}
              </button>
            )}
            {job?.state === "failed" && job.error ? (
              <p role="alert" className="mt-2 break-words text-[11.5px] leading-snug text-danger">
                {job.error}
              </p>
            ) : null}
            {job?.state === "canceled" ? (
              <p className="mt-2 text-[11.5px] text-ink-3">Render canceled.</p>
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
        <span key={label} className="flex items-center gap-1">
          <span aria-hidden="true" className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : "bg-danger"}`} />
          <span className="sr-only">{label}: </span>
          {label}
        </span>
      ))}
    </>
  );
}
