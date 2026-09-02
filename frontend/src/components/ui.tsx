import type { ReactNode } from "react";

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[12px] font-medium text-ink-2 tracking-wide">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[11px] leading-snug text-ink-3">{hint}</p> : null}
    </div>
  );
}

export function Select({
  id,
  value,
  onChange,
  children,
  disabled,
  ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 w-full rounded-sm border border-line bg-surface-2 px-2.5 text-[13px] text-ink transition-colors hover:border-line-strong disabled:opacity-50"
    >
      {children}
    </select>
  );
}

export function SliderRow({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
  onReset,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (v: number) => void;
  onReset?: () => void;
  hint?: string;
}) {
  const id = `sl-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-[12px] font-medium text-ink-2 tracking-wide">
          {label}
        </label>
        <span className="flex items-center gap-2">
          <output htmlFor={id} className="text-[12px] tabular-nums text-ink">
            {value}
            {unit}
          </output>
          {onReset ? (
            <button
              type="button"
              onClick={onReset}
              className="text-[11px] text-ink-3 underline-offset-2 hover:text-gold hover:underline"
            >
              reset
            </button>
          ) : null}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-xs bg-line-strong"
      />
      {hint ? <p className="text-[11px] leading-snug text-ink-3">{hint}</p> : null}
    </div>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  description,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  description?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 py-1">
      <span className="flex flex-col">
        <span className="text-[13px] text-ink">{label}</span>
        {description ? <span className="text-[11px] text-ink-3">{description}</span> : null}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors ${
          checked ? "border-gold bg-gold/90" : "border-line-strong bg-surface-2"
        }`}
      >
        <span
          className={`absolute top-0.5 h-3.5 w-3.5 rounded-full bg-canvas transition-[inset-inline-start] ${
            checked ? "start-[18px] bg-gold-ink" : "start-0.5 bg-ink-3"
          }`}
        />
      </button>
    </label>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="flex h-9 w-full items-stretch rounded-sm border border-line bg-surface-2 p-0.5"
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            type="button"
            onClick={() => onChange(o.value)}
            className={`flex-1 rounded-xs px-2 text-[12.5px] font-medium transition-colors ${
              active ? "bg-line-strong text-ink" : "text-ink-2 hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function ColorRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-0.5">
      <span className="text-[12px] font-medium text-ink-2">{label}</span>
      <span className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-ink-3">{value}</span>
        <input
          type="color"
          aria-label={`${label} color`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-6 w-8 cursor-pointer rounded-xs border border-line bg-transparent p-0.5"
        />
      </span>
    </div>
  );
}

export function Divider({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-1" aria-hidden="true">
      <span className="h-px flex-1 bg-line" />
      {label ? <span className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-3">{label}</span> : null}
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}
