// Shared by the views: the one capture queue and navigation.
import { send } from "./api";
import { idb } from "./db";
import { Queue } from "./queue";

// The stall limit can be shortened for tests (localStorage scrap.stall_ms).
const stall = () => Number(localStorage.getItem("scrap.stall_ms")) || 60_000;
export const queue = new Queue(
  idb,
  (item) => send(item, XMLHttpRequest, stall()),
  Date.now,
  () => navigator.onLine,
);

/** Navigate inside the app; main.ts renders on popstate. */
export function go(path: string, replace = false) {
  history[replace ? "replaceState" : "pushState"](null, "", path);
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** Aborted when the view changes: views pass it to their event listeners. */
export const view = { signal: new AbortController().signal };
