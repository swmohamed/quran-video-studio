export interface SurahMeta {
  number: number;
  arabicName: string;
  englishName: string;
  englishNameTranslation: string;
  revelationType: string;
  ayahCount: number;
}

export interface Ayah {
  surah: number;
  ayah: number;
  arabic: string;
  translations: Record<string, string>;
}

export interface Reciter {
  id: string;
  name: string;
  arabicName?: string;
  cachedAudioCount: number;
}

export interface TranslationMeta {
  id: string;
  name: string;
  language: string;
  languageCode: string | null;
  direction: string;
  translator: string | null;
  attribution?: string;
}

export interface BackgroundEntry {
  id: string;
  file: string;
  kind: "video" | "image";
  uploaded: boolean;
  name: string;
  url: string;
  thumb?: string;
  duration?: number;
}

export interface StockItem {
  provider: "pexels" | "pixabay";
  id: string;
  kind: "image" | "video";
  thumb: string | null;
  preview: string | null;
  url: string;
  width: number | null;
  height: number | null;
  author: string;
  name: string;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  settings: {
    background?: Partial<BackgroundSettings>;
    text?: Partial<TextSettings>;
    fadeMs?: number;
  };
}

export interface BackgroundSettings {
  id: string;
  brightness: number;
  contrast: number;
  saturation: number;
  blur: number;
  darkOverlay: number;
  position: "top" | "center" | "bottom";
}

export interface CardSettings {
  visible: boolean;
  color: string;
  opacity: number;
  radius: number;
  borderWidth: number;
  borderColor: string;
  widthPct: number;
  padding: number;
  positionPct: number;
}

export interface ArabicTextSettings {
  font: string;
  size: number;
  color: string;
  lineHeight: number;
}

export interface TranslationTextSettings {
  font: string;
  size: number;
  color: string;
  lineHeight: number;
}

export interface HeaderSettings {
  show: boolean;
  showArabic: boolean;
  showEnglish: boolean;
  showNumber: boolean;
  topPct: number;
}

export interface TextSettings {
  card: CardSettings;
  arabic: ArabicTextSettings;
  translation: TranslationTextSettings;
  header: HeaderSettings;
  showAyahNumber: boolean;
  refColor: string;
}

export interface EditorSettings {
  surah: number;
  fromAyah: number;
  toAyah: number;
  reciter: string;
  translation: string;
  platform: string;
  resolution: "light" | "fhd" | "uhd";
  quality: "max" | "high" | "small";
  withLight: boolean;
  background: BackgroundSettings;
  text: TextSettings;
  fadeMs: number;
}

export type JobState = "queued" | "running" | "succeeded" | "failed" | "canceled";

export interface JobSnapshot {
  id: string;
  state: JobState;
  stage: string;
  progress: number;
  detail: string;
  error: string | null;
  result: RenderResult | null;
}

export interface RenderResult {
  filename: string;
  url: string;
  path: string;
  duration: number;
  expectedDuration: number;
  sizeBytes: number;
  resolution: string;
  videoCodec: string;
  audioCodec: string;
  surah: number;
  fromAyah: number;
  toAyah: number;
  reciter: string;
  translation: string;
  platform: string;
  resolutionTier: string;
  lightFilename?: string;
  lightUrl?: string;
  lightSizeBytes?: number;
  lightResolution?: string;
  dualFilename?: string;
  dualUrl?: string;
  dualSizeBytes?: number;
  ayahSegments: { ayah: number; start: number; end: number; duration: number }[];
}

export interface HealthReport {
  ffmpeg: { ok: boolean; version?: string; error?: string };
  dataOk: boolean;
  dataError: string | null;
  fonts: Record<string, boolean>;
}

export interface VersesSeg {
  ayah: number;
  offset: number;
  duration: number;
  audioUrl: string;
}

export interface SurahSeg {
  ayah: number;
  at: number;
}

export interface PreviewTimeline {
  mode: "verses" | "surah";
  surah: number;
  reciter: string;
  segments: { ayah: number; at?: number; offset?: number; duration?: number; audioUrl?: string }[];
  total: number;
  estimated: boolean;
  url?: string;
  offset?: number;
  duration?: number;
}

export interface FontCatalog {
  arabic: { id: string; name: string; file: string }[];
  latin: { id: string; name: string; file: string }[];
}
