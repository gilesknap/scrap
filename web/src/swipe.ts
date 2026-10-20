// Swipes on lists and pages. A list row swiped left shows its Edit and Delete (a tap on one
// does it; Delete has Undo); swiped right, or a tap elsewhere, it closes. A page opened from a
// list swipes, or arrow-keys, to the previous or next page in that list. Every swipe has a
// button too: the page's own Edit and Delete, and the page's ‹ › pager.
import { ApiError, api } from "./api";
import { go, view } from "./app";
import { swipeStep, type Trail } from "./gesture";
import { icon } from "./icons";
import { h, toast } from "./ui";

const EDGE = 24; // the phone's own Back gesture starts at the screen's edges: leave them to it

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

async function remove(li: HTMLLIElement, slug: string) {
  const key = encodeURIComponent(slug);
  try {
    await api(`pages/${key}`, { method: "DELETE" });
  } catch (err) {
    return toast(`Not deleted: ${why(err)}`);
  }
  shut(li);
  const list = li.parentElement;
  const t = list && trails.get(list);
  if (t) t.slugs = t.slugs.filter((s) => s !== slug); // no swiping on to it from its list
  li.remove();
  const undo = async () => {
    try {
      await api(`pages/${key}/undelete`, { method: "POST" });
      window.dispatchEvent(new PopStateEvent("popstate")); // the list again, with it back
    } catch (err) {
      toast(`Undo failed: ${why(err)}`, "Try again", undo, 8000);
    }
  };
  toast("Page deleted", "Undo", undo, 8000);
}

// ---- pages: swipe to the previous or next in the trail

/** Calls step(+1) for a swipe left or the right arrow, step(-1) the other way, while the
 * view lasts. Not inside anything that scrolls sideways or takes typing, not from the
 * screen's edges, not while zoomed in, selecting text, or with a layer (editor, photo,
 * drawing) open. */
export function swipePages(step: (d: 1 | -1) => void) {
  const blocked = () => document.body.matches(".editing, .viewing, .drawing-open");
  const typing = (t: EventTarget | null) =>
    t instanceof Element && !!t.closest("input, textarea, select, [contenteditable]");
  const scrolls = (t: EventTarget | null) => {
    for (let el = t instanceof Element ? t : null; el && el.id !== "view"; el = el.parentElement) {
      if (el.scrollWidth > el.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(el).overflowX))
        return true;
    }
    return false;
  };
  let start: { x: number; y: number; t: number } | null = null;
  const signal = view.signal;
  document.addEventListener(
    "touchstart",
    (e) => {
      const p = e.touches[0];
      start = null;
      if (e.touches.length !== 1 || blocked() || typing(e.target) || scrolls(e.target)) return;
      if (!(e.target instanceof Element && e.target.closest("#view"))) return;
      if (p.clientX < EDGE || p.clientX > innerWidth - EDGE) return;
      if ((visualViewport?.scale ?? 1) > 1.01) return; // zoomed in: the touch pans the page
      start = { x: p.clientX, y: p.clientY, t: e.timeStamp };
    },
    { signal, passive: true },
  );
  document.addEventListener(
    "touchmove",
    (e) => {
      if (e.touches.length > 1) start = null; // a pinch
    },
    { signal, passive: true },
  );
  document.addEventListener(
    "touchcancel",
    () => {
      start = null; // e.g. the phone took it for its Back gesture
    },
    { signal },
  );
  document.addEventListener(
    "touchend",
    (e) => {
      const p = e.changedTouches[0];
      if (!start || e.touches.length) return;
      const d = swipeStep(p.clientX - start.x, p.clientY - start.y, e.timeStamp - start.t);
      start = null;
      if (!d || blocked() || !getSelection()?.isCollapsed) return;
      step(d);
    },
    { signal },
  );
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || blocked() || typing(e.target)) return;
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    },
    { signal },
  );
}
