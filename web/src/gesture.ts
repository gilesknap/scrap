// Swipes, as pure functions so they are tested without a browser: which way a finished touch
// went, and where a page sits in the list it was opened from.

/** A one-finger drag across something `width` wide: +1 for a swipe to the left, -1 to the
 * right, 0 for anything else (a tap, a scroll, a short drag). A swipe is mostly sideways, and
 * either a quick flick or a drag over a third of the way across. */
export function swipeStep(dx: number, dy: number, ms: number, width: number): -1 | 0 | 1 {
  const x = Math.abs(dx);
  if (x < 2 * Math.abs(dy) || !((x >= 72 && ms <= 500) || x > width / 3)) return 0;
  return dx < 0 ? 1 : -1;
}

/** The list a page was opened from (Recent, search results): its pages' slugs in order. */
export interface Trail {
  label: string;
  slugs: string[];
}

/** Where a page is in its trail, and its neighbours; null if it isn't in it. */
export function placeIn(t: Trail | null | undefined, slug: string) {
  const i = t?.slugs.indexOf(slug) ?? -1;
  if (!t || i < 0) return null;
  return { i, n: t.slugs.length, prev: t.slugs[i - 1], next: t.slugs[i + 1] };
}
