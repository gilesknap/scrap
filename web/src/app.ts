// Shared by the views: the one capture queue and navigation.
import { kept, send, stallLimit } from "./api";
import { idb } from "./db";
import { Queue } from "./queue";

const stall = () => stallLimit(kept("scrap.stall_ms"));
export const queue = new Queue(
  idb,
  (item) => send(item, XMLHttpRequest, stall()),
  Date.now,
  () => navigator.onLine,
);

/** Navigate inside the app; main.ts renders on popstate. The state rides in the history
 * entry (e.g. the list a page was opened from). */
export function go(path: string, replace = false, state: object | null = null) {
  // A step back of the app's own still on its way (the Filters sheet closed): after it lands,
  // or it would land on this new entry and undo it
  if (back.pending) return void back.pending.then(() => go(path, replace, state));
  history[replace ? "replaceState" : "pushState"](state, "", path);
  window.scrollTo(0, 0);
  rerender();
}

/** Write the current entry's address (a new query, say), keeping the Filters sheet's mark on
 * its entry. While a step back of the app's own is on its way, on the entry it lands on, after
 * the sheet's own write there (so the newest address wins). */
export function address(path: string) {
  if (back.pending) return void back.pending.then(() => address(path));
  history.replaceState(history.state?.sheet ? { sheet: 1 } : null, "", path);
}

/** A plain click (or tap) the app may route itself: not one meant for a new tab or window
 * (Ctrl, Cmd, Shift, Alt, a middle click) nor one a handler already took. */
export const plain = (e: MouseEvent) =>
  !e.defaultPrevented && e.button === 0 && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey);

/** Show the current view again (main.ts renders on popstate). */
export const rerender = () => window.dispatchEvent(new PopStateEvent("popstate"));

let land = () => {};
/** take: while set (the Filters sheet is open), Back runs it instead of showing a view
 * (main.ts). pending: while a step back of the app's own (pop()) is on its way, which
 * go() and the sheet wait for; landed() (main.ts, on the browser's popstate) ends it. */
export const back = {
  take: null as (() => void) | null,
  pending: null as Promise<void> | null,
  pop() {
    back.pending ??= new Promise((r) => {
      land = r;
    });
    history.back();
  },
  landed() {
    back.pending = null;
    land();
  },
};

/** Aborted when the view changes: views pass it to their event listeners. */
export const view = { signal: new AbortController().signal };

/** Mark the nav's tab for what is on screen (/search, with or without a query, is Search). */
export function markNav() {
  for (const a of document.querySelectorAll<HTMLAnchorElement>("nav a"))
    a.toggleAttribute("aria-current", a.pathname === location.pathname);
}
