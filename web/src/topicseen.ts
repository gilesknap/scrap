// What this device has seen of Claude's topics (#261), for the Topics screen's dots: each
// topic's last change as it was last shown ({id: updated_at}, scrap.topics.seen, on the device
// only), and the dots shown while the app is open. A topic's page, shown however it was
// reached, counts as seeing it (page.ts). Tiny: shared by the Topics screen and the page view.
import { kept } from "./api";

const SEEN = "scrap.topics.seen";
/** The topics with a dot while the app is open: new or changed since the last time. */
export const dots = new Set<string>();

/** What this device saw last time: {id: updated_at}, or null if it never looked (or has no
 * storage, or holds something else). */
export function seen(): Record<string, string> | null {
  try {
    const got = JSON.parse(kept(SEEN) ?? "null");
    return got && typeof got === "object" && !Array.isArray(got) ? got : null;
  } catch {
    return null;
  }
}

/** The topics new or changed since then: none the first time (all would be). */
export function changed(
  rows: { id: string; updated_at: string }[],
  was: Record<string, string> | null,
): Set<string> {
  if (!was) return new Set();
  return new Set(rows.filter((r) => was[r.id] !== r.updated_at).map((r) => r.id));
}

/** Remember the topics as shown now, for the next look. */
export const look = (rows: { id: string; updated_at: string }[]) =>
  kept(SEEN, JSON.stringify(Object.fromEntries(rows.map((r) => [r.id, r.updated_at]))));

/** A topic's page was shown, as it is at stamp (its synthesis's time, else the page's: as the
 * index has it): no dot for it now or next time. Before the first look at the Topics screen,
 * nothing is kept (that look shows no dots anyway). */
export function seenTopic(id: string, stamp: string) {
  dots.delete(id);
  const was = seen();
  if (was && was[id] !== stamp) kept(SEEN, JSON.stringify({ ...was, [id]: stamp }));
}
