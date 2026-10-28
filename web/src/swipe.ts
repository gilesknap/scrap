// What lists and pages share for swipes: the trail (a list marks its links with it, so a page
// opened from it can step through it: pager.ts), the screen edges left to the phone, and
// delete with Undo. The row gestures themselves are rows.ts, loaded with a list.
import { ApiError, api, type Summary } from "./api";
import type { Trail } from "./gesture";
import { toast } from "./ui";

export const EDGE = 24; // the phone's own Back gesture starts at the screen's edges: leave them to it

// ---- trails: the list a page was opened from rides in its history entry

export const trails = new WeakMap<Element, Trail>();

/** Mark a list: opening a page from it carries the list along (main.ts, trailOf). */
export function trail<T extends Element>(list: T, label: string, slugs: string[]): T {
  trails.set(list, { label, slugs });
  return list;
}

/** The trail of the list a link is in, as a history entry's state. */
export function trailOf(a: Element): { trail: Trail } | null {
  const t = trails.get(a.closest("ul") as Element);
  return t ? { trail: t } : null;
}

export type RowPage = Pick<
  Summary,
  "id" | "slug" | "title" | "kind" | "fields" | "due" | "priority" | "tasks"
>;

/** Give list rows their gestures and ticks (rows.ts) once that chunk is here: the list shows
 * at once, and its rows only open their page if the chunk can't load. Per row: the row and
 * its page. */
export function swipeRows(rows: [Element, RowPage][]) {
  import("./rows").then(
    (m) => {
      for (const [li, p] of rows) m.swipeRow(li as HTMLLIElement, p);
    },
    () => {},
  );
}

export const why = (err: unknown) =>
  err instanceof ApiError ? err.message : "can't reach the server";

/** Delete a page (from its row or its page), with Undo: gone() runs once it is deleted,
 * back() once Undo has brought it back. */
export async function deletePage(key: string, gone: () => void | Promise<void>, back: () => void) {
  try {
    await api(`pages/${key}`, { method: "DELETE" });
  } catch (err) {
    return toast(`Not deleted: ${why(err)}`);
  }
  await gone(); // e.g. back to the list: the toast is for the view it lands on
  const undo = async () => {
    try {
      await api(`pages/${key}/undelete`, { method: "POST" });
      back();
    } catch (err) {
      toast(`Undo failed: ${why(err)}`, "Try again", undo, 8000);
    }
  };
  toast("Page deleted", "Undo", undo, 8000);
}
