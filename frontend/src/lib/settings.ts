import type { EditorSettings, Preset } from "../types";
import { DEFAULT_PLATFORM } from "./formats";

export const DEFAULT_SETTINGS: EditorSettings = {
  surah: 89,
  fromAyah: 6,
  toAyah: 12,
  reciter: "alafasy",
  translation: "en-sahih",
  platform: DEFAULT_PLATFORM,
  resolution: "fhd",
  quality: "high",
  withLight: true,
  background: {
    id: "night-sky",
    brightness: 80,
    contrast: 100,
    saturation: 90,
    blur: 0,
    darkOverlay: 42,
    position: "center",
    clips: [],
    crossfade: true,
    transitionDuration: 0.5,
  },
  text: {
    card: {
      visible: true,
      color: "#0a0c12",
      opacity: 70,
      radius: 24,
      borderWidth: 0,
      borderColor: "#c9a45c",
      widthPct: 92,
      padding: 32,
      positionPct: 52,
    },
    arabic: { font: "amiri", size: 68, color: "#f5f1e8", lineHeight: 1.85, offsetX: 0, offsetY: 0 },
    translation: { font: "amiri", size: 40, color: "#d8d2c4", lineHeight: 1.5, offsetX: 0, offsetY: 0 },
    header: { show: true, showArabic: true, showEnglish: true, showNumber: true, topPct: 7, size: 64, gap: 18, color: "#f5f1e8", lineHeight: 1.2 },
    showAyahNumber: true,
    refColor: "#c9a45c",
    outline: false,
  },
  fadeMs: 280,
};

const STORAGE_KEY = "qvs.settings.v2";

export function loadSettings(): EditorSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(DEFAULT_SETTINGS);
    const saved = JSON.parse(raw) as Partial<EditorSettings>;
    const merged = deepMerge(structuredClone(DEFAULT_SETTINGS), saved);
    const bg = saved.background as { transitionDuration?: number } | undefined;
    if (bg && typeof bg.transitionDuration !== "number") {
      merged.background.crossfade = true;
      merged.background.transitionDuration = 0.5;
    }
    return merged;
  } catch {
    return structuredClone(DEFAULT_SETTINGS);
  }
}

export function saveSettings(s: EditorSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable — session-only */
  }
}

export function applyPreset(base: EditorSettings, preset: Preset): EditorSettings {
  const next = structuredClone(base);
  const merged = deepMerge(structuredClone(DEFAULT_SETTINGS), preset.settings as Partial<EditorSettings>);
  const clips = base.background.clips ?? [];
  next.background = {
    ...merged.background,
    clips,
    crossfade: base.background.crossfade,
    transitionDuration: base.background.transitionDuration,
    id: clips.length ? base.background.id : merged.background.id,
  };
  next.text = {
    ...merged.text,
    arabic: {
      ...merged.text.arabic,
      offsetX: base.text.arabic.offsetX ?? 0,
      offsetY: base.text.arabic.offsetY ?? 0,
    },
    translation: {
      ...merged.text.translation,
      offsetX: base.text.translation.offsetX ?? 0,
      offsetY: base.text.translation.offsetY ?? 0,
    },
  };
  next.fadeMs = merged.fadeMs;
  return next;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function deepMerge<T>(base: T, overlay: Partial<T> | undefined): T {
  if (!overlay) return base;
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(overlay as Record<string, unknown>)) {
    if (v === undefined) continue;
    const bv = out[k];
    out[k] = isPlainObject(v) && isPlainObject(bv) ? deepMerge(bv, v) : v;
  }
  return out as T;
}

export const UI_PREVIEW = {
  localStorageSafeZone: "qvs.preview.safeZone",
  localStoragePlatform: "qvs.preview.platform",
};
