import type { Reciter, SurahMeta, TranslationMeta } from "../../../types";

export function ContentPanel({
  surahs,
  surah,
  onSurah,
  fromAyah,
  toAyah,
  onFrom,
  onTo,
  ayahCount,
  reciters,
  reciter,
  onReciter,
  translations,
  translation,
  onTranslation,
}: {
  surahs: SurahMeta[];
  surah: number;
  onSurah: (n: number) => void;
  fromAyah: number;
  toAyah: number;
  onFrom: (n: number) => void;
  onTo: (n: number) => void;
  ayahCount: number;
  reciters: Reciter[];
  reciter: string;
  onReciter: (id: string) => void;
  translations: TranslationMeta[];
  translation: string;
  onTranslation: (id: string) => void;
}) {
  const selectedCount = toAyah - fromAyah + 1;
  const tooMany = selectedCount > 30;
  const activeTranslation = translations.find((t) => t.id === translation);

  const ayahOptions = Array.from({ length: ayahCount }, (_, i) => i + 1);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="surah-select" className="text-[12px] font-medium text-ink-2 tracking-wide">
          Surah
        </label>
        <select
          id="surah-select"
          value={surah}
          onChange={(e) => onSurah(Number(e.target.value))}
          className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink hover:border-line-strong"
        >
          {surahs.map((s) => (
            <option key={s.number} value={s.number}>
              {s.number}. {s.englishName} — {s.englishNameTranslation}
            </option>
          ))}
        </select>
        {(() => {
          const meta = surahs.find((s) => s.number === surah);
          return meta ? (
            <p lang="ar" dir="rtl" className="text-right text-[15px] text-ink-2" style={{ fontFamily: "var(--font-amiri)" }}>
              {meta.arabicName} · {meta.revelationType} · {meta.ayahCount} ayahs
            </p>
          ) : null;
        })()}
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-[12px] font-medium text-ink-2 tracking-wide">Ayah range</legend>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="from-ayah">From ayah</label>
          <select
            id="from-ayah"
            value={fromAyah}
            onChange={(e) => onFrom(Number(e.target.value))}
            className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2 text-[13px] tabular-nums"
          >
            {ayahOptions.map((n) => (
              <option key={n} value={n}>From {n}</option>
            ))}
          </select>
          <span aria-hidden="true" className="text-ink-3">→</span>
          <label className="sr-only" htmlFor="to-ayah">To ayah</label>
          <select
            id="to-ayah"
            value={toAyah}
            onChange={(e) => onTo(Number(e.target.value))}
            className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2 text-[13px] tabular-nums"
          >
            {ayahOptions.map((n) => (
              <option key={n} value={n}>To {n}</option>
            ))}
          </select>
        </div>
        <p className={`text-[11.5px] ${tooMany ? "text-danger" : "text-ink-3"}`} role={tooMany ? "alert" : undefined}>
          {selectedCount} {selectedCount === 1 ? "ayah" : "ayahs"} selected
          {tooMany ? " — maximum is 30 per video" : ""}
        </p>
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="reciter-select" className="text-[12px] font-medium text-ink-2 tracking-wide">
          Reciter
        </label>
        <select
          id="reciter-select"
          value={reciter}
          onChange={(e) => onReciter(e.target.value)}
          className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink hover:border-line-strong"
        >
          {reciters.map((r) => (
            <option key={r.id} value={r.id}>
              {r.arabicName ? `${r.name} · ${r.arabicName}` : r.name}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-ink-3">Continuous full-surah audio with official verse timestamps; verse-by-verse fallback otherwise.</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="translation-select" className="text-[12px] font-medium text-ink-2 tracking-wide">
          Translation
        </label>
        <select
          id="translation-select"
          value={translation}
          onChange={(e) => onTranslation(e.target.value)}
          className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink hover:border-line-strong"
        >
          {translations.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        {activeTranslation?.attribution ? (
          <p className="text-[11px] leading-snug text-ink-3">{activeTranslation.attribution}</p>
        ) : null}
      </div>
    </div>
  );
}
