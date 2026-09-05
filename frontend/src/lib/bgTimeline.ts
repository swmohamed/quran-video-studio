import type { BackgroundClip, BackgroundEntry, BackgroundSettings, PreviewTimeline } from "../types";

export const IMAGE_DEFAULT_S = 8;
export const DEFAULT_XFADE_S = 0.5;
export const XFADE_MIN_S = 0.2;
export const XFADE_MAX_S = 1.0;
/** @deprecated use DEFAULT_XFADE_S */
export const XFADE_S = DEFAULT_XFADE_S;
export const MIN_CLIP_S = 0.05;

export type BgLayer = {
  index: number;
  sourceTime: number;
  opacity: number;
};

export function clampXfadeRequested(requested?: number): number {
  const n = Number(requested);
  if (!Number.isFinite(n)) return DEFAULT_XFADE_S;
  return Math.min(XFADE_MAX_S, Math.max(XFADE_MIN_S, n));
}

export function newClipId(): string {
  return crypto.randomUUID?.() ?? `clip-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function sourceDuration(entry: BackgroundEntry | undefined): number {
  if (!entry) return IMAGE_DEFAULT_S;
  if (entry.kind === "image") return IMAGE_DEFAULT_S;
  return Math.max(MIN_CLIP_S, entry.duration ?? IMAGE_DEFAULT_S);
}

export function clampTrim(start: number, end: number, srcDur: number): { trimStart: number; trimEnd: number } {
  const src = Math.max(MIN_CLIP_S, srcDur);
  const trimStart = Math.max(0, Math.min(start, src - MIN_CLIP_S));
  const rawEnd = end > 0 ? end : src;
  const trimEnd = Math.min(src, Math.max(trimStart + MIN_CLIP_S, rawEnd));
  return { trimStart, trimEnd };
}

export function makeClip(entry: BackgroundEntry): BackgroundClip {
  const src = sourceDuration(entry);
  return { id: newClipId(), sourceId: entry.id, trimStart: 0, trimEnd: src };
}

export function clipUsedDuration(clip: BackgroundClip, entry: BackgroundEntry | undefined): number {
  const src = sourceDuration(entry);
  const { trimStart, trimEnd } = clampTrim(clip.trimStart, clip.trimEnd, src);
  return Math.max(MIN_CLIP_S, trimEnd - trimStart);
}

export function xfadeDuration(
  clips: BackgroundClip[],
  entries: Map<string, BackgroundEntry>,
  enabled: boolean,
  requested?: number,
): number {
  if (!enabled || clips.length < 2) return 0;
  const want = clampXfadeRequested(requested);
  const shortest = Math.min(...clips.map((c) => clipUsedDuration(c, entries.get(c.sourceId))));
  const cap = Math.max(0, shortest - MIN_CLIP_S);
  if (cap < 0.05) return 0;
  return Math.min(want, cap);
}

export function sequenceDuration(
  clips: BackgroundClip[],
  entries: Map<string, BackgroundEntry>,
  crossfade: boolean,
  requested?: number,
): number {
  if (!clips.length) return 0;
  const total = clips.reduce((s, c) => s + clipUsedDuration(c, entries.get(c.sourceId)), 0);
  const xf = xfadeDuration(clips, entries, crossfade, requested);
  return Math.max(MIN_CLIP_S, total - xf * Math.max(0, clips.length - 1));
}

export function mapAudioToSequence(t: number, seqDur: number, audioDur: number): number {
  if (seqDur <= 0) return 0;
  const clamped = audioDur > 0 ? Math.min(Math.max(0, t), audioDur) : Math.max(0, t);
  if (seqDur + 0.0001 >= audioDur) return Math.min(clamped, seqDur);
  return clamped % seqDur;
}

/** Sequence-time start of clip `index` (same span math as clipAtTime). */
export function clipSequenceOffset(
  clips: BackgroundClip[],
  index: number,
  entries: Map<string, BackgroundEntry>,
  crossfade: boolean,
  requested?: number,
): number {
  if (index <= 0) return 0;
  const xf = xfadeDuration(clips, entries, crossfade, requested);
  let acc = 0;
  const until = Math.min(index, clips.length);
  for (let i = 0; i < until; i++) {
    const used = clipUsedDuration(clips[i], entries.get(clips[i].sourceId));
    const span = i < clips.length - 1 ? Math.max(MIN_CLIP_S, used - xf) : used;
    acc += span;
  }
  return acc;
}

/** Map a sequence time onto the audio/master playhead, staying in the current loop. */
export function sequenceToAudioTime(
  seqT: number,
  seqDur: number,
  audioDur: number,
  currentAudioT: number,
): number {
  if (seqDur <= 0) return 0;
  const t = Math.max(0, seqT);
  if (!(audioDur > 0) || seqDur + 0.0001 >= audioDur) {
    return audioDur > 0 ? Math.min(t, audioDur) : t;
  }
  const loop = Math.floor(Math.max(0, currentAudioT) / seqDur);
  const mapped = loop * seqDur + t;
  return Math.min(audioDur, mapped > audioDur + 0.0001 ? t : mapped);
}

export function clipAtTime(
  seqT: number,
  clips: BackgroundClip[],
  entries: Map<string, BackgroundEntry>,
  crossfade: boolean,
  requested?: number,
): { index: number; sourceTime: number } {
  const layers = layersAtTime(seqT, clips, entries, crossfade, requested);
  const primary = layers[0] ?? { index: 0, sourceTime: 0 };
  return { index: primary.index, sourceTime: primary.sourceTime };
}

/** Layers at sequence time. Incoming sits under outgoing so CSS opacity
 *  matches FFmpeg xfade: A*(1-p)+B*p with no black showing through. */
export function layersAtTime(
  seqT: number,
  clips: BackgroundClip[],
  entries: Map<string, BackgroundEntry>,
  crossfade: boolean,
  requested?: number,
): BgLayer[] {
  if (!clips.length) return [{ index: 0, sourceTime: 0, opacity: 1 }];
  const xf = xfadeDuration(clips, entries, crossfade, requested);
  const used = clips.map((c) => clipUsedDuration(c, entries.get(c.sourceId)));
  const starts: number[] = [0];
  for (let i = 0; i < clips.length - 1; i++) {
    starts.push(starts[i] + Math.max(MIN_CLIP_S, used[i] - xf));
  }
  const t = Math.max(0, seqT);

  const layerAt = (i: number): BgLayer => {
    const src = sourceDuration(entries.get(clips[i].sourceId));
    const { trimStart } = clampTrim(clips[i].trimStart, clips[i].trimEnd, src);
    const local = Math.min(used[i] - 0.001, Math.max(0, t - starts[i]));
    return { index: i, sourceTime: trimStart + local, opacity: 1 };
  };

  for (let i = 0; i < clips.length - 1; i++) {
    const fade0 = starts[i + 1];
    const fade1 = fade0 + xf;
    if (xf > 0 && t >= fade0 && t < fade1) {
      const p = Math.min(1, Math.max(0, (t - fade0) / xf));
      const incoming = layerAt(i + 1);
      const outgoing = layerAt(i);
      return [
        { ...incoming, opacity: 1 },
        { ...outgoing, opacity: 1 - p },
      ];
    }
  }

  for (let i = 0; i < clips.length; i++) {
    const end = i < clips.length - 1 ? starts[i + 1] : starts[i] + used[i];
    if (t < end || i === clips.length - 1) return [layerAt(i)];
  }
  return [layerAt(clips.length - 1)];
}

export function ensureClips(settings: BackgroundSettings, backgrounds: BackgroundEntry[]): BackgroundClip[] {
  if (settings.clips?.length) return settings.clips;
  const entry = backgrounds.find((b) => b.id === settings.id);
  if (!entry) return [];
  return [makeClip(entry)];
}

export function ayahIndexAtTime(tl: PreviewTimeline, t: number): number {
  if (!tl.segments.length) return 0;
  if (tl.mode === "surah") {
    let idx = 0;
    for (let i = 0; i < tl.segments.length; i++) {
      if ((tl.segments[i].at ?? 0) <= t) idx = i;
    }
    return idx;
  }
  let acc = 0;
  for (let i = 0; i < tl.segments.length; i++) {
    const d = tl.segments[i].duration ?? 0;
    if (t < acc + d) return i;
    acc += d;
  }
  return tl.segments.length - 1;
}

export function timeAtAyahIndex(tl: PreviewTimeline, index: number): number {
  if (!tl.segments.length) return 0;
  const i = Math.max(0, Math.min(index, tl.segments.length - 1));
  if (tl.mode === "surah") return tl.segments[i].at ?? 0;
  let acc = 0;
  for (let k = 0; k < i; k++) acc += tl.segments[k].duration ?? 0;
  return acc;
}

export function timelineFromDuration(d: {
  duration: number;
  estimated: boolean;
  source: string;
  segments?: { ayah: number; at?: number; duration?: number }[];
}): PreviewTimeline | null {
  if (!d.segments?.length) return null;
  const hasAt = d.segments.every((s) => s.at != null);
  return {
    mode: hasAt ? "surah" : "verses",
    surah: 0,
    reciter: "",
    segments: d.segments,
    total: d.duration,
    estimated: d.estimated,
  };
}
