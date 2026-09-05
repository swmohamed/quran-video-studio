import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { BackgroundClip, BackgroundEntry, BackgroundSettings } from "../../types";
import { fmtDuration } from "../../lib/time";
import {
  clampTrim,
  clipAtTime,
  clipSequenceOffset,
  clipUsedDuration,
  DEFAULT_XFADE_S,
  ensureClips,
  layersAtTime,
  makeClip,
  mapAudioToSequence,
  MIN_CLIP_S,
  sequenceDuration,
  sequenceToAudioTime,
  sourceDuration,
  XFADE_MAX_S,
  XFADE_MIN_S,
} from "../../lib/bgTimeline";

/**
 * THESIS: Background editing lives under the monitor it drives — a filmstrip
 * dock, not a distant settings-tab widget.
 * OWN-WORLD: QVS canvas / surface / gold tokens; gold only for playhead,
 * selection, and the recitation end mark.
 * STORY: Select, trim, reorder, or scrub → the preview frame updates now.
 * FIRST VIEWPORT: Compact dock attached to the preview well; clips are
 * time-proportional blocks with a source In/Out strip for the selection.
 * FORM: Lightweight NLE dock (desktop pointer first).
 */

export function BackgroundTimeline({
  backgrounds,
  settings,
  onChange,
  audioDuration,
  playhead,
  onSeek,
  onOpenLibrary,
}: {
  backgrounds: BackgroundEntry[];
  settings: BackgroundSettings;
  onChange: (patch: Partial<BackgroundSettings>) => void;
  audioDuration: number | null;
  playhead: number;
  onSeek: (t: number) => void;
  onOpenLibrary?: () => void;
}) {
  const byId = useMemo(() => new Map(backgrounds.map((b) => [b.id, b])), [backgrounds]);
  const clips = ensureClips(settings, backgrounds);
  const xfReq = settings.transitionDuration ?? DEFAULT_XFADE_S;
  const audio = audioDuration && audioDuration > 0 ? audioDuration : 0;
  const seq = sequenceDuration(clips, byId, settings.crossfade, xfReq);
  const ruler = Math.max(audio || 0, seq, 1);
  const loops = audio > 0 && seq + 0.05 < audio;
  const cuts = audio > 0 && seq > audio + 0.05;

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const selected = clips.find((c) => c.id === selectedId) ?? clips[0] ?? null;
  const selectedIndex = selected ? clips.findIndex((c) => c.id === selected.id) : -1;
  const selectedEntry = selected ? byId.get(selected.sourceId) : undefined;
  const selectedSrc = sourceDuration(selectedEntry);
  const selectedTrim = selected
    ? clampTrim(selected.trimStart, selected.trimEnd, selectedSrc)
    : { trimStart: 0, trimEnd: selectedSrc };

  const trackRef = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const addRef = useRef<HTMLDivElement>(null);
  const dragFrom = useRef<number | null>(null);

  const setClips = (next: BackgroundClip[], extra?: Partial<BackgroundSettings>) => {
    onChange({ clips: next, id: next[0]?.sourceId ?? settings.id, ...extra });
  };

  const updateClip = (id: string, patch: Partial<BackgroundClip>) => {
    setClips(clips.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  };

  const seekSeq = (seqT: number) => {
    onSeek(sequenceToAudioTime(seqT, seq, audio, playhead));
  };

  const selectAndSeek = (clip: BackgroundClip, index: number, localFrac = 0) => {
    setSelectedId(clip.id);
    const used = clipUsedDuration(clip, byId.get(clip.sourceId));
    const offset = clipSequenceOffset(clips, index, byId, settings.crossfade, xfReq);
    seekSeq(offset + Math.max(0, Math.min(1, localFrac)) * used);
  };

  const removeClip = (id: string) => {
    if (clips.length <= 1) return;
    const next = clips.filter((c) => c.id !== id);
    setSelectedId(next[0]?.id ?? null);
    setClips(next);
    if (next[0]) {
      onSeek(sequenceToAudioTime(0, sequenceDuration(next, byId, settings.crossfade, xfReq), audio, 0));
    }
  };

  const duplicateClip = (id: string) => {
    const src = clips.find((c) => c.id === id);
    if (!src) return;
    const copy = { ...src, id: `${src.id}-copy-${Date.now().toString(36)}` };
    const i = clips.findIndex((c) => c.id === id);
    const next = [...clips.slice(0, i + 1), copy, ...clips.slice(i + 1)];
    setSelectedId(copy.id);
    setClips(next);
  };

  const moveClip = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0 || from >= clips.length || to >= clips.length) return;
    const next = [...clips];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    setClips(next);
    setSelectedId(item.id);
    const idx = next.findIndex((c) => c.id === item.id);
    const offset = clipSequenceOffset(next, idx, byId, settings.crossfade, xfReq);
    onSeek(sequenceToAudioTime(offset, sequenceDuration(next, byId, settings.crossfade, xfReq), audio, playhead));
  };

  const timeFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width)));
    return x * ruler;
  };

  const scrubTo = (clientX: number) => {
    const t = timeFromClientX(clientX);
    const next = audio ? Math.min(t, audio) : t;
    onSeek(next);
    if (!clips.length) return;
    const seqT = mapAudioToSequence(next, seq, audio || seq);
    const at = clipAtTime(seqT, clips, byId, settings.crossfade, xfReq);
    const under = clips[at.index];
    if (under) setSelectedId(under.id);
  };

  useEffect(() => {
    if (selectedId && !clips.some((c) => c.id === selectedId) && clips[0]) {
      setSelectedId(clips[0].id);
    }
  }, [clips, selectedId]);

  useEffect(() => {
    if (!addOpen) return;
    const onDoc = (e: PointerEvent) => {
      if (!addRef.current?.contains(e.target as Node)) setAddOpen(false);
    };
    document.addEventListener("pointerdown", onDoc);
    return () => document.removeEventListener("pointerdown", onDoc);
  }, [addOpen]);

  useEffect(() => {
    const el = dockRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (!selected) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((e.key === "Delete" || e.key === "Backspace") && clips.length > 1) {
        e.preventDefault();
        removeClip(selected.id);
      }
      if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
        e.preventDefault();
        moveClip(selectedIndex, selectedIndex + (e.key === "ArrowLeft" ? -1 : 1));
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [selected, selectedIndex, clips.length]);

  const loopTiles = loops ? Math.ceil(audio / Math.max(seq, MIN_CLIP_S)) : 1;
  const cyclePct = (seq / ruler) * 100;

  return (
    <section
      ref={dockRef}
      tabIndex={0}
      aria-label="Background timeline"
      className="qvs-tl-dock shrink-0 outline-none"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 lg:px-4">
        <h2 className="text-[13px] font-semibold text-ink">Background</h2>
        <DurationCompare seq={seq} audio={audio} loops={loops} cuts={cuts} />
        <div className="ms-auto flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[12px] text-ink-3">Transition</span>
          <div role="radiogroup" aria-label="Clip transition" className="qvs-seg qvs-seg-compact">
            <button
              type="button"
              role="radio"
              aria-checked={!settings.crossfade}
              onClick={() => onChange({ crossfade: false })}
            >
              None
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={settings.crossfade}
              onClick={() => onChange({ crossfade: true })}
            >
              Crossfade
            </button>
          </div>
          {settings.crossfade ? (
            <label className="flex items-center gap-1.5 text-[12px] text-ink-3">
              <span className="sr-only">Transition duration</span>
              <input
                type="range"
                min={XFADE_MIN_S}
                max={XFADE_MAX_S}
                step={0.1}
                value={xfReq}
                aria-label="Transition duration"
                onChange={(e) => onChange({ transitionDuration: Number(e.target.value) })}
                className="h-1.5 w-16 cursor-pointer appearance-none rounded-xs bg-line-strong lg:w-20"
              />
              <output className="w-7 tabular-nums text-ink">{xfReq.toFixed(1)}s</output>
            </label>
          ) : null}
        </div>
      </div>

      <div className="px-3 pb-2 lg:px-4">
        <div
          ref={trackRef}
          className="relative select-none rounded-sm border border-line bg-canvas"
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).closest("[data-clip],[data-add]")) return;
            (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            scrubTo(e.clientX);
          }}
          onPointerMove={(e) => {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) scrubTo(e.clientX);
          }}
        >
          <TimeRuler ruler={ruler} />

          <div className="relative h-[4.5rem] overflow-hidden">
            {clips.length === 0 ? (
              <p className="flex h-full items-center justify-center px-3 text-[12px] text-ink-3">
                No clips yet. Add a background from your library.
              </p>
            ) : (
              Array.from({ length: loopTiles }, (_, tile) => (
                <div
                  key={tile}
                  className="absolute inset-y-0 flex"
                  style={{
                    left: `${tile * cyclePct}%`,
                    width: `${cyclePct}%`,
                    opacity: tile === 0 ? 1 : 0.32,
                    pointerEvents: tile === 0 ? "auto" : "none",
                  }}
                  aria-hidden={tile > 0}
                >
                  {clips.map((clip, i) => {
                    const entry = byId.get(clip.sourceId);
                    const start = clipSequenceOffset(clips, i, byId, settings.crossfade, xfReq);
                    const end =
                      i < clips.length - 1
                        ? clipSequenceOffset(clips, i + 1, byId, settings.crossfade, xfReq)
                        : seq;
                    const w = ((end - start) / Math.max(seq, MIN_CLIP_S)) * 100;
                    const active = tile === 0 && clip.id === selected?.id;
                    return (
                      <ClipBlock
                        key={`${tile}-${clip.id}`}
                        clip={clip}
                        index={i}
                        entry={entry}
                        widthPct={w}
                        active={active}
                        canDelete={clips.length > 1}
                        onSelect={(frac) => selectAndSeek(clip, i, frac)}
                        onDuplicate={() => duplicateClip(clip.id)}
                        onDelete={() => removeClip(clip.id)}
                        onMove={(dir) => moveClip(i, i + dir)}
                        onDragStart={() => {
                          dragFrom.current = i;
                        }}
                        onDrop={() => {
                          if (dragFrom.current != null) moveClip(dragFrom.current, i);
                          dragFrom.current = null;
                        }}
                        onTrimStart={(next) => {
                          const src = sourceDuration(byId.get(clip.sourceId));
                          const trimmed = clampTrim(next, clip.trimEnd, src);
                          updateClip(clip.id, trimmed);
                          const offset = clipSequenceOffset(clips, i, byId, settings.crossfade, xfReq);
                          seekSeq(offset);
                        }}
                        onTrimEnd={(next) => {
                          const src = sourceDuration(byId.get(clip.sourceId));
                          const trimmed = clampTrim(clip.trimStart, next, src);
                          updateClip(clip.id, trimmed);
                          const offset = clipSequenceOffset(clips, i, byId, settings.crossfade, xfReq);
                          seekSeq(offset + clipUsedDuration({ ...clip, ...trimmed }, byId.get(clip.sourceId)) - 0.04);
                        }}
                        pxPerSec={(trackRef.current?.clientWidth || 1) / ruler}
                      />
                    );
                  })}
                </div>
              ))
            )}

            {audio ? (
              <>
                <div
                  className="pointer-events-none absolute inset-y-0 z-10 w-px bg-gold"
                  style={{ left: `${Math.min(100, (audio / ruler) * 100)}%` }}
                  title="Recitation end"
                />
                {cuts ? (
                  <div
                    className="qvs-tl-hatch pointer-events-none absolute inset-y-0"
                    style={{
                      left: `${(audio / ruler) * 100}%`,
                      width: `${((ruler - audio) / ruler) * 100}%`,
                    }}
                    title="Cut at recitation end"
                  />
                ) : null}
              </>
            ) : null}

            <div
              className="pointer-events-none absolute inset-y-0 z-20"
              style={{ left: `${Math.min(100, (playhead / ruler) * 100)}%` }}
            >
              <div className="relative -ms-px h-full w-0.5 bg-gold">
                <span className="absolute -top-1 start-1/2 h-0 w-0 -translate-x-1/2 border-x-[5px] border-t-[7px] border-x-transparent border-t-gold" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {selected && selectedEntry ? (
        <SourceTrim
          entry={selectedEntry}
          order={selectedIndex + 1}
          trim={selectedTrim}
          srcDur={selectedSrc}
          playheadInClip={sourceTimeAtPlayhead(
            playhead,
            selected,
            clips,
            byId,
            settings.crossfade,
            xfReq,
            seq,
            audio,
          )}
          onTrim={(next) => {
            updateClip(selected.id, next);
            const offset = clipSequenceOffset(clips, selectedIndex, byId, settings.crossfade, xfReq);
            const used = clipUsedDuration({ ...selected, ...next }, selectedEntry);
            const local = Math.max(0, next.trimStart - selectedTrim.trimStart);
            seekSeq(offset + (local > 0 ? 0 : used - 0.04));
          }}
          onTrimToPlayhead={(edge) => {
            const srcT = sourceTimeAtPlayhead(
              playhead,
              selected,
              clips,
              byId,
              settings.crossfade,
              xfReq,
              seq,
              audio,
            );
            if (srcT == null) {
              const offset = clipSequenceOffset(clips, selectedIndex, byId, settings.crossfade, xfReq);
              seekSeq(offset);
              return;
            }
            const next =
              edge === "in"
                ? clampTrim(srcT, selectedTrim.trimEnd, selectedSrc)
                : clampTrim(selectedTrim.trimStart, srcT, selectedSrc);
            updateClip(selected.id, next);
          }}
        />
      ) : null}

      <div className="flex items-center gap-2 px-3 pb-2.5 lg:px-4">
        <div ref={addRef} className="relative" data-add>
          <button
            type="button"
            className="qvs-btn qvs-btn-ghost h-8 px-2.5 text-[12px]"
            aria-expanded={addOpen}
            aria-haspopup="true"
            onClick={() => setAddOpen((v) => !v)}
          >
            <IconPlus />
            Add clip
          </button>
          {addOpen ? (
            <div
              className="absolute bottom-[calc(100%+6px)] start-0 z-30 w-[min(22rem,calc(100vw-2rem))] rounded-sm border border-line bg-surface p-2 shadow-[var(--shadow-stage)]"
              role="listbox"
              aria-label="Add background clip"
            >
              {backgrounds.length ? (
                <div className="grid max-h-48 grid-cols-4 gap-1.5 overflow-y-auto">
                  {backgrounds.map((b) => (
                    <button
                      key={b.id}
                      type="button"
                      role="option"
                      onClick={() => {
                        const next = [...clips, makeClip(b)];
                        setSelectedId(next[next.length - 1].id);
                        setClips(next);
                        setAddOpen(false);
                        const offset = clipSequenceOffset(next, next.length - 1, byId, settings.crossfade, xfReq);
                        onSeek(
                          sequenceToAudioTime(
                            offset,
                            sequenceDuration(next, byId, settings.crossfade, xfReq),
                            audio,
                            playhead,
                          ),
                        );
                      }}
                      className="overflow-hidden rounded-xs border border-line text-start hover:border-gold/60"
                      title={`Add ${b.name}`}
                    >
                      {b.thumb ? (
                        <img src={b.thumb} alt="" className="aspect-[3/4] w-full object-cover" />
                      ) : (
                        <div className="flex aspect-[3/4] items-center justify-center bg-surface-2 text-[10px] text-ink-3">
                          {b.kind}
                        </div>
                      )}
                      <span className="block truncate px-1 py-0.5 text-[10px] text-ink-2">{b.name}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="px-1 py-2 text-[12px] text-ink-3">Upload or search in Background first.</p>
              )}
              {onOpenLibrary ? (
                <button
                  type="button"
                  className="mt-1.5 w-full text-start text-[12px] text-ink-3 hover:text-gold"
                  onClick={() => {
                    setAddOpen(false);
                    onOpenLibrary();
                  }}
                >
                  Browse library…
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <p className="min-w-0 truncate text-[11px] text-ink-3">
          Drag the grip to reorder. Drag gold edges to trim. Recitation length is the finish line.
        </p>
      </div>
    </section>
  );
}

function DurationCompare({
  seq,
  audio,
  loops,
  cuts,
}: {
  seq: number;
  audio: number;
  loops: boolean;
  cuts: boolean;
}) {
  const max = Math.max(seq, audio, 1);
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-0.5 sm:max-w-sm">
      <CompareRow label="Recitation" value={audio ? fmtDuration(audio) : "—"} width={audio ? 100 : 0} tone="gold" />
      <CompareRow
        label="Background"
        value={`${fmtDuration(seq)}${loops ? " · loops" : cuts ? " · cuts at end" : ""}`}
        width={(seq / max) * 100}
        tone="ink"
      />
    </div>
  );
}

function CompareRow({
  label,
  value,
  width,
  tone,
}: {
  label: string;
  value: string;
  width: number;
  tone: "gold" | "ink";
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-[11px] text-ink-3">{label}</span>
      <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full ${tone === "gold" ? "bg-gold" : "bg-ink-3"}`}
          style={{ width: `${Math.max(0, Math.min(100, width))}%` }}
        />
      </div>
      <span className="w-[7.5rem] shrink-0 text-end text-[11px] tabular-nums text-ink-2">{value}</span>
    </div>
  );
}

function TimeRuler({ ruler }: { ruler: number }) {
  const marks = 5;
  return (
    <div className="relative h-5 border-b border-line bg-surface-2" aria-hidden="true">
      {Array.from({ length: marks }, (_, i) => {
        const t = (ruler * i) / (marks - 1);
        return (
          <span
            key={i}
            className="absolute top-0.5 text-[10px] tabular-nums text-ink-3"
            style={{ left: `${(i / (marks - 1)) * 100}%`, transform: i === marks - 1 ? "translateX(-100%)" : undefined }}
          >
            {fmtDuration(t)}
          </span>
        );
      })}
    </div>
  );
}

function ClipBlock({
  clip,
  index,
  entry,
  widthPct,
  active,
  canDelete,
  onSelect,
  onDuplicate,
  onDelete,
  onMove,
  onDragStart,
  onDrop,
  onTrimStart,
  onTrimEnd,
  pxPerSec,
}: {
  clip: BackgroundClip;
  index: number;
  entry: BackgroundEntry | undefined;
  widthPct: number;
  active: boolean;
  canDelete: boolean;
  onSelect: (frac: number) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onMove: (dir: -1 | 1) => void;
  onDragStart: () => void;
  onDrop: () => void;
  onTrimStart: (next: number) => void;
  onTrimEnd: (next: number) => void;
  pxPerSec: number;
}) {
  const used = clipUsedDuration(clip, entry);
  const name = entry?.name ?? clip.sourceId;
  return (
    <div
      data-clip
      className={`group relative h-full min-w-[4.5rem] shrink-0 overflow-hidden border-e border-canvas ${
        active ? "z-10 ring-1 ring-inset ring-gold" : "hover:ring-1 hover:ring-inset hover:ring-line-strong"
      }`}
      style={{ width: `${Math.max(8, widthPct)}%` }}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        const r = e.currentTarget.getBoundingClientRect();
        onSelect((e.clientX - r.left) / Math.max(1, r.width));
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      {entry?.thumb ? (
        <div className="flex h-full">
          <img src={entry.thumb} alt="" className="h-full w-11 shrink-0 object-cover" />
          <img src={entry.thumb} alt="" className="h-full min-w-0 flex-1 object-cover opacity-55" />
        </div>
      ) : (
        <div className="h-full w-full bg-surface-2" />
      )}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-1.5 pb-1 pt-4">
        <div className="flex items-baseline gap-1">
          <span className="text-[10px] font-semibold tabular-nums text-gold">{index + 1}</span>
          <span className="min-w-0 truncate text-[11px] leading-tight text-ink">{name}</span>
        </div>
        <span className="text-[10px] tabular-nums text-ink-2">{fmtDuration(used)}</span>
      </div>

      <button
        type="button"
        draggable
        title="Drag to reorder"
        aria-label={`Reorder clip ${index + 1}`}
        className="absolute start-0.5 top-0.5 hidden h-6 w-5 cursor-grab items-center justify-center rounded-xs bg-black/65 text-ink-2 hover:text-ink group-hover:flex"
        onClick={(e) => e.stopPropagation()}
        onDragStart={onDragStart}
      >
        <IconGrip />
      </button>

      {active ? (
        <div className="absolute end-0.5 top-0.5 flex gap-0.5 rounded-xs bg-black/70 p-0.5">
          <IconBtn label="Trim" title="Trim this clip" onClick={() => onSelect(0)}>
            <IconTrim />
          </IconBtn>
          <IconBtn label="Duplicate" title="Duplicate clip" onClick={onDuplicate}>
            <IconCopy />
          </IconBtn>
          <IconBtn label="Move earlier" title="Move earlier" onClick={() => onMove(-1)}>
            <IconChevL />
          </IconBtn>
          <IconBtn label="Move later" title="Move later" onClick={() => onMove(1)}>
            <IconChevR />
          </IconBtn>
          <IconBtn
            label="Delete"
            title={canDelete ? "Delete clip" : "Need at least one clip"}
            onClick={onDelete}
            disabled={!canDelete}
            danger
          >
            <IconTrash />
          </IconBtn>
        </div>
      ) : null}

      {active ? (
        <>
          <TrimHandle
            edge="start"
            value={clip.trimStart}
            onValue={onTrimStart}
            pxPerSec={pxPerSec}
          />
          <TrimHandle
            edge="end"
            value={clip.trimEnd}
            onValue={onTrimEnd}
            pxPerSec={pxPerSec}
          />
        </>
      ) : null}
    </div>
  );
}

function TrimHandle({
  edge,
  value,
  onValue,
  pxPerSec,
}: {
  edge: "start" | "end";
  value: number;
  onValue: (next: number) => void;
  pxPerSec: number;
}) {
  return (
    <button
      type="button"
      aria-label={edge === "start" ? "Trim start" : "Trim end"}
      title={edge === "start" ? "Trim start" : "Trim end"}
      className={`absolute inset-y-0 z-10 flex w-2.5 cursor-ew-resize items-center justify-center bg-gold hover:bg-gold-strong ${
        edge === "start" ? "start-0" : "end-0"
      }`}
      onPointerDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        const startX = e.clientX;
        const origin = value;
        const live = (ev: PointerEvent) => {
          onValue(origin + (ev.clientX - startX) / Math.max(8, pxPerSec));
        };
        const end = () => {
          window.removeEventListener("pointermove", live);
          window.removeEventListener("pointerup", end);
        };
        window.addEventListener("pointermove", live);
        window.addEventListener("pointerup", end);
      }}
    >
      <span className="h-6 w-px bg-gold-ink/50" />
    </button>
  );
}

function SourceTrim({
  entry,
  order,
  trim,
  srcDur,
  playheadInClip,
  onTrim,
  onTrimToPlayhead,
}: {
  entry: BackgroundEntry;
  order: number;
  trim: { trimStart: number; trimEnd: number };
  srcDur: number;
  playheadInClip: number | null;
  onTrim: (next: { trimStart: number; trimEnd: number }) => void;
  onTrimToPlayhead: (edge: "in" | "out") => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const used = Math.max(MIN_CLIP_S, trim.trimEnd - trim.trimStart);
  const left = srcDur > 0 ? (trim.trimStart / srcDur) * 100 : 0;
  const width = srcDur > 0 ? (used / srcDur) * 100 : 100;

  const applyAtX = (clientX: number, edge: "in" | "out") => {
    const el = barRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const t = Math.max(0, Math.min(srcDur, ((clientX - r.left) / Math.max(1, r.width)) * srcDur));
    onTrim(edge === "in" ? clampTrim(t, trim.trimEnd, srcDur) : clampTrim(trim.trimStart, t, srcDur));
  };

  return (
    <div className="flex flex-col gap-1.5 border-t border-line px-3 py-2 lg:px-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 truncate text-[12px] text-ink">
          <span className="me-1 tabular-nums text-gold">{order}</span>
          {entry.name}
        </span>
        <span className="text-[12px] tabular-nums text-ink-3">
          {fmtPrecise(trim.trimStart)}–{fmtPrecise(trim.trimEnd)} of {fmtPrecise(srcDur)}
          {" · "}
          {fmtPrecise(used)} used
        </span>
        <div className="ms-auto flex gap-1">
          <button
            type="button"
            className="qvs-btn qvs-btn-ghost h-7 px-2 text-[11px]"
            title="Set In to the playhead in this clip"
            onClick={() => onTrimToPlayhead("in")}
          >
            Trim Start
          </button>
          <button
            type="button"
            className="qvs-btn qvs-btn-ghost h-7 px-2 text-[11px]"
            title="Set Out to the playhead in this clip"
            onClick={() => onTrimToPlayhead("out")}
          >
            Trim End
          </button>
        </div>
      </div>
      <div
        ref={barRef}
        className="relative h-3 overflow-hidden rounded-full bg-line"
        role="slider"
        aria-label="Source in and out"
        aria-valuemin={0}
        aria-valuemax={srcDur}
        aria-valuenow={trim.trimStart}
      >
        <div
          className="absolute inset-y-0 rounded-full bg-gold/80"
          style={{ left: `${left}%`, width: `${Math.max(2, width)}%` }}
        />
        {playheadInClip != null && srcDur > 0 ? (
          <span
            className="absolute inset-y-0 w-px bg-gold"
            style={{ left: `${(playheadInClip / srcDur) * 100}%` }}
          />
        ) : null}
        <button
          type="button"
          aria-label="Trim start"
          className="absolute inset-y-0 z-10 w-2 cursor-ew-resize bg-gold"
          style={{ left: `${left}%` }}
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const move = (ev: PointerEvent) => applyAtX(ev.clientX, "in");
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
          }}
        />
        <button
          type="button"
          aria-label="Trim end"
          className="absolute inset-y-0 z-10 w-2 cursor-ew-resize bg-gold"
          style={{ left: `calc(${left + width}% - 8px)` }}
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const move = (ev: PointerEvent) => applyAtX(ev.clientX, "out");
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
          }}
        />
      </div>
    </div>
  );
}

function sourceTimeAtPlayhead(
  playhead: number,
  clip: BackgroundClip,
  clips: BackgroundClip[],
  byId: Map<string, BackgroundEntry>,
  crossfade: boolean,
  requested: number,
  seq: number,
  audio: number,
): number | null {
  if (!clips.length) return null;
  const seqT = mapAudioToSequence(playhead, seq, audio || seq);
  const layers = layersAtTime(seqT, clips, byId, crossfade, requested);
  const hit = layers.find((l) => clips[l.index]?.id === clip.id);
  if (hit) return hit.sourceTime;
  return null;
}

function fmtPrecise(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const whole = Math.floor(s);
  const tenth = Math.round((s - whole) * 10);
  const adj = tenth === 10 ? { whole: whole + 1, tenth: 0 } : { whole, tenth };
  return `${m}:${String(adj.whole).padStart(2, "0")}.${adj.tenth}`;
}

function IconBtn({
  label,
  title,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  title: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`flex h-6 w-6 items-center justify-center rounded-xs text-ink-2 hover:bg-line-strong hover:text-ink disabled:opacity-35 ${
        danger ? "hover:text-danger" : ""
      }`}
    >
      {children}
    </button>
  );
}

function IconGrip() {
  return (
    <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden="true">
      <circle cx="3" cy="2" r="1" />
      <circle cx="7" cy="2" r="1" />
      <circle cx="3" cy="6" r="1" />
      <circle cx="7" cy="6" r="1" />
      <circle cx="3" cy="10" r="1" />
      <circle cx="7" cy="10" r="1" />
    </svg>
  );
}

function IconTrim() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M3 1.5v9M9 1.5v9M3 6h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function IconCopy() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8.5 3.2V2.5A1 1 0 0 0 7.5 1.5h-5A1 1 0 0 0 1.5 2.5v5a1 1 0 0 0 1 1h.7" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M2 3.5h8M5 3.5V2h2v1.5M3.2 3.5l.5 6.2h4.6l.5-6.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevL() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path d="M6.5 1.5 3 5l3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevR() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path d="M3.5 1.5 7 5l-3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M6 2v8M2 6h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
