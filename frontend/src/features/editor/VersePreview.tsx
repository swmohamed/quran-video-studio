import type {
  Ayah,
  BackgroundEntry,
  BackgroundSettings,
  SurahMeta,
  TextSettings,
} from "../../types";

/**
 * HTML replica of the server-side render composition, designed in the same
 * 1080x1920 coordinate space and scaled down visually. Font metric ratios
 * below are measured from the actual TTF files (freetype ascent/descent) so
 * browser line boxes match the HarfBuzz renderer.
 */
const FONT_METRICS: Record<string, number> = {
  amiri: 1.77,
  notonaskh: 1.71,
  notosansarabic: 2.12,
  inter: 1.22,
};

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

function toArabicIndic(n: number): string {
  return String(n).replace(/[0-9]/g, (d) => ARABIC_INDIC_DIGITS[Number(d)]);
}

/** Quranic verse-end marker: thin ornamental rosette (double ring + 8
 *  radiating petals), ayah number centered inside in the same ink color.
 *  Mirrors draw_ayah_marker() in the backend (same proportions) so preview
 *  matches the exported MP4 exactly. */
function AyahMarker({ n, fontStack, color }: { n: number; fontStack: string; color: string }) {
  const digits = String(n).length;
  const numSize = digits === 1 ? "0.44em" : digits === 2 ? "0.4em" : "0.33em";
  return (
    <span className="qvs-ayah-marker" style={{ color }} aria-hidden="true">
      <svg viewBox="0 0 100 100" focusable="false">
        <circle cx="50" cy="50" r="31" fill="none" stroke="currentColor" strokeWidth="4.5" />
        <circle cx="50" cy="50" r="26" fill="none" stroke="currentColor" strokeWidth="2.7" />
        {Array.from({ length: 8 }, (_, k) => {
          const a = (k * Math.PI) / 4;
          return (
            <circle
              key={k}
              cx={50 + Math.cos(a) * 37}
              cy={50 + Math.sin(a) * 37}
              r="5.5"
              fill="currentColor"
            />
          );
        })}
      </svg>
      <span className="qvs-marker-num" dir="rtl" style={{ fontFamily: fontStack, fontSize: numSize }}>
        {toArabicIndic(n)}
      </span>
    </span>
  );
}

export function VersePreview({
  surahMeta,
  ayah,
  translationText,
  text,
  bgEntry,
  bgSettings,
  width = 1080,
  height = 1920,
}: {
  surahMeta: SurahMeta | undefined;
  ayah: Ayah | undefined;
  translationText: string | null;
  text: TextSettings;
  bgEntry: BackgroundEntry | undefined;
  bgSettings: BackgroundSettings;
  width?: number;
  height?: number;
}) {
  const card = text.card;
  const ar = text.arabic;
  const tr = text.translation;

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

  // card width mirrors the renderer: % of canvas width, capped on landscape
  const cardW = Math.min(
    Math.round((width * card.widthPct) / 100),
    width > height ? Math.round(height * 1.15) : width,
  );
  const headerTop = Math.max(24, Math.round(height * ((text.header.topPct ?? 10) / 100)));

  return (
    <div className="relative overflow-hidden bg-canvas" style={{ width, height }} aria-hidden="true">
      {bgEntry ? (
        bgEntry.kind === "video" ? (
          <video
            key={bgEntry.id}
            src={bgEntry.url}
            autoPlay
            loop
            muted
            playsInline
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter, objectPosition: `center ${objectPositionY}` }}
          />
        ) : (
          <img
            key={bgEntry.id}
            src={bgEntry.url}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter, objectPosition: `center ${objectPositionY}` }}
          />
        )
      ) : null}

      <div className="absolute inset-0" style={{ background: `rgba(0,0,0,${bgSettings.darkOverlay / 100})` }} />

      {text.header.show ? (
        <div
          className="absolute inset-x-0 flex flex-col items-center"
          style={{ top: headerTop, gap: 18 }}
        >
          {text.header.showArabic && surahMeta ? (
            <div
              lang="ar"
              dir="rtl"
              style={{
                fontFamily: "var(--font-amiri)",
                fontWeight: 700,
                fontSize: 64,
                lineHeight: 1.77,
                color: "#e8d9b0",
              }}
            >
              {surahMeta.arabicName}
            </div>
          ) : null}
          {text.header.showEnglish ? (
            <div
              style={{
                fontFamily: "var(--font-ui)",
                fontSize: 30,
                lineHeight: 1.22,
                letterSpacing: "0.08em",
                color: "#b9b2a2",
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
          borderRadius: card.radius ? card.radius : undefined,
          border:
            card.visible && card.borderWidth
              ? `${card.borderWidth}px solid ${card.borderColor}`
              : undefined,
          padding: card.visible ? card.padding : 12,
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
                fontSize: ar.size,
                lineHeight: ar.lineHeight * (FONT_METRICS[ar.font] ?? 1.7),
                color: ar.color,
                textAlign: "center",
                paddingInline: 4,
              }}
            >
              {text.showAyahNumber && ayah.arabic.trim().includes(" ") ? (
                <>
                  {ayah.arabic.slice(0, ayah.arabic.trimEnd().lastIndexOf(" ") + 1)}
                  <span className="qvs-last-word">
                    {ayah.arabic.trimEnd().slice(ayah.arabic.trimEnd().lastIndexOf(" ") + 1)}
                    <AyahMarker
                      n={ayah.ayah}
                      fontStack={ARABIC_STACKS[ar.font] ?? "var(--font-amiri)"}
                      color={ar.color}
                    />
                  </span>
                </>
              ) : (
                <>
                  {ayah.arabic}
                  {text.showAyahNumber ? (
                    <AyahMarker
                      n={ayah.ayah}
                      fontStack={ARABIC_STACKS[ar.font] ?? "var(--font-amiri)"}
                      color={ar.color}
                    />
                  ) : null}
                </>
              )}
            </div>
            {translationText ? (
              <div
                dir="ltr"
                style={{
                  fontFamily: LATIN_STACKS[tr.font] ?? "var(--font-amiri)",
                  fontSize: tr.size,
                  lineHeight: tr.lineHeight * (FONT_METRICS[tr.font] ?? 1.4),
                  color: tr.color,
                  textAlign: "center",
                  marginTop: 52,
                  paddingInline: 4,
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

function hexAlpha(hex: string, opacityPct: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacityPct / 100})`;
}
