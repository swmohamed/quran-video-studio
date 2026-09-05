import type {
  Ayah,
  BackgroundEntry,
  BackgroundSettings,
  SurahMeta,
  TextSettings,
} from "../../types";
import { compositionScale } from "../../lib/formats";
import {
  clampTrim,
  ensureClips,
  layersAtTime,
  mapAudioToSequence,
  sequenceDuration,
  sourceDuration,
} from "../../lib/bgTimeline";
import { ensureQpcFont, isQpcReady, qpcFamily } from "../../lib/qpcFonts";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * HTML replica of the server-side render composition. Authored in 1080×1920
 * design units; `compositionScale(width, height)` applies the same uniform
 * scale the FFmpeg renderer uses. The stage may CSS-scale this whole tree
 * down to fit the UI — that does not change final MP4 glyph resolution.
 */
const ARABIC_STACKS: Record<string, string> = {
  amiri: "var(--font-amiri)",
  notonaskh: "var(--font-naskh)",
  notosansarabic: "var(--font-naskh-sans)",
};

const LATIN_STACKS: Record<string, string> = {
  amiri: "var(--font-amiri)",
  inter: "var(--font-ui)",
};

const ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";
const HEADER_EN_RATIO = 30 / 64;

function toArabicIndic(n: number): string {
  return String(n).replace(/[0-9]/g, (d) => ARABIC_INDIC_DIGITS[Number(d)]);
}

/** Quran.com QCF v2 ayah-end glyph (p{page}-v2 + code_v2 `end` word).
 *  Falls back to Noto U+06DD until that page font is ready. */
function AyahMarker({
  n,
  color,
  marker,
}: {
  n: number;
  color: string;
  marker?: Ayah["qpcMarker"];
}) {
  const page = marker?.page;
  const [ready, setReady] = useState(() => (page ? isQpcReady(page) : false));
  useEffect(() => {
    if (!page) {
      setReady(false);
      return;
    }
    if (isQpcReady(page)) {
      setReady(true);
      return;
    }
    let live = true;
    ensureQpcFont(page).then((ok) => {
      if (live) setReady(ok);
    });
    return () => {
      live = false;
    };
  }, [page, marker?.char]);

  if (marker && ready) {
    return (
      <span
        className="qvs-ayah-marker qvs-ayah-marker-qpc"
        dir="rtl"
        lang="ar"
        style={{ color, fontFamily: qpcFamily(marker.page) }}
        aria-hidden="true"
      >
        {marker.char}
      </span>
    );
  }
  return (
    <span className="qvs-ayah-marker" dir="rtl" lang="ar" style={{ color }} aria-hidden="true">
      {"\u06DD"}
      {toArabicIndic(n)}
    </span>
  );
}

