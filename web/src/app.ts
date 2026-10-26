// Shared by the views: the one capture queue and navigation.
import { kept, send, stallLimit } from "./api";
import { nameAt } from "./crumbs";
import { idb } from "./db";
import { Queue } from "./queue";
import { keepScroll } from "./scroll";

const stall = () => stallLimit(kept("scrap.stall_ms"));
export const queue = new Queue(
  idb,
  (item) => send(item, XMLHttpRequest, stall()),
  Date.now,
  () => navigator.onLine,
);

/** The screens a page is opened from: the name the top bar's Back gives each. */
export const LISTS: Record<string, string> = {
  "/": "Capture",
  "/search": "Search",
  "/todos": "Todos",
  "/topics": "Topics",
};

/** Navigate inside the app; main.ts renders on popstate. The state rides in the history
 * entry (e.g. the list a page was opened from). */
export function go(path: string, replace = false, state: object | null = null) {
  // Each entry the app pushes says how deep it is (at), which list it was opened from (back:
  // that list's name and depth; a page opened from a page keeps its list) and, opened from a
  // page, that page (up: its title as shown and its depth), so the top bar's Back goes up one
  // level and the jump beside it straight to the list (main.ts); a replace keeps all three
  const now = history.state ?? {};
  const list = LISTS[location.pathname];
  const at = replace ? now.at : (now.at ?? 0) + 1;
  const back = replace
    ? now.back
    : list
      ? { name: list, at: now.at ?? 0, path: location.pathname }
      : now.back;
  const paged = (p: string) => p.startsWith("/p/");
  const up = replace
    ? now.up
    : paged(location.pathname) && paged(path)
      ? { name: nameAt(now.at ?? 0) ?? "Previous page", at: now.at ?? 0 } // as drawn: crumbs.ts
      : undefined;
  if (!replace) keepScroll(); // where this screen was, for Back (scroll.ts)
  history[replace ? "replaceState" : "pushState"]({ ...state, at, back, up }, "", path);
  window.scrollTo(0, 0);
  rerender();
}

/** Write the current entry's address (a new query, say), keeping go()'s marks on it (the top
 * bar's Back reads them). */
export function address(path: string) {
  const { at, back, up } = history.state ?? {};
  history.replaceState({ at, back, up }, "", path);
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
