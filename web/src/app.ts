// Shared by the views: the one capture queue and navigation.
import { send, stallLimit } from "./api";
import { idb } from "./db";
import { Queue } from "./queue";

const stall = () => stallLimit(localStorage.getItem("scrap.stall_ms"));
export const queue = new Queue(
  idb,
  (item) => send(item, XMLHttpRequest, stall()),
  Date.now,
  () => navigator.onLine,
);

/** Navigate inside the app; main.ts renders on popstate. The state rides in the history
 * entry (e.g. the list a page was opened from). */
export function go(path: string, replace = false, state: object | null = null) {
  history[replace ? "replaceState" : "pushState"](state, "", path);
  window.scrollTo(0, 0);
  rerender();
}

/** Show the current view again (main.ts renders on popstate). */
export const rerender = () => window.dispatchEvent(new PopStateEvent("popstate"));

/** Aborted when the view changes: views pass it to their event listeners. */
export const view = { signal: new AbortController().signal };

/** Mark the nav's tab for what is on screen (/search, with or without a query, is Search). */
export function markNav() {
  for (const a of document.querySelectorAll<HTMLAnchorElement>("nav a"))
    a.toggleAttribute("aria-current", a.pathname === location.pathname);
}
