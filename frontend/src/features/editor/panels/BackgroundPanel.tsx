import { useEffect, useRef, useState } from "react";
import type { BackgroundEntry, BackgroundSettings, StockItem } from "../../../types";
import { Segmented, SliderRow } from "../../../components/ui";
import { api } from "../../../lib/api";
import { searchOrientation } from "../../../lib/formats";
import { fmtDuration } from "../../../lib/time";
import { ensureClips, makeClip } from "../../../lib/bgTimeline";
import { isGoodMatch, itemOrientation, rankStockItems } from "../../../lib/stockRank";

const DEFAULTS = { brightness: 80, contrast: 100, saturation: 90, blur: 0, darkOverlay: 30 };

type LibraryTab = "library" | "upload" | "online";

const QUICK_QUERIES = [
  "ocean", "waves", "sunset", "sunrise", "clouds", "night sky", "stars", "moon",
  "mountains", "fog", "forest", "rain", "waterfall", "desert", "lake",
  "coast", "aerial", "nature", "space", "earth", "mosque", "islamic architecture",
];

function orientLabel(o: string | null | undefined): string {
  if (o === "portrait") return "Vertical";
  if (o === "landscape") return "Landscape";
  if (o === "square") return "Square";
  return "";
}

function thumbAspect(platform: string): string {
  const o = searchOrientation(platform);
  if (o === "landscape") return "aspect-video";
  if (o === "square") return "aspect-square";
  return "aspect-[9/16]";
}

function StockCardThumb({
  src,
  aspect,
  kind,
}: {
  src: string | null;
  aspect: string;
  kind: string;
}) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) {
    return (
      <div className={`flex ${aspect} w-full items-center justify-center text-[10px] text-ink-3`}>
        {kind}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      className={`${aspect} w-full object-cover`}
      onError={() => setBroken(true)}
    />
  );
}

