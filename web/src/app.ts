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

/** Navigate inside the app; main.ts renders on popstate. */
export function go(path: string, replace = false) {
  history[replace ? "replaceState" : "pushState"](null, "", path);
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** Aborted when the view changes: views pass it to their event listeners. */
export const view = { signal: new AbortController().signal };
