// The app shell: a tiny router, the top bar (Back, the queue badge, New todo) and service
// worker updates.
import "./style.css";
import { api, kept, learnLimit } from "./api";
import { view as current, go, markNav, plain, queue } from "./app";
import { capture } from "./capture";
import { KEY } from "./debug";
import { pageRow } from "./lists";
import { page } from "./page";
import { search } from "./search";
import { whenSlow } from "./slow";
import { today } from "./status";
import { trailOf } from "./swipe";
import { KIND_ROW } from "./terms";
import { clearToasts, h, placeToasts, problem, toast } from "./ui";

const todos = () => import("./todos").then((m) => m.todos(pageRow)); // a lazy chunk
const add = document.getElementById("new") as HTMLButtonElement;
// The Todos screen's New todo: the composer (a chunk of its own) with Todo chosen; saved, it
// closes back onto the list
add.onclick = () =>
  import("./composer").then(
    (m) => m.compose([], "todo"),
    () => toast("Can't open the composer: reload scrap and try again"),
  );
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
const logo = document.querySelector(".logo") as HTMLElement;
const up = document.getElementById("back") as HTMLButtonElement;
const where = document.getElementById("where") as HTMLElement;
// An iPhone's home-screen app: no Back of its own, so the top bar gives one
const ios = (navigator as { standalone?: boolean }).standalone === true;
// Back to the app's entry before this one (go() marks the entries it pushes), else (opened
// from a link or a share) up to a parent: a todo's is Todos, Tags' is Search, any other
// page's is Capture
up.onclick = async () => {
  if (history.state?.at) return history.back();
  const from = location.pathname;
  const to = from === "/tags" ? "/search" : (await kindShown()) === "todo" ? "/todos" : "/";
  if (location.pathname === from) go(to, true); // unless gone elsewhere meanwhile
};
/** The kind of the page on screen: as drawn, else (still loading) asked for; "" unknown. */
async function kindShown() {
  const drawn = view.querySelector<HTMLElement>(".page[data-kind]")?.dataset.kind;
  if (drawn) return drawn;
  const key = decodeURIComponent(location.pathname.slice("/p/".length));
  return api<{ kind: string }>(`pages/${encodeURIComponent(key)}`).then(
    (p) => p.kind,
    () => "",
  );
}
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
  // A page and Tags are reached from elsewhere: Back in the top bar instead of the wordmark,
  // where nothing else offers one (an iPhone's home-screen app: Android and browsers have Back)
  const sub = path.startsWith("/p/") ? "" : path === "/tags" ? "Tags" : null;
  const arrow = sub !== null && ios;
  logo.hidden = arrow;
  up.hidden = !arrow;
  where.hidden = !(arrow && sub);
  where.textContent = sub;
  document.body.classList.toggle("paged", sub === ""); // its toolbar is the bottom bar: no nav
  if (path !== "/todos") add.hidden = true; // shown with the Todos list, once it is drawn
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
    add.hidden = !(el instanceof Element && el.classList.contains("todos")); // not on a problem
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
// Today as this device has it, as the Todos screen does (the server's day may differ)
const due = () =>
  encodeURIComponent(`kind:todo due:<=${today()} -is:done -is:cancelled -is:snoozed`);
let dueTimer: ReturnType<typeof setTimeout>;
function dueSoon() {
  clearTimeout(dueTimer);
  dueTimer = setTimeout(async () => {
    try {
      const { total } = await api<{ total: number }>(`search/facets?q=${due()}`);
      dueN.textContent = String(total);
      dueN.hidden = !total;
      tab.ariaLabel = total ? `Todos, ${total} due` : null;
    } catch {} // offline: as it was
  }, 300);
}
addEventListener("scrap:wrote", dueSoon);

// iPhone's text size sets the root (style.css), but never under scrap's 17 px: measured again
// when the app comes back, the setting may have changed meanwhile
const root = document.documentElement.style;
const floor = () => {
  root.fontSize = "";
  if (parseFloat(getComputedStyle(document.documentElement).fontSize) < 17) root.fontSize = "17px";
};
floor();

// No Background Sync guarantee on Android: flush on open, on reconnect and when shown.
const flush = () => {
  floor();
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

if (kept(KEY) === "1") void import("./debugpanel").then((m) => m.debugPanel());
void render();
void showQueue();
flush();
