import type { FontCatalog, TextSettings } from "../../../types";
import { ColorRow, Divider, Field, SliderRow, Toggle } from "../../../components/ui";

export function TextPanel({
  text,
  onChange,
  fonts,
}: {
  text: TextSettings;
  onChange: (patch: Partial<TextSettings>) => void;
  fonts: FontCatalog | undefined;
}) {
  const setCard = (p: Partial<TextSettings["card"]>) => onChange({ card: { ...text.card, ...p } });
  const setArabic = (p: Partial<TextSettings["arabic"]>) => onChange({ arabic: { ...text.arabic, ...p } });
  const setTr = (p: Partial<TextSettings["translation"]>) => onChange({ translation: { ...text.translation, ...p } });
  const setHeader = (p: Partial<TextSettings["header"]>) => onChange({ header: { ...text.header, ...p } });

  return (
    <div className="flex flex-col gap-5">
      <Divider label="Text card" />
      <Toggle label="Show card" checked={text.card.visible} onChange={(v) => setCard({ visible: v })}
        description="Translucent panel behind the verse" />
      {text.card.visible ? (
        <>
          <SliderRow label="Card opacity" unit="%" value={text.card.opacity} min={0} max={100}
            onChange={(v) => setCard({ opacity: v })} />
          <SliderRow label="Card width" unit="%" value={text.card.widthPct} min={50} max={96}
            onChange={(v) => setCard({ widthPct: v })} />
          <SliderRow label="Corner radius" unit="px" value={text.card.radius} min={0} max={64}
            onChange={(v) => setCard({ radius: v })} />
          <SliderRow label="Vertical position" unit="%" value={text.card.positionPct} min={20} max={80}
            onChange={(v) => setCard({ positionPct: v })} />
          <ColorRow label="Card color" value={text.card.color} onChange={(v) => setCard({ color: v })} />
          <SliderRow label="Border" unit="px" value={text.card.borderWidth} min={0} max={6}
            onChange={(v) => setCard({ borderWidth: v })} />
          {text.card.borderWidth > 0 ? (
            <ColorRow label="Border color" value={text.card.borderColor} onChange={(v) => setCard({ borderColor: v })} />
          ) : null}
        </>
      ) : null}

      <Divider label="Arabic verse" />
      {fonts ? (
        <Field label="Arabic font" htmlFor="arabic-font">
          <select
            id="arabic-font"
            value={text.arabic.font}
            onChange={(e) => setArabic({ font: e.target.value })}
            className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink"
          >
            {fonts.arabic.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </Field>
      ) : null}
      <SliderRow label="Arabic size" unit="px" value={text.arabic.size} min={36} max={110}
        onChange={(v) => setArabic({ size: v })}
        hint="Long verses auto-shrink to fit the card while staying readable." />
      <SliderRow label="Line height" value={text.arabic.lineHeight} min={1.4} max={2.4} step={0.05}
        onChange={(v) => setArabic({ lineHeight: v })} />
      <ColorRow label="Arabic color" value={text.arabic.color} onChange={(v) => setArabic({ color: v })} />

      <Divider label="Translation" />
      {fonts ? (
        <Field label="Translation font" htmlFor="tr-font">
          <select
            id="tr-font"
            value={text.translation.font}
            onChange={(e) => setTr({ font: e.target.value })}
            className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink"
          >
            {fonts.latin.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </Field>
      ) : null}
      <SliderRow label="Translation size" unit="px" value={text.translation.size} min={24} max={64}
        onChange={(v) => setTr({ size: v })} />
      <SliderRow label="Line height" value={text.translation.lineHeight} min={1.2} max={2} step={0.05}
        onChange={(v) => setTr({ lineHeight: v })} />
      <ColorRow label="Translation color" value={text.translation.color} onChange={(v) => setTr({ color: v })} />

      <Divider label="Header & reference" />
      <Toggle label="Show surah header" checked={text.header.show} onChange={(v) => setHeader({ show: v })} />
      {text.header.show ? (
        <div className="ms-1 flex flex-col gap-2 border-s border-line ps-3">
          <Toggle label="Arabic surah name" checked={text.header.showArabic} onChange={(v) => setHeader({ showArabic: v })} />
          <Toggle label="English name" checked={text.header.showEnglish} onChange={(v) => setHeader({ showEnglish: v })} />
          <SliderRow
            label="Header height"
            unit="%"
            value={text.header.topPct ?? 10}
            min={3}
            max={30}
            onChange={(v) => setHeader({ topPct: v })}
            hint="Distance of the surah header from the top edge."
          />
        </div>
      ) : null}
      <Toggle label="Ayah number marker" checked={text.showAyahNumber}
        onChange={(v) => onChange({ showAyahNumber: v })} description="Quranic verse-end marker after the Arabic text" />
    </div>
  );
}
