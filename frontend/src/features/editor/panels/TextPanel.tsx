import type { FontCatalog, TextSettings } from "../../../types";
import { ColorRow, Divider, Field, Segmented, SliderRow, Toggle } from "../../../components/ui";

type HeaderLang = "ar" | "en" | "both" | "hidden";

function headerLang(h: TextSettings["header"]): HeaderLang {
  if (!h.show) return "hidden";
  if (h.showArabic && h.showEnglish) return "both";
  if (h.showEnglish) return "en";
  return "ar";
}

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

  const setHeaderLang = (mode: HeaderLang) => {
    if (mode === "hidden") setHeader({ show: false, showArabic: false, showEnglish: false });
    else if (mode === "ar") setHeader({ show: true, showArabic: true, showEnglish: false });
    else if (mode === "en") setHeader({ show: true, showArabic: false, showEnglish: true });
    else setHeader({ show: true, showArabic: true, showEnglish: true });
  };

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
            className="qvs-input"
          >
            {fonts.arabic.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </Field>
      ) : null}
      <SliderRow label="Arabic size" unit="px" value={text.arabic.size} min={36} max={140}
        onChange={(v) => setArabic({ size: v })}
        hint="This is the Quran text size in the video. Long verses shrink only if they overflow the card." />
      <SliderRow label="Arabic line height" value={text.arabic.lineHeight} min={0} max={5} step={0.05}
        onChange={(v) => setArabic({ lineHeight: v })}
        hint="0 stacks lines. 5 is very open. Applies to preview and the final video." />
      <ColorRow label="Arabic color" value={text.arabic.color} onChange={(v) => setArabic({ color: v })} />
      <SliderRow
        label="Arabic Position X"
        unit="%"
        value={Math.round((text.arabic.offsetX ?? 0) * 10) / 10}
        min={-40}
        max={40}
        step={0.5}
        onChange={(v) => setArabic({ offsetX: v })}
        hint="Left or right. The ayah marker moves with the Arabic text."
      />
      <SliderRow
        label="Arabic Position Y"
        unit="%"
        value={Math.round((text.arabic.offsetY ?? 0) * 10) / 10}
        min={-40}
        max={40}
        step={0.5}
        onChange={(v) => setArabic({ offsetY: v })}
        hint="Up or down. Does not change Arabic size."
      />
      <Toggle
        label="Text Outline"
        checked={!!text.outline}
        onChange={(v) => onChange({ outline: v })}
      />

      <Divider label="Translation" />
      {fonts ? (
        <Field label="Translation font" htmlFor="tr-font">
          <select
            id="tr-font"
            value={text.translation.font}
            onChange={(e) => setTr({ font: e.target.value })}
            className="qvs-input"
          >
            {fonts.latin.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </Field>
      ) : null}
      <SliderRow label="Translation size" unit="px" value={text.translation.size} min={20} max={64}
        onChange={(v) => setTr({ size: v })} />
      <SliderRow label="Translation line height" value={text.translation.lineHeight} min={0} max={5} step={0.05}
        onChange={(v) => setTr({ lineHeight: v })}
        hint="0 stacks lines. 5 is very open. Applies to preview and the final video." />
      <ColorRow label="Translation color" value={text.translation.color} onChange={(v) => setTr({ color: v })} />
      <SliderRow
        label="Translation Position X"
        unit="%"
        value={Math.round((text.translation.offsetX ?? 0) * 10) / 10}
        min={-40}
        max={40}
        step={0.5}
        onChange={(v) => setTr({ offsetX: v })}
        hint="Moves only the translation. Arabic, marker, and header stay put."
      />
      <SliderRow
        label="Translation Position Y"
        unit="%"
        value={Math.round((text.translation.offsetY ?? 0) * 10) / 10}
        min={-40}
        max={40}
        step={0.5}
        onChange={(v) => setTr({ offsetY: v })}
        hint="Does not change translation size."
      />

      <Divider label="Surah header" />
      <Field label="Header language">
        <Segmented
          ariaLabel="Surah header language"
          value={headerLang(text.header)}
          onChange={(v) => setHeaderLang(v as HeaderLang)}
          options={[
            { value: "ar", label: "Arabic" },
            { value: "en", label: "English" },
            { value: "both", label: "Both" },
            { value: "hidden", label: "Hidden" },
          ]}
        />
      </Field>
      {text.header.show ? (
        <>
          <ColorRow
            label="Header color"
            value={text.header.color ?? "#f5f1e8"}
            onChange={(v) => setHeader({ color: v })}
          />
          <SliderRow
            label="Header size"
            unit="px"
            value={text.header.size ?? 64}
            min={28}
            max={96}
            onChange={(v) => setHeader({ size: v })}
            hint="Arabic name size. English tracks at a smaller matching size. Names come from Surah metadata and cannot be edited."
          />
          <SliderRow
            label="Header position"
            unit="%"
            value={text.header.topPct ?? 10}
            min={3}
            max={30}
            onChange={(v) => setHeader({ topPct: v })}
            hint="Distance from the top edge."
          />
          {text.header.showArabic && text.header.showEnglish ? (
            <SliderRow
              label="Name gap"
              unit="px"
              value={text.header.gap ?? 18}
              min={4}
              max={48}
              onChange={(v) => setHeader({ gap: v })}
              hint="Space between the Arabic and English names."
            />
          ) : null}
          <SliderRow
            label="Header line height"
            value={text.header.lineHeight ?? 1.2}
            min={0}
            max={5}
            step={0.05}
            onChange={(v) => setHeader({ lineHeight: v })}
          />
        </>
      ) : null}
      <Toggle label="Ayah number marker" checked={text.showAyahNumber}
        onChange={(v) => onChange({ showAyahNumber: v })} description="Quranic verse-end marker after the Arabic text" />
    </div>
  );
}
