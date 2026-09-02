import type {
  Ayah,
  BackgroundEntry,
  FontCatalog,
  HealthReport,
  JobSnapshot,
  Preset,
  PreviewTimeline,
  Reciter,
  StockItem,
  SurahMeta,
  TranslationMeta,
} from "../types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep default */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<HealthReport>(r)),
  surahs: () => fetch("/api/surahs").then((r) => json<{ surahs: SurahMeta[] }>(r)),
  surah: (n: number) =>
    fetch(`/api/surahs/${n}`).then((r) => json<{ surah: SurahMeta; ayahs: Ayah[] }>(r)),
  reciters: () => fetch("/api/reciters").then((r) => json<{ reciters: Reciter[] }>(r)),
  translations: () =>
    fetch("/api/translations").then((r) => json<{ translations: TranslationMeta[]; quranTextSource: string }>(r)),
  presets: () => fetch("/api/presets").then((r) => json<{ presets: Preset[] }>(r)),
  fonts: () => fetch("/api/fonts").then((r) => json<FontCatalog>(r)),
  backgrounds: () => fetch("/api/backgrounds").then((r) => json<{ backgrounds: BackgroundEntry[] }>(r)),
  uploadBackground: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/background/upload", { method: "POST", body: form }).then((r) =>
      json<BackgroundEntry>(r),
    );
  },
  stockStatus: () =>
    fetch("/api/stock/status").then((r) => json<{ providers: { pexels: boolean; pixabay: boolean } }>(r)),
  stockSearch: (q: string, provider: string, orientation: string, kind: "image" | "video") =>
    fetch(
      `/api/stock/search?q=${encodeURIComponent(q)}&provider=${provider}` +
        `&orientation=${orientation}&kind=${kind}`,
    ).then((r) => json<{ provider: string; kind: string; items: StockItem[] }>(r)),
  stockDownload: (item: StockItem) =>
    fetch("/api/stock/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: item.provider,
        id: item.id,
        url: item.url,
        kind: item.kind,
        name: item.name,
      }),
    }).then((r) => json<BackgroundEntry>(r)),
  render: (settings: unknown) =>
    fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).then((r) => json<{ jobId: string }>(r)),
  previewTimeline: (req: { surah: number; fromAyah: number; toAyah: number; reciter: string }) =>
    fetch("/api/preview/timeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }).then((r) => json<PreviewTimeline>(r)),
  job: (id: string) => fetch(`/api/render/${id}`).then((r) => json<JobSnapshot>(r)),
  cancelJob: (id: string) =>
    fetch(`/api/render/${id}/cancel`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r)),
  downloadUrl: (id: string) => `/api/render/${id}/download`,
};