export function BackgroundPanel({
  backgrounds,
  settings,
  onChange,
  onUpload,
  onDownload,
  platform,
  audioDuration,
}: {
  backgrounds: BackgroundEntry[];
  settings: BackgroundSettings;
  onChange: (patch: Partial<BackgroundSettings>) => void;
  onUpload: (file: File) => Promise<void>;
  onDownload: (item: StockItem) => Promise<BackgroundEntry>;
  platform: string;
  audioDuration: number | null;
}) {
  const [tab, setTab] = useState<LibraryTab>("library");
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [provider, setProvider] = useState<"pexels" | "pixabay">("pexels");
  const [mediaKind, setMediaKind] = useState<"image" | "video">("image");
  const [results, setResults] = useState<StockItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [downloadId, setDownloadId] = useState<string | null>(null);
  const [providers, setProviders] = useState<{ pexels: boolean; pixabay: boolean }>({ pexels: false, pixabay: false });
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLUListElement>(null);
  const scrollResultsRef = useRef(false);
  const targetOrient = searchOrientation(platform);
  const aspect = thumbAspect(platform);

  useEffect(() => {
    api.stockStatus().then((s) => setProviders(s.providers)).catch(() => undefined);
  }, []);

  useEffect(() => {
    setResults((prev) => (prev.length ? rankStockItems(prev, audioDuration, targetOrient) : prev));
  }, [audioDuration, targetOrient]);

  useEffect(() => {
    if (!scrollResultsRef.current || !results.length) return;
    scrollResultsRef.current = false;
    resultsRef.current?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [results]);

  const builtin = backgrounds.filter((b) => !b.uploaded);
  const uploaded = backgrounds.filter((b) => b.uploaded);
  const selected = backgrounds.find((b) => b.id === settings.id);

  const pick = (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    onUpload(file)
      .catch((e: Error) => setUploadError(e.message))
      .finally(() => setUploading(false));
  };

  const runSearch = async (q: string) => {
    const term = q.trim();
    if (!term) return;
    setSearching(true);
    setSearchError(null);
    setResults([]);
    setLastQuery(term);
    try {
      const d = await api.stockSearch(term, provider, targetOrient, mediaKind, audioDuration);
      const ranked = rankStockItems(d.items, audioDuration, targetOrient);
      scrollResultsRef.current = true;
      setResults(ranked);
      if (!ranked.length) setSearchError("No results — try another keyword.");
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    if (!lastQuery) return;
    void runSearch(lastQuery);
    // Refresh provider/format results; duration re-ranks locally without a refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platform, provider, mediaKind]);

  const downloadAndUse = async (item: StockItem) => {
    const key = `${item.provider}:${item.id}`;
    setDownloadId(key);
    setSearchError(null);
    try {
      await onDownload(item);
      setTab("library");
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloadId(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div role="tablist" aria-label="Background source" className="qvs-seg">
        {([
          ["library", "Local"],
          ["upload", "Upload"],
          ["online", "Online"],
        ] as [LibraryTab, string][]).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "library" ? (
        <div className="flex flex-col gap-2">
          <span className="text-[12px] font-medium tracking-wide text-ink-2">Background</span>
          {builtin.length + uploaded.length === 0 ? (
            <p className="rounded-sm border border-dashed border-line px-3 py-6 text-center text-[13px] text-ink-3">
              No local backgrounds yet. Upload a file or search Online.
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Background">
              {[...builtin, ...uploaded].map((b) => {
                const active = b.id === settings.id;
                return (
                  <div
                    key={b.id}
                    role="radio"
                    aria-checked={active}
                    tabIndex={0}
                    aria-label={
                      b.kind === "video" && b.duration
                        ? `${b.name}, ${fmtDuration(b.duration)}`
                        : b.name
                    }
                    onClick={() => onChange({ id: b.id, clips: [makeClip(b)] })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onChange({ id: b.id, clips: [makeClip(b)] });
                      }
                    }}
                    className={`group relative cursor-pointer overflow-hidden rounded-sm border text-start transition-colors ${
                      active ? "border-gold" : "border-line hover:border-line-strong"
                    }`}
                  >
                    {b.thumb ? (
                      <img src={b.thumb} alt="" className={`${aspect} w-full object-cover`} />
                    ) : (
                      <div className={`flex ${aspect} w-full items-center justify-center bg-surface-2 text-[10px] text-ink-3`}>
                        {b.kind}
                      </div>
                    )}
                    <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 pb-1 pt-4 text-[11px] font-medium text-ink">
                      {b.name}
                      {b.kind === "video" && b.duration ? (
                        <span className="ms-1 tabular-nums text-ink-2"> {fmtDuration(b.duration)}</span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      aria-label={`Add ${b.name} to timeline`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onChange({
                          id: b.id,
                          clips: [...ensureClips(settings, backgrounds), makeClip(b)],
                        });
                      }}
                      className="absolute end-1 top-1 rounded-xs bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-ink hover:bg-gold hover:text-canvas"
                    >
                      Add
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          {selected?.uploaded ? (
            <p className="text-[12px] text-ink-3">
              Uploaded background{selected.duration ? ` · ${fmtDuration(selected.duration)} source` : ""}
              {selected.kind === "video" ? " · loops if shorter than the recitation" : ""}
            </p>
          ) : null}
          {selected && !selected.uploaded && selected.id.startsWith("stock-") ? (
            <p className="text-[12px] text-ink-3">
              From the online library · saved permanently to your local backgrounds
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "upload" ? (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex h-40 w-full flex-col items-center justify-center gap-2 rounded-sm border border-dashed border-line-strong text-ink-3 transition-colors hover:border-gold/70 hover:text-gold"
            aria-label="Upload background (MP4, WebM, JPG, PNG)"
            disabled={uploading}
          >
            <svg width="20" height="20" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 11V3m0 0L5 6m3-3 3 3M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[13px] font-medium">{uploading ? "Uploading…" : "Choose file"}</span>
            <span className="text-[12px]">MP4 · WebM · JPG · PNG · up to 200 MB</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="video/mp4,video/webm,image/jpeg,image/png"
            className="hidden"
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {uploadError ? (
            <p className="text-[13px] text-danger" role="alert">{uploadError}</p>
          ) : null}
        </div>
      ) : null}

      {tab === "online" ? (
        <div className="flex flex-col gap-3">
          <p className="text-[12px] leading-relaxed text-ink-3">
            Search free stock media (Pexels &amp; Pixabay). Download &amp; add to timeline saves it to your library and the background track.
            {audioDuration && mediaKind === "video" ? (
              <span className="mt-1 block">
                Sorted for {fmtDuration(audioDuration)} of recitation — clips at or above that length first.
              </span>
            ) : (
              <span className="mt-1 block">
                Preferring {orientLabel(targetOrient).toLowerCase()} frames for {searchOrientation(platform) === "landscape" ? "16:9" : searchOrientation(platform) === "square" ? "1:1" : "9:16"} export.
              </span>
            )}
            {!providers.pexels && !providers.pixabay ? (
              <span className="mt-1 block text-danger">
                API keys not configured — add them to <code>data/stock_keys.json</code> or set
                PEXELS_API_KEY / PIXABAY_API_KEY, then restart the backend.
              </span>
            ) : null}
          </p>
          <form
            className="flex gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              runSearch(query);
            }}
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${mediaKind === "image" ? "photos" : "videos"}…`}
              aria-label="Search online backgrounds"
              className="qvs-input flex-1"
            />
            <button
              type="submit"
              disabled={searching || !query.trim()}
              className="qvs-btn qvs-btn-primary shrink-0 px-3.5"
            >
              {searching ? "Searching…" : "Search"}
            </button>
          </form>
          <div className="flex flex-col gap-2">
            <Segmented
              ariaLabel="Stock provider"
              value={provider}
              onChange={(v) => setProvider(v as "pexels" | "pixabay")}
              options={[
                { value: "pexels", label: "Pexels" },
                { value: "pixabay", label: "Pixabay" },
              ]}
            />
            <Segmented
              ariaLabel="Media type"
              value={mediaKind}
              onChange={(v) => setMediaKind(v as "image" | "video")}
              options={[
                { value: "image", label: "Photos" },
                { value: "video", label: "Videos" },
              ]}
            />
          </div>
          {results.length ? null : (
            <div className="flex flex-wrap gap-1.5" aria-label="Quick searches">
              {QUICK_QUERIES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => {
                    setQuery(q);
                    runSearch(q);
                  }}
                  className="min-h-8 rounded-xs border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink-2 transition-colors hover:border-gold/60 hover:text-ink"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
          {searching ? (
            <p className="text-[12px] text-ink-3" aria-live="polite">Searching…</p>
          ) : null}
          {searchError ? (
            <p className="text-[13px] text-danger" role="alert">{searchError}</p>
          ) : null}
          {results.length ? (
            <ul ref={resultsRef} className="grid grid-cols-2 gap-2" aria-label="Search results">
              {results.map((item) => {
                const key = `${item.provider}:${item.id}`;
                const busy = downloadId === key;
                const orient = itemOrientation(item);
                const good = isGoodMatch(item, audioDuration, targetOrient);
                const title = item.author ? item.author : item.name;
                return (
                  <li key={key} className="overflow-hidden rounded-sm border border-line bg-surface-2">
                    <div className="relative">
                      <StockCardThumb src={item.thumb} aspect={aspect} kind={item.kind} />
                      {item.kind === "video" && item.duration ? (
                        <span className="absolute end-1.5 bottom-1.5 rounded-xs bg-black/70 px-1.5 py-0.5 text-[11px] tabular-nums text-ink">
                          {fmtDuration(item.duration)}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex flex-col gap-1.5 px-2 py-2">
                      <div className="flex items-baseline justify-between gap-1">
                        <span className="truncate text-[12px] text-ink">{title}</span>
                        {good ? (
                          <span className="shrink-0 text-[10px] font-medium tracking-wide text-gold">Good Match</span>
                        ) : null}
                      </div>
                      <span className="truncate text-[11px] text-ink-3">
                        {item.provider}
                        {orient ? ` · ${orientLabel(orient)}` : ""}
                      </span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => downloadAndUse(item)}
                        aria-label={
                          item.kind === "video" && item.duration
                            ? `Download and add ${title} to the timeline, ${fmtDuration(item.duration)}`
                            : `Download and add ${title} to the timeline`
                        }
                        className="qvs-btn qvs-btn-primary h-8 text-[12px]"
                      >
                        {busy ? "Downloading…" : "Download & add to timeline"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-4 border-t border-line pt-4">
        <div className="flex items-center justify-between">
          <span className="qvs-kicker">Adjustments</span>
          <button
            type="button"
            onClick={() => onChange({ ...DEFAULTS })}
            className="text-[12px] text-ink-3 underline-offset-2 hover:text-gold hover:underline"
          >
            Reset all
          </button>
        </div>
        <SliderRow label="Brightness" unit="%" value={settings.brightness} min={20} max={150}
          onChange={(v) => onChange({ brightness: v })} />
        <SliderRow label="Contrast" unit="%" value={settings.contrast} min={20} max={200}
          onChange={(v) => onChange({ contrast: v })} />
        <SliderRow label="Saturation" unit="%" value={settings.saturation} min={0} max={200}
          onChange={(v) => onChange({ saturation: v })} />
        <SliderRow label="Blur" unit="px" value={settings.blur} min={0} max={40}
          onChange={(v) => onChange({ blur: v })} />
        <SliderRow label="Dark overlay" unit="%" value={settings.darkOverlay} min={0} max={90}
          onChange={(v) => onChange({ darkOverlay: v })} />
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-ink-2">Position</span>
          <Segmented
            ariaLabel="Background position"
            value={settings.position}
            onChange={(v) => onChange({ position: v })}
            options={[
              { value: "top", label: "Top" },
              { value: "center", label: "Center" },
              { value: "bottom", label: "Bottom" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
