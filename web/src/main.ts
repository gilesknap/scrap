// The app shell: a tiny router, the queue badge in the header and service worker updates.
import "./style.css";
import { api, learnLimit } from "./api";
import { view as current, go, markNav, plain, queue } from "./app";
import { capture } from "./capture";
import { debugPanel } from "./debug";
import { pageRow } from "./lists";
import { page } from "./page";
import { search } from "./search";
import { whenSlow } from "./slow";
import { trailOf } from "./swipe";
import { KIND_ROW } from "./terms";
import { clearToasts, h, placeToasts, problem, toast } from "./ui";

const todos = () => import("./todos").then((m) => m.todos(pageRow)); // a lazy chunk
const routes: [RegExp, (m: RegExpMatchArray) => Promise<Node> | Node][] = [
  [/^\/$/, () => capture()],
  [/^\/recent$/, () => recent()], // Recent is the search screen now: old links and shortcuts
  [/^\/search$/, () => search()],
  [/^\/tags$/, () => import("./tags").then((m) => m.tags())],
  [/^\/todos$/, () => todos()],
  [/^\/p\/([^/]+)$/, (m) => page(decodeURIComponent(m[1]))],
];

/** /recent (?kind=consume) as the search screen's address, ?kind=todo as the Todos screen's;
 * another kind= is ignored. */
function recent() {
  const kind = new URLSearchParams(location.search).get("kind");
  const name = KIND_ROW.find(([, , , api]) => api === kind)?.[1];
  history.replaceState(
    null,
    "",
    name === "todo"
      ? "/todos"
      : name
        ? `/search?q=${encodeURIComponent(`kind:${name}`)}`
        : "/search",
  );
  return name === "todo" ? todos() : search();
}

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
  markNav();
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

// Every page, tag and list is a real link (long-press or Ctrl-click opens it in a new tab):
// a plain tap on one routes here instead of loading the app again.
document.addEventListener("click", (e) => {
  const a = (e.target as Element).closest("a");
  if (!a || !plain(e) || a.origin !== location.origin || a.target || a.hasAttribute("download"))
    return;
  if (a.pathname.startsWith("/api/") || a.pathname === "/share") return;
  e.preventDefault();
  if (a.hash && a.pathname === location.pathname && a.search === location.search) {
    // A heading or footnote of this page: scrolled to, not routed
    let id = a.hash.slice(1);
    try {
      id = decodeURIComponent(id);
    } catch {} // a malformed % stays as typed
    document.getElementById(id)?.scrollIntoView();
    return;
  }
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
queue.onchange = () => {
  void showQueue();
  dueSoon(); // a capture uploaded may be a todo due today
};

// The Todos tab's badge: how many open todos are due today or overdue (one count from the
// server), refreshed when the app opens or comes back, and after a change (a tick, an edit).
const tab = document.querySelector('nav a[href="/todos"]') as HTMLAnchorElement;
const dueN = tab.querySelector("b") as HTMLElement;
const DUE = encodeURIComponent("kind:todo due:<=today -is:done -is:cancelled");
let dueTimer: ReturnType<typeof setTimeout>;
function dueSoon() {
  clearTimeout(dueTimer);
  dueTimer = setTimeout(async () => {
    try {
      const { total } = await api<{ total: number }>(`search/facets?q=${DUE}`);
      dueN.textContent = String(total);
      dueN.hidden = !total;
      tab.ariaLabel = total ? `Todos, ${total} due` : null;
    } catch {} // offline: as it was
  }, 300);
}
addEventListener("scrap:wrote", dueSoon);

// No Background Sync guarantee on Android: flush on open, on reconnect and when shown.
const flush = () => {
  void queue.nudge(); // now, not when its backoff says: the user is here
  dueSoon();
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
