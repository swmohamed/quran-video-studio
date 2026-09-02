/**
 * Platform / video-format presets — mirrors backend config.PLATFORM_PRESETS.
 * TikTok, Shorts and Reels share output dimensions but stay separate presets
 * so safe zones can be defined (and updated) per platform.
 */
export type PlatformId = "tiktok" | "shorts" | "reels" | "youtube" | "portrait" | "square";

export interface PlatformPreset {
  label: string;
  width: number;
  height: number;
  orientation: "portrait" | "landscape" | "square";
  aspect: string;
}

export const PLATFORM_PRESETS: Record<PlatformId, PlatformPreset> = {
  tiktok: { label: "TikTok", width: 1080, height: 1920, orientation: "portrait", aspect: "9:16" },
  shorts: { label: "YouTube Shorts", width: 1080, height: 1920, orientation: "portrait", aspect: "9:16" },
  reels: { label: "Instagram Reels", width: 1080, height: 1920, orientation: "portrait", aspect: "9:16" },
  youtube: { label: "YouTube", width: 1920, height: 1080, orientation: "landscape", aspect: "16:9" },
  portrait: { label: "Portrait", width: 1080, height: 1350, orientation: "portrait", aspect: "4:5" },
  square: { label: "Square", width: 1080, height: 1080, orientation: "square", aspect: "1:1" },
};

export const PLATFORM_ORDER: PlatformId[] = ["tiktok", "shorts", "reels", "youtube", "portrait", "square"];

export const DEFAULT_PLATFORM: PlatformId = "tiktok";

export function platformPreset(id: string | undefined | null): PlatformPreset {
  return PLATFORM_PRESETS[(id as PlatformId) ?? ""] ?? PLATFORM_PRESETS[DEFAULT_PLATFORM];
}

/** Online background search orientation hint for a platform. */
export function searchOrientation(id: string | undefined | null): "portrait" | "landscape" | "square" {
  const p = platformPreset(id);
  if (p.orientation === "landscape") return "landscape";
  if (p.orientation === "square") return "square";
  return "portrait";
}

/* ------------------------------------------------------------------ */
/* Preview-only safe zones (NEVER rendered into the MP4).              */
/* Values are percent of canvas from each edge. Updated per platform.  */
/* ------------------------------------------------------------------ */

export interface SafeZoneBox {
  top?: number;
  bottom?: number;
  start?: number;
  end?: number;
  note?: string;
}

export const SAFE_ZONES: Record<string, { label: string; boxes: SafeZoneBox[] }> = {
  tiktok: {
    label: "TikTok",
    boxes: [
      { top: 8, note: "top bar" },
      { bottom: 18, note: "caption + sound" },
      { end: 13, note: "action rail" },
    ],
  },
  shorts: {
    label: "YouTube Shorts",
    boxes: [
      { top: 10, note: "title" },
      { bottom: 16, note: "engagement" },
    ],
  },
  reels: {
    label: "Instagram Reels",
    boxes: [
      { top: 10, note: "header" },
      { bottom: 24, note: "caption + CTA" },
      { end: 12, note: "actions" },
    ],
  },
};
