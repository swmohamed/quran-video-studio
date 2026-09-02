import { useEffect, useRef, useState } from "react";
import type { BackgroundEntry, BackgroundSettings, StockItem } from "../../../types";
import { Segmented, SliderRow } from "../../../components/ui";
import { api } from "../../../lib/api";
import { searchOrientation } from "../../../lib/formats";

const DEFAULTS = { brightness: 80, contrast: 100, saturation: 90, blur: 0, darkOverlay: 30 };

type LibraryTab = "library" | "upload" | "online";

const QUICK_QUERIES = [
  "ocean", "waves", "sunset", "clouds", "night sky", "stars", "moon",
  "mountains", "fog", "forest", "rain", "waterfall", "desert", "nature", "mosque",
];

export function BackgroundPanel({
  backgrounds,
  settings,
  onChange,
  onUpload,
  onDownload,
  platform,
}: {
  backgrounds: BackgroundEntry[];
  settings: BackgroundSettings;
  onChange: (patch: Partial<BackgroundSettings>) => void;
  onUpload: (file: File) => Promise<void>;
  onDownload: (item: StockItem) => Promise<BackgroundEntry>;
  platform: string;
}) {
  const [tab, setTab] = useState<LibraryTab>("library");
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // --- online library state ---
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<"pexels" | "pixabay">("pexels");
  const [mediaKind, setMediaKind] = useState<"image" | "video">("image");
  const [results, setResults] = useState<StockItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [downloadId, setDownloadId] = useState<string | null>(null);
  const [providers, setProviders] = useState<{ pexels: boolean; pixabay: boolean }>({ pexels: false, pixabay: false });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.stockStatus().then((s) => setProviders(s.providers)).catch(() => undefined);
  }, []);

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
    try {
      const d = await api.stockSearch(term, provider, searchOrientation(platform), mediaKind);
      setResults(d.items);
      if (!d.items.length) setSearchError("No results — try another keyword.");
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  };

  const downloadAndUse = async (item: StockItem) => {
    const key = `${item.provider}:${item.id}`;
    setDownloadId(key);
    setSearchError(null);
    try {
      await onDownload(item); // parent saves to library + selects it
      setTab("library");
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloadId(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* source tabs */}
      <div role="tablist" aria-label="Background source" className="flex h-9 items-stretch rounded-sm border border-line bg-surface-2 p-0.5">
        {([
          ["library", "Local"],
          ["upload", "Upload"],
          ["online", "Online"],
        ] as [LibraryTab, string][]).map(([id, label]) => (
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

      {tab === "library" ? (
        <div className="flex flex-col gap-2">
          <span className="text-[12px] font-medium text-ink-2 tracking-wide">Background</span>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Background">
            {[...builtin, ...uploaded].map((b) => {
              const active = b.id === settings.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onChange({ id: b.id })}
                  className={`group relative overflow-hidden rounded-sm border text-start transition-colors ${
                    active ? "border-gold" : "border-line hover:border-line-strong"
                  }`}
                >
                  {b.thumb ? (
                    <img src={b.thumb} alt="" className="aspect-[9/16] w-full object-cover" />
                  ) : (
                    <div className="flex aspect-[9/16] w-full items-center justify-center bg-surface-2 text-[10px] text-ink-3">
                      {b.kind}
                    </div>
                  )}
                  <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1.5 pb-1 pt-3 text-[10.5px] font-medium text-ink">
                    {b.name}
                  </span>
                </button>
              );
            })}
          </div>
          {selected?.uploaded ? (
            <p className="text-[11px] text-ink-3">
              Uploaded background{selected.duration ? ` · ${selected.duration}s source` : ""}
              {selected.kind === "video" ? " · loops automatically if shorter than the recitation" : ""}
            </p>
          ) : null}
          {selected && !selected.uploaded && selected.id.startsWith("stock-") ? (
            <p className="text-[11px] text-ink-3">
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
          >
            <svg width="20" height="20" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 11V3m0 0L5 6m3-3 3 3M3 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[12px] font-medium">{uploading ? "Uploading…" : "Choose file"}</span>
            <span className="text-[10.5px]">MP4 · WebM · JPG · PNG · up to 200 MB</span>
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
            <p className="text-[11.5px] text-danger" role="alert">{uploadError}</p>
          ) : null}
        </div>
      ) : null}

      {tab === "online" ? (
        <div className="flex flex-col gap-3">
          <p className="text-[11.5px] leading-relaxed text-ink-3">
            Search free stock media (Pexels &amp; Pixabay official APIs). Download &amp; Use saves it
            to your local library permanently.
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
              className="h-9 min-w-0 flex-1 rounded-sm border border-line bg-surface-2 px-3 text-[13px] text-ink outline-none placeholder:text-ink-3/60 focus:border-gold/60"
            />
            <button
              type="submit"
              disabled={searching || !query.trim()}
              className="h-9 shrink-0 rounded-sm bg-gold px-3.5 text-[12.5px] font-semibold text-gold-ink transition-colors hover:bg-gold-strong disabled:opacity-40"
            >
              {searching ? "…" : "Search"}
            </button>
          </form>
          <div className="flex flex-wrap items-center gap-2">
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
          <div className="flex flex-wrap gap-1.5" aria-label="Quick searches">
            {QUICK_QUERIES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => {
                  setQuery(q);
                  runSearch(q);
                }}
                className="rounded-xs border border-line bg-surface-2 px-2 py-0.5 text-[11px] text-ink-2 transition-colors hover:border-gold/60 hover:text-ink"
              >
                {q}
              </button>
            ))}
          </div>
          {searchError ? (
            <p className="text-[11.5px] text-danger" role="alert">{searchError}</p>
          ) : null}
          {results.length ? (
            <ul className="grid grid-cols-2 gap-2" aria-label="Search results">
              {results.map((item) => {
                const key = `${item.provider}:${item.id}`;
                const busy = downloadId === key;
                return (
                  <li key={key} className="overflow-hidden rounded-sm border border-line bg-surface-2">
                    {item.thumb ? (
                      <img src={item.thumb} alt="" loading="lazy" className="aspect-[9/16] w-full object-cover" />
                    ) : (
                      <div className="flex aspect-[9/16] w-full items-center justify-center text-[10px] text-ink-3">
                        {item.kind}
                      </div>
                    )}
                    <div className="flex flex-col gap-1 px-2 py-1.5">
                      <span className="truncate text-[10.5px] text-ink-3">
                        {item.provider} · {item.width}×{item.height}
                        {item.author ? ` · ${item.author}` : ""}
                      </span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => downloadAndUse(item)}
                        className="rounded-xs bg-gold/90 px-2 py-1 text-[11.5px] font-semibold text-gold-ink transition-colors hover:bg-gold disabled:opacity-50"
                      >
                        {busy ? "Downloading…" : "Download & Use"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-4 rounded-md border border-line bg-surface px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-ink-3">Adjustments</span>
          <button
            type="button"
            onClick={() =>
              onChange({ ...DEFAULTS })
            }
            className="text-[11px] text-ink-3 underline-offset-2 hover:text-gold hover:underline"
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
