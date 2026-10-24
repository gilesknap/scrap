// A page opened from a list (Recent, search results): where it is in it, and the previous
// and next by its ‹ ›, a swipe or the arrow keys. A chunk of its own, loaded only for such a
// page. Between them, where it is ("3 of 8 · Todos · Now"), a label. Each step replaces the
// page's history entry, so the top bar's Back still goes back to the list. Mark done on a todo
// opened from the Todos screen moves on to the next one in that list.
import { type Page, setStatus } from "./api";
import { go, plain } from "./app";
import { placeIn, swipeStep, type Trail } from "./gesture";
import { icon } from "./icons";
import { EDGE } from "./swipe";
import { h, toast } from "./ui";

/** The pager for a page (null if it isn't in the trail), and the swipes and keys for it
 * while its view lasts (signal). A step says in the history entry which way it went, so the
 * next page slides in from that side. */
export function pager(
  { trail, from }: { trail?: Trail; from?: 1 | -1 },
  slug: string,
  root: HTMLElement,
  signal: AbortSignal,
) {
  const at = placeIn(trail, slug);
  if (!trail || !at || signal.aborted) return null;
  if (from) {
    // slide in from that side once: not again on Back, Forward or a reload
    root.classList.add(from > 0 ? "from-next" : "from-prev");
    history.replaceState({ ...history.state, from: 0 }, "");
  }
  const step = (d: 1 | -1) => {
    const to = d > 0 ? at.next : at.prev;
    if (signal.aborted) return; // gone elsewhere meanwhile: never replace that entry
    if (!to) return toast(d > 0 ? "That's the last in the list" : "That's the first in the list");
    go(`/p/${encodeURIComponent(to)}`, true, { trail, from: d });
  };
  // Real links (long-press or Ctrl-click opens the next page in a new tab); a plain tap steps
  // here, in place, so Back still goes back to the list
  const link = (d: 1 | -1, label: string, to?: string) =>
    h(
      "a",
      {
        className: "button ghost",
        "aria-label": label,
        ...(to
          ? { href: `/p/${encodeURIComponent(to)}` }
          : { role: "link", "aria-disabled": "true" }),
        onclick: (e: MouseEvent) => {
          if (!plain(e)) return;
          e.preventDefault();
          step(d);
        },
      },
      icon(d > 0 ? "down" : "up"),
    );
  swipePages(step, at, signal);
  const el = h(
    "div",
    { className: "pager", role: "group", "aria-label": `In ${trail.label}` },
    // In the top bar, as a mail app has it: where it is, then ∧ ∨ (Back, beside it, names the
    // list)
    h("span", { className: "at" }, `${at.i + 1} of ${at.n}`),
    link(-1, "Previous", at.prev),
    link(1, "Next", at.next),
  );
  /** Marked done (p as saved; was: its status before): from the Todos screen, on to the next
   * todo in its list, saying so with an Undo (true); else false, and it stays. */
  const done = (p: Page, was: string) => {
    if (!trail.label.startsWith("Todos ·")) return false;
    if (!at.next) {
      toast(
        "Done: that was the last in the list",
        "Back to list",
        () => document.getElementById("back")?.click(),
        6000,
      );
      return false;
    }
    step(1);
    const undo = () =>
      setStatus(p.id, was).then(
        () => go(`/p/${encodeURIComponent(p.slug)}`, true, { trail, from: -1 }),
        () => toast("Undo failed: can't reach the server"),
      );
    toast(`Done: ${p.title}. Next todo, ${at.i + 2} of ${at.n}`, "Undo", undo, 6000);
    return true;
  };
  return Object.assign(el, { done });
}

/** Calls step(+1) for a swipe left or the right arrow, step(-1) the other way, while the
 * view lasts. Not inside anything that scrolls sideways or takes typing, not from the
 * screen's edges, not while zoomed in, selecting text, or with a layer (editor, photo,
 * drawing) open. */
function swipePages(
  step: (d: 1 | -1) => void,
  at: { prev?: string; next?: string },
  signal: AbortSignal,
) {
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
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
  // The page follows the finger sideways, then slides off (the next one comes in from that
  // side) or settles back. Passive listeners: scrolling and zooming stay the browser's.
  let start: { x: number; y: number; t: number } | null = null;
  let sideways = false;
  const page = () => document.querySelector<HTMLElement>("#view > .page");
  const slide = (x: number, glide: boolean) => {
    const el = page();
    if (!el) return;
    el.style.transition = glide
      ? "translate var(--d-2) var(--ease), opacity var(--d-2) linear"
      : "none";
    el.style.translate = x ? `${x}px 0` : "";
    el.style.opacity = x ? String(1 - Math.min(0.6, Math.abs(x) / innerWidth)) : "";
  };
  const on = <K extends keyof DocumentEventMap>(type: K, fn: (e: DocumentEventMap[K]) => void) =>
    document.addEventListener(type, fn, { signal, passive: true });
  on("touchstart", (e) => {
    const p = e.touches[0];
    start = null;
    sideways = false;
    if (e.touches.length !== 1 || blocked() || typing(e.target) || scrolls(e.target)) return;
    if (!(e.target instanceof Element && e.target.closest("#view"))) return;
    if (p.clientX < EDGE || p.clientX > innerWidth - EDGE) return;
    if ((visualViewport?.scale ?? 1) > 1.01) return; // zoomed in: the touch pans the page
    start = { x: p.clientX, y: p.clientY, t: e.timeStamp };
  });
  on("touchmove", (e) => {
    if (!start) return;
    if (e.touches.length > 1 || !getSelection()?.isCollapsed) return cancel(); // a pinch, a selection
    const dx = e.touches[0].clientX - start.x;
    const dy = e.touches[0].clientY - start.y;
    if (!sideways) {
      if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx))
        start = null; // a scroll
      else if (Math.abs(dx) > 10) sideways = true;
      if (!sideways) return;
    }
    const to = dx < 0 ? at.next : at.prev;
    slide(to ? dx : dx / 4, false); // at an end it only gives a little
  });
  const cancel = () => {
    if (sideways) slide(0, true);
    start = null;
    sideways = false;
  };
  on("touchcancel", cancel); // e.g. the phone took it for its Back gesture
  on("touchend", (e) => {
    const p = e.changedTouches[0];
    if (!start || !sideways || e.touches.length) return cancel();
    const dx = p.clientX - start.x;
    const d = swipeStep(dx, p.clientY - start.y, e.timeStamp - start.t, innerWidth);
    const to = d > 0 ? at.next : at.prev;
    start = null;
    sideways = false;
    if (!d || !to) {
      slide(0, true);
      if (d) step(d); // says it is the first or last
      return;
    }
    slide(dx < 0 ? -innerWidth : innerWidth, true);
    setTimeout(() => step(d), reduced() ? 0 : 150);
  });
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
