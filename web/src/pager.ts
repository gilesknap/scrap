// A page opened from a list (Recent, search results): where it is in it, and the previous
// and next by its ‹ ›, a swipe or the arrow keys. A chunk of its own, loaded only for such a
// page. Each step replaces the page's history entry, so Back still goes back to the list.
import { go, view } from "./app";
import { placeIn, swipeStep, type Trail } from "./gesture";
import { icon } from "./icons";
import { EDGE } from "./swipe";
import { h, toast } from "./ui";

let arriving = 0; // the way the last step went: the next page slides in from that side

/** The pager for a page (null if it isn't in the trail), and the swipes and keys for it. */
export function pager(trail: Trail | undefined, slug: string, root: HTMLElement) {
  if (arriving) root.classList.add(arriving > 0 ? "from-next" : "from-prev");
  arriving = 0;
  const at = placeIn(trail, slug);
  if (!trail || !at) return null;
  const step = (d: 1 | -1) => {
    const to = d > 0 ? at.next : at.prev;
    if (!to) return toast(d > 0 ? "That's the last in the list" : "That's the first in the list");
    arriving = d;
    go(`/p/${encodeURIComponent(to)}`, true, { trail });
  };
  const button = (d: 1 | -1, label: string, to?: string) =>
    h(
      "button",
      {
        type: "button",
        className: "ghost",
        "aria-label": label,
        disabled: !to,
        onclick: () => step(d),
      },
      icon(d > 0 ? "next" : "back"),
    );
  swipePages(step);
  return h(
    "div",
    { className: "pager", role: "group", "aria-label": `In ${trail.label}` },
    button(-1, "Previous", at.prev),
    h("span", {}, `${at.i + 1} of ${at.n} · ${trail.label}`),
    button(1, "Next", at.next),
  );
}

/** Calls step(+1) for a swipe left or the right arrow, step(-1) the other way, while the
 * view lasts. Not inside anything that scrolls sideways or takes typing, not from the
 * screen's edges, not while zoomed in, selecting text, or with a layer (editor, photo,
 * drawing) open. */
function swipePages(step: (d: 1 | -1) => void) {
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
