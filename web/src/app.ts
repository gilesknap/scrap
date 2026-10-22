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
  // Marked as pushed by the app, so the top bar's Back knows an entry of the app's is behind
  // it (main.ts); a replace keeps the mark
  const at = replace ? history.state?.at : 1;
  history[replace ? "replaceState" : "pushState"]({ ...state, at }, "", path);
  window.scrollTo(0, 0);
  rerender();
}

/** Write the current entry's address (a new query, say), keeping go()'s mark on it (the top
 * bar's Back reads it). */
export function address(path: string) {
  history.replaceState({ at: history.state?.at }, "", path);
}

/** A plain click (or tap) the app may route itself: not one meant for a new tab or window
 * (Ctrl, Cmd, Shift, Alt, a middle click) nor one a handler already took. */
export const plain = (e: MouseEvent) =>
  !e.defaultPrevented && e.button === 0 && !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey);

/** Show the current view again (main.ts renders on popstate). */
export const rerender = () => window.dispatchEvent(new PopStateEvent("popstate"));

/** Aborted when the view changes: views pass it to their event listeners. */
export const view = { signal: new AbortController().signal };

/** Mark the nav's tab for what is on screen (/search, with or without a query, is Search). */
export function markNav() {
  for (const a of document.querySelectorAll<HTMLAnchorElement>("nav a"))
    a.toggleAttribute("aria-current", a.pathname === location.pathname);
}
