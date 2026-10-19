// The app shell: a tiny router, the queue badge in the header and service worker updates.
import "./style.css";
import { learnLimit } from "./api";
import { view as current, go, queue } from "./app";
import { capture } from "./capture";
import { debugPanel } from "./debug";
import { page } from "./page";
import { recent } from "./recent";
import { search } from "./search";
import { clearToasts, h, problem, toast } from "./ui";

const routes: [RegExp, (m: RegExpMatchArray) => Promise<Node> | Node][] = [
  [/^\/$/, () => capture()],
  [/^\/recent$/, () => recent()],
  [/^\/search$/, () => search()],
  [/^\/p\/([^/]+)$/, (m) => page(decodeURIComponent(m[1]))],
];

const view = document.getElementById("view") as HTMLElement;
let rendering = 0;
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
    try {
      el = await fn(m);
    } catch (e) {
      el = problem(e);
    }
    if (n === rendering) view.replaceChildren(el);
    return;
  }
  view.replaceChildren(h("p", { className: "empty" }, "Not found"));
}

document.addEventListener("click", (e) => {
  const a = (e.target as Element).closest("a");
  if (!a || a.origin !== location.origin || a.target || a.pathname.startsWith("/api/")) return;
  e.preventDefault();
  go(a.pathname + a.search);
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
  void queue.flush();
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
