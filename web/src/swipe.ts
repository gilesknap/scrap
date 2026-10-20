// Swipes on lists. A list row swiped left deletes its page (with Undo); swiped right, opens it
// in the editor. The page has the same Edit and Delete, for those who never swipe. A list also marks its links with a trail, so a page opened
// from it can step through it (pager.ts).
import { ApiError, api } from "./api";
import { go, rerender } from "./app";
import { swipeStep, type Trail } from "./gesture";
import { icon } from "./icons";
import { h, toast } from "./ui";

export const EDGE = 24; // the phone's own Back gesture starts at the screen's edges: leave them to it

// ---- trails: the list a page was opened from rides in its history entry

const trails = new WeakMap<Element, Trail>();

/** Mark a list: opening a page from it carries the list along (main.ts, trailOf). */
export function trail<T extends Element>(list: T, label: string, slugs: string[]): T {
  trails.set(list, { label, slugs });
  return list;
}

/** The trail of the list a link is in, as a history entry's state. */
export function trailOf(a: Element): { trail: Trail } | null {
  for (let el = a.parentElement; el; el = el.parentElement) {
    const t = trails.get(el);
    if (t) return { trail: t };
  }
  return null;
}

// ---- list rows

/** A row swiped right opens its page in the editor; swiped left, deletes it (with Undo). It
 * follows the finger, with what letting go would do shown behind it. */
export function swipeRow(li: HTMLLIElement, slug: string) {
  const under = h(
    "div",
    { className: "row-under", "aria-hidden": "true" },
    h("span", {}, icon("edit"), "Edit"),
    h("span", {}, icon("trash"), "Delete"),
  );
  li.classList.add("swipe");
  li.prepend(under);
  const row = li.lastElementChild as HTMLElement;
  const move = (x: number, glide: boolean) => {
    row.style.transition = glide ? "" : "none"; // 1:1 with the finger; glides when let go
    row.style.transform = x ? `translateX(${x}px)` : "";
  };

  let start: { x: number; y: number; t: number; id: number } | null = null;
  let sideways = false;
  li.addEventListener("pointerdown", (e) => {
    sideways = false;
    if (e.pointerType === "mouse" || !e.isPrimary) return;
    if (e.clientX < EDGE || e.clientX > innerWidth - EDGE) return;
    start = { x: e.clientX, y: e.clientY, t: e.timeStamp, id: e.pointerId };
  });
  li.addEventListener("pointermove", (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!sideways) {
      if (Math.abs(dy) > 8 && Math.abs(dy) >= Math.abs(dx))
        start = null; // a scroll
      else if (Math.abs(dx) > 8) {
        sideways = true;
        li.setPointerCapture(e.pointerId);
      }
      if (!sideways) return;
    }
    const d = swipeStep(dx, dy, 0, li.offsetWidth); // past the point of no return?
    li.className = `swipe ${dx < 0 ? "to-delete" : "to-edit"}${d ? " armed" : ""}`;
    move(dx, false);
  });
  const end = (e: PointerEvent) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const d =
      e.type === "pointerup" &&
      swipeStep(dx, e.clientY - start.y, e.timeStamp - start.t, li.offsetWidth);
    start = null;
    if (!sideways) return;
    if (d === 1) {
      move(-li.offsetWidth, true); // off it goes
      void remove(li, slug).then(() => li.isConnected && move(0, true)); // or not deleted
    } else {
      move(0, true);
      li.classList.remove("armed");
      if (d === -1) go(`/p/${encodeURIComponent(slug)}`, false, { ...trailOf(li), edit: true });
    }
  };
  li.addEventListener("pointerup", end);
  li.addEventListener("pointercancel", end);
  // A touch that moved the row is no tap: no click opens the page
  li.addEventListener(
    "click",
    (e) => {
      if (!sideways) return;
      e.preventDefault();
      e.stopPropagation();
    },
    true,
  );
  return li;
}

const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

/** Delete a page (from its row or its page), with Undo: gone() runs once it is deleted,
 * back() once Undo has brought it back. */
export async function deletePage(key: string, gone: () => void, back: () => void) {
  try {
    await api(`pages/${key}`, { method: "DELETE" });
  } catch (err) {
    return toast(`Not deleted: ${why(err)}`);
  }
  gone();
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

async function remove(li: HTMLLIElement, slug: string) {
  await deletePage(
    encodeURIComponent(slug),
    () => {
      const t = trails.get(li.parentElement as Element);
      if (t) t.slugs = t.slugs.filter((s) => s !== slug); // no swiping on to it from its list
      li.remove();
    },
    rerender, // the list again, with it back
  );
  if (li.isConnected)
    li.querySelector<HTMLElement>(":scope > a")?.style.removeProperty("transform"); // not deleted
}
