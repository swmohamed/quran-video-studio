/** Dynamic QCF v2 (Quran.com p{N}-v2) page-font loader. */

const loading = new Map<number, Promise<boolean>>();
const ready = new Set<number>();

export function qpcFamily(page: number): string {
  return `p${page}-v2`;
}

export function isQpcReady(page: number): boolean {
  return ready.has(page);
}

export function ensureQpcFont(page: number): Promise<boolean> {
  if (!Number.isInteger(page) || page < 1 || page > 604) return Promise.resolve(false);
  if (ready.has(page)) return Promise.resolve(true);
  const hit = loading.get(page);
  if (hit) return hit;
  const family = qpcFamily(page);
  const face = new FontFace(family, `url(/api/qpc/font/${page}) format("truetype")`);
  const task = face
    .load()
    .then((loaded) => {
      document.fonts.add(loaded);
      ready.add(page);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      loading.delete(page);
    });
  loading.set(page, task);
  return task;
}

export function prefetchQpcPages(pages: Iterable<number | undefined>): void {
  const seen = new Set<number>();
  for (const p of pages) {
    if (typeof p === "number" && !seen.has(p)) {
      seen.add(p);
      void ensureQpcFont(p);
    }
  }
}