export function VersePreview({
  surahMeta,
  ayah,
  translationText,
  text,
  bgEntry,
  backgrounds = [],
  bgSettings,
  width = 1080,
  height = 1920,
  playhead = 0,
  audioDuration = 0,
  playing = false,
}: {
  surahMeta: SurahMeta | undefined;
  ayah: Ayah | undefined;
  translationText: string | null;
  text: TextSettings;
  bgEntry: BackgroundEntry | undefined;
  backgrounds?: BackgroundEntry[];
  bgSettings: BackgroundSettings;
  width?: number;
  height?: number;
  playhead?: number;
  audioDuration?: number;
  playing?: boolean;
}) {
  const card = text.card;
  const ar = text.arabic;
  const tr = text.translation;
  const scale = compositionScale(width, height);
  const headerSize = (text.header.size ?? 64) * scale;
  const headerEnSize = Math.max(14 * scale, headerSize * HEADER_EN_RATIO);
  const headerGap = (text.header.gap ?? 18) * scale;
  const headerLh = text.header.lineHeight ?? 1.2;
  const arSize = ar.size * scale;
  const trSize = tr.size * scale;

  const filter = [
    `brightness(${bgSettings.brightness / 100})`,
    `contrast(${bgSettings.contrast / 100})`,
    `saturate(${bgSettings.saturation / 100})`,
    bgSettings.blur > 0 ? `blur(${bgSettings.blur}px)` : "",
  ]
    .filter(Boolean)
    .join(" ");

  const objectPositionY =
    bgSettings.position === "top" ? "0%" : bgSettings.position === "bottom" ? "100%" : "50%";

  const byId = useMemo(() => new Map(backgrounds.map((b) => [b.id, b])), [backgrounds]);
  const clips = ensureClips(bgSettings, backgrounds);
  const xfReq = bgSettings.transitionDuration ?? 0.5;
  const seqDur = sequenceDuration(clips, byId, bgSettings.crossfade, xfReq);
  const seqT = mapAudioToSequence(playhead, seqDur, audioDuration || seqDur);
  const layers = layersAtTime(seqT, clips, byId, bgSettings.crossfade, xfReq);
  const primary = layers[0];
  const shownLayers = [...layers];
  if (bgSettings.crossfade && primary && primary.index + 1 < clips.length) {
    const nextI = primary.index + 1;
    if (!shownLayers.some((l) => l.index === nextI)) {
      const nextClip = clips[nextI];
      const nextEntry = byId.get(nextClip.sourceId);
      const nextTrim = clampTrim(nextClip.trimStart, nextClip.trimEnd, sourceDuration(nextEntry));
      shownLayers.unshift({ index: nextI, sourceTime: nextTrim.trimStart, opacity: 0 });
    }
  }
  // card width mirrors the renderer: % of canvas width, capped on landscape
  const cardW = Math.min(
    Math.round((width * card.widthPct) / 100),
    width > height ? Math.round(height * 1.15) : width,
  );
  const headerTop = Math.max(24, Math.round(height * ((text.header.topPct ?? 7) / 100)));
  const pad = (card.visible ? card.padding : 12) * scale;
  const radius = card.radius * scale;
  const borderW = card.borderWidth * scale;

  return (
    <div className="relative overflow-hidden bg-canvas" style={{ width, height }} aria-hidden="true">
      {shownLayers.map((layer) => {
        const clip = clips[layer.index];
        const entry = (clip && byId.get(clip.sourceId)) || bgEntry;
        if (!entry) return null;
        const trim = clip
          ? clampTrim(clip.trimStart, clip.trimEnd, sourceDuration(entry))
          : { trimStart: 0, trimEnd: sourceDuration(entry) };
        return (
          <div
            key={`${clip?.id ?? entry.id}-${layer.index}`}
            className="absolute inset-0"
            style={{ opacity: layer.opacity }}
          >
            {entry.kind === "video" ? (
              <TimelineVideo
                entry={entry}
                sourceTime={layer.sourceTime}
                trimStart={trim.trimStart}
                trimEnd={trim.trimEnd}
                playing={playing && layer.opacity > 0}
                loopSection={clips.length <= 1}
                filter={filter}
                objectPositionY={objectPositionY}
              />
            ) : (
              <img
                src={entry.url}
                alt=""
                className="absolute inset-0 h-full w-full object-cover"
                style={{ filter, objectPosition: `center ${objectPositionY}` }}
              />
            )}
          </div>
        );
      })}

      <div className="absolute inset-0" style={{ background: `rgba(0,0,0,${bgSettings.darkOverlay / 100})` }} />

      {text.header.show ? (
        <div
          className="absolute inset-x-0 flex flex-col items-center"
          style={{ top: headerTop, gap: headerGap }}
        >
          {text.header.showArabic && surahMeta ? (
            <div
              lang="ar"
              dir="rtl"
              style={{
                fontFamily: "var(--font-amiri)",
                fontWeight: 700,
                fontSize: headerSize,
                lineHeight: headerLh,
                color: text.header.color ?? "#f5f1e8",
              }}
            >
              {surahMeta.arabicName}
            </div>
          ) : null}
          {text.header.showEnglish ? (
            <div
              style={{
                fontFamily: "var(--font-ui)",
                fontSize: headerEnSize,
                lineHeight: headerLh,
                letterSpacing: "0.08em",
                color: text.header.color ?? "#f5f1e8",
                fontWeight: 500,
              }}
            >
              {surahMeta?.englishName.toUpperCase()}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* verse card — persistent shell; ONLY the text content swaps */}
      <div
        className="absolute left-1/2 flex flex-col items-center justify-center"
        style={{
          width: cardW,
          top: `${card.positionPct}%`,
          transform: "translate(-50%, -50%)",
          background: card.visible ? hexAlpha(card.color, card.opacity) : "transparent",
          borderRadius: card.radius ? radius : undefined,
          border:
            card.visible && card.borderWidth
              ? `${borderW}px solid ${card.borderColor}`
              : undefined,
          padding: card.visible ? pad : 12 * scale,
        }}
      >
        {ayah ? (
          <div
            key={`${ayah.surah}:${ayah.ayah}`}
            className="qvs-text-fade flex flex-col items-center"
          >
            <div
              lang="ar"
              dir="rtl"
              style={{
                fontFamily: ARABIC_STACKS[ar.font] ?? "var(--font-amiri)",
                fontSize: arSize,
                lineHeight: ar.lineHeight,
                color: ar.color,
                textAlign: "center",
                paddingInline: 4,
                position: "relative",
                left: ((ar.offsetX ?? 0) / 100) * width,
                top: ((ar.offsetY ?? 0) / 100) * height,
                ...(text.outline ? { textShadow: "0 1px 2px rgba(8,7,6,0.88)" } : {}),
              }}
            >
              {text.showAyahNumber && ayah.arabic.trim().includes(" ") ? (
                <>
                  {ayah.arabic.slice(0, ayah.arabic.trimEnd().lastIndexOf(" ") + 1)}
                  <span className="qvs-last-word">
                    {ayah.arabic.trimEnd().slice(ayah.arabic.trimEnd().lastIndexOf(" ") + 1)}
                    <AyahMarker n={ayah.ayah} color={ar.color} marker={ayah.qpcMarker} />
                  </span>
                </>
              ) : (
                <>
                  {ayah.arabic}
                  {text.showAyahNumber ? (
                    <AyahMarker n={ayah.ayah} color={ar.color} marker={ayah.qpcMarker} />
                  ) : null}
                </>
              )}
            </div>
            {translationText ? (
              <div
                dir="ltr"
                style={{
                  fontFamily: LATIN_STACKS[tr.font] ?? "var(--font-amiri)",
                  fontSize: trSize,
                  lineHeight: tr.lineHeight,
                  color: tr.color,
                  textAlign: "center",
                  marginTop: 32 * scale,
                  paddingInline: 4,
                  position: "relative",
                  left: ((tr.offsetX ?? 0) / 100) * width,
                  top: ((tr.offsetY ?? 0) / 100) * height,
                }}
              >
                {translationText}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TimelineVideo({
  entry,
  sourceTime,
  trimStart,
  trimEnd,
  playing,
  loopSection,
  filter,
  objectPositionY,
}: {
  entry: BackgroundEntry;
  sourceTime: number;
  trimStart: number;
  trimEnd: number;
  playing: boolean;
  loopSection: boolean;
  filter: string;
  objectPositionY: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const apply = () => {
      const slop = playing ? 0.22 : 0.04;
      if (Math.abs(v.currentTime - sourceTime) > slop) {
        try {
          v.currentTime = sourceTime;
        } catch {
          /* seeking not ready */
        }
      }
    };
    if (v.readyState >= 1) apply();
    else v.addEventListener("loadedmetadata", apply, { once: true });
    if (playing || loopSection) {
      void v.play().catch(() => undefined);
    } else {
      v.pause();
    }
  }, [sourceTime, playing, loopSection, entry.id]);

  return (
    <video
      ref={ref}
      src={entry.url}
      muted
      playsInline
      className="absolute inset-0 h-full w-full object-cover"
      style={{ filter, objectPosition: `center ${objectPositionY}` }}
      onTimeUpdate={(e) => {
        if (!loopSection) return;
        const v = e.currentTarget;
        if (v.currentTime >= trimEnd - 0.05) v.currentTime = trimStart;
      }}
    />
  );
}

function hexAlpha(hex: string, opacityPct: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacityPct / 100})`;
}
