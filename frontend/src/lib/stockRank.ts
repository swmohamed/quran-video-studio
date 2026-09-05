import type { StockItem } from "../types";

export type StockOrientation = "portrait" | "landscape" | "square";

export function classifyOrientation(width: number | null, height: number | null): StockOrientation | null {
  if (!width || !height) return null;
  const ratio = width / height;
  if (ratio >= 1.15) return "landscape";
  if (ratio <= 0.87) return "portrait";
  return "square";
}

export function itemOrientation(item: StockItem): StockOrientation | null {
  return item.orientation ?? classifyOrientation(item.width, item.height);
}

export function isGoodMatch(
  item: StockItem,
  audioDuration: number | null,
  target: StockOrientation,
): boolean {
  const orient = itemOrientation(item);
  if (orient !== target) return false;
  if (item.kind !== "video") return true;
  if (audioDuration == null || audioDuration <= 0) return false;
  const dur = item.duration ?? 0;
  if (dur + 1 < audioDuration) return false;
  // Close enough to avoid labeling every longer clip as a match.
  return dur <= audioDuration * 2 + 1;
}

/** Mirror of backend rank_stock_items — re-sort when audio duration changes. */
export function rankStockItems(
  items: StockItem[],
  audioDuration: number | null,
  targetOrientation: StockOrientation | null,
): StockItem[] {
  const wantDur = audioDuration != null && audioDuration > 0;
  const target = targetOrientation;

  const key = (item: StockItem): [number, number, number, number, number] => {
    const suit = item.kind === "video" ? (item.suitScore ?? 1) : 1;
    let durBucket = 0;
    let durDelta = 0;
    if (wantDur && item.kind === "video") {
      const dur = item.duration;
      if (dur != null && dur > 0) {
        if (dur + 1 >= audioDuration!) {
          durBucket = 0;
          durDelta = Math.abs(dur - audioDuration!);
        } else {
          durBucket = 1;
          durDelta = audioDuration! - dur;
        }
      } else {
        durBucket = 2;
      }
    }
    const orient = itemOrientation(item);
    const orientBucket = target && orient ? (orient === target ? 0 : 1) : 0;
    const res = -((item.width ?? 0) * (item.height ?? 0));
    return [suit, durBucket, durDelta, orientBucket, res];
  };

  return [...items].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2] || ka[3] - kb[3] || ka[4] - kb[4];
  });
}
