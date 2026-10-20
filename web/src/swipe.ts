// Swipes on lists. A list row swiped left shows its Edit and Delete (a tap on one does it;
// Delete has Undo); swiped right, or a tap anywhere, it closes. The page has the same Edit and
// Delete, for those who never swipe. A list also marks its links with a trail, so a page opened
// from it can step through it (pager.ts).
import { ApiError, api } from "./api";
import { go } from "./app";
import type { Trail } from "./gesture";
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

let openRow: HTMLLIElement | null = null;
const shut = (li: HTMLLIElement | null) => {
  if (!li) return;
  li.classList.remove("open");
  (li.firstElementChild as HTMLElement).style.transform = "";
  (li.lastElementChild as HTMLElement).inert = true;
  if (openRow === li) openRow = null;
};

/** A row's Edit and Delete, behind the row: a swipe left shows them. */
export function swipeRow(li: HTMLLIElement, slug: string) {
  const href = `/p/${encodeURIComponent(slug)}`;
  const edit = h(
    "button",
    {
      type: "button",
      onclick: () => {
        go(href, false, { ...trailOf(li), edit: true });
      },
    },
    icon("edit"),
    "Edit",
  );
  const del = h(
    "button",
    { type: "button", className: "danger", onclick: () => void remove(li, slug) },
    icon("trash"),
    "Delete",
  );
  const actions = h("div", { className: "row-actions" }, edit, del);
  actions.inert = true;
  li.classList.add("swipe");
  li.append(actions);
  const row = li.firstElementChild as HTMLElement;

  let start: { x: number; y: number; id: number } | null = null;
  let sideways = false;
  let from = 0; // the offset when the touch began
  let at = 0;
  li.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" || !e.isPrimary) return;
    if (e.clientX < EDGE || e.clientX > innerWidth - EDGE) return;
    if (openRow && openRow !== li) shut(openRow);
    start = { x: e.clientX, y: e.clientY, id: e.pointerId };
    sideways = false;
    from = at = li.classList.contains("open") ? -actions.offsetWidth : 0;
  });
  li.addEventListener("pointermove", (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!sideways) {
      if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx))
        start = null; // a scroll
      else if (Math.abs(dx) > 10) {
        sideways = true;
        li.setPointerCapture(e.pointerId);
        li.classList.add("dragging");
      }
      if (!sideways) return;
    }
    at = Math.min(0, Math.max(-actions.offsetWidth, from + dx));
    row.style.transform = `translateX(${at}px)`;
  });
  const end = (e: PointerEvent) => {
    if (!start || e.pointerId !== start.id) return;
    start = null;
    li.classList.remove("dragging");
    if (!sideways) return;
    // the row went sideways, so this touch is no tap: no click opens the page
    li.addEventListener("click", stop, { capture: true, once: true });
    setTimeout(() => li.removeEventListener("click", stop, { capture: true }), 400);
    const open = e.type === "pointerup" ? at < -actions.offsetWidth / 2 : from < 0;
    if (!open) return shut(li);
    li.classList.add("open");
    row.style.transform = `translateX(${-actions.offsetWidth}px)`;
    actions.inert = false;
    openRow = li;
  };
  li.addEventListener("pointerup", end);
  li.addEventListener("pointercancel", end);
  // An open row: a tap on it closes it, rather than opening the page
  row.addEventListener("click", (e) => {
    if (!li.classList.contains("open")) return;
    stop(e);
    shut(li);
  });
  return li;
}

function stop(e: Event) {
  e.preventDefault();
  e.stopPropagation();
}

// A tap anywhere else closes an open row, and does only that (as a tap on the row itself)
addEventListener(
  "pointerdown",
  (e) => {
    if (!openRow || openRow.contains(e.target as Node)) return;
    shut(openRow);
    addEventListener("click", stop, { capture: true, once: true });
    setTimeout(() => removeEventListener("click", stop, { capture: true }), 600);
  },
  { capture: true },
);

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

function remove(li: HTMLLIElement, slug: string) {
  return deletePage(
    encodeURIComponent(slug),
    () => {
      shut(li);
      const t = trails.get(li.parentElement as Element);
      if (t) t.slugs = t.slugs.filter((s) => s !== slug); // no swiping on to it from its list
      li.remove();
    },
    () => window.dispatchEvent(new PopStateEvent("popstate")), // the list again, with it back
  );
}
