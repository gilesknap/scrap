// Swipes, as pure functions so they are tested without a browser: which way a finished touch
// went, and where a page sits in the list it was opened from.

/** A finished one-finger touch: +1 for a swipe to the left (the next one), -1 to the right
 * (the previous one), 0 for anything else (a tap, a scroll, a slow drag). */
export function swipeStep(dx: number, dy: number, ms: number): -1 | 0 | 1 {
  if (Math.abs(dx) < 72 || Math.abs(dx) < 2 * Math.abs(dy) || ms > 800) return 0;
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
