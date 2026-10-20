// The app shell: a tiny router, the queue badge in the header and service worker updates.
import "./style.css";
import { learnLimit } from "./api";
import { view as current, go, queue } from "./app";
import { capture } from "./capture";
import { debugPanel } from "./debug";
import { page } from "./page";
import { recent } from "./recent";
import { search } from "./search";
import { whenSlow } from "./slow";
import { trailOf } from "./swipe";
import { clearToasts, h, placeToasts, problem, toast } from "./ui";

const routes: [RegExp, (m: RegExpMatchArray) => Promise<Node> | Node][] = [
  [/^\/$/, () => capture()],
  [/^\/recent$/, () => recent()],
  [/^\/search$/, () => search()],
  [/^\/tags$/, () => import("./tags").then((m) => m.tags())],
  [/^\/p\/([^/]+)$/, (m) => page(decodeURIComponent(m[1]))],
];

const view = document.getElementById("view") as HTMLElement;
let rendering = 0;
let shown = ""; // the path on screen
let controller = new AbortController();

async function render() {
  const n = ++rendering;
  controller.abort();
  controller = new AbortController();
  current.signal = controller.signal;
  clearToasts();
  const path = location.pathname;
  for (const a of document.querySelectorAll("nav a")) {
    a.toggleAttribute("aria-current", (a as HTMLAnchorElement).pathname === path);
  }
  for (const [re, fn] of routes) {
    const m = path.match(re);
    if (!m) continue;
    let el: Node;
    // A view waiting for the server (behind an upload on a slow link, say) says so at once,
    // rather than leaving the last one up as if the tap did nothing. Not for the same page
    // again, and not for quick answers: no flash.
    const loading = () => {
      if (n !== rendering || path === shown) return;
      shown = ""; // no page on screen now
      view.replaceChildren(h("p", { className: "empty", role: "status" }, "Loading…"));
    };
    try {
      el = await whenSlow(
        Promise.resolve().then(() => fn(m)),
        150,
        loading,
      );
    } catch (e) {
      el = problem(e);
    }
    if (n !== rendering) return;
    // The same page again (back from the editor, a retry): no fade-in, it is already here.
    if (path === shown && el instanceof Element) el.classList.add("still");
    shown = path;
    view.replaceChildren(el);
    placeToasts(); // e.g. one placed for the view before
    return;
  }
  view.replaceChildren(h("p", { className: "empty" }, "Not found"));
}

document.addEventListener("click", (e) => {
  const a = (e.target as Element).closest("a");
  if (!a || a.origin !== location.origin || a.target || a.pathname.startsWith("/api/")) return;
  e.preventDefault();
  go(a.pathname + a.search, false, trailOf(a)); // from a list: swipe on through it
});
window.addEventListener("popstate", () => void render());

// Header badge: what is waiting to upload; tap to retry now.
const badge = document.getElementById("queue") as HTMLButtonElement;
async function showQueue() {
  const items = await queue.items();
  const failed = items.filter((i) => i.failed).length;
  const waiting = items.length - failed;
  badge.hidden = !items.length;
  badge.className = failed ? "badge failed" : "badge";
  badge.textContent = [waiting && `${waiting} waiting`, failed && `${failed} failed`]
    .filter(Boolean)
    .join(" · ");
  document.dispatchEvent(new Event("queuechange"));
}
badge.onclick = () => void queue.retry();
queue.onchange = () => void showQueue();

// No Background Sync guarantee on Android: flush on open, on reconnect and when shown.
const flush = () => {
  void queue.nudge(); // now, not when its backoff says: the user is here
  void learnLimit(); // the server's upload limit, kept for offline checks
};
window.addEventListener("online", flush);
document.addEventListener(
  "visibilitychange",
  () => document.visibilityState === "visible" && flush(),
);

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  const sw = navigator.serviceWorker;
  const controlled = !!sw.controller;
  const offer = (w: ServiceWorker) =>
    toast("Update available", "Reload", () => w.postMessage("skipWaiting"), 0);
  sw.addEventListener("controllerchange", () => controlled && location.reload());
  sw.register("/sw.js", { type: "module" }).then((reg) => {
    if (reg.waiting && controlled) offer(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const w = reg.installing;
      w?.addEventListener("statechange", () => w.state === "installed" && controlled && offer(w));
    });
    document.addEventListener(
      "visibilitychange",
      () => document.visibilityState === "visible" && reg.update(),
    );
  });
}

debugPanel();
void render();
void showQueue();
flush();
