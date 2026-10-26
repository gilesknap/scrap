// The app shell: a tiny router, the top bar (Back and the jump to the list, the queue badge,
// New todo, Settings) and service worker updates.
import "./style.css";
import { api, kept, learnLimit } from "./api";
import { address, view as current, go, LISTS, markNav, plain, queue } from "./app";
import { capture } from "./capture";
import { named, remember } from "./crumbs";
import { KEY } from "./debug";
import { pageRow } from "./lists";
import { holdScroll, restoreScroll, watchScroll } from "./scroll";
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
document.getElementById("settings")?.addEventListener("click", () =>
  import("./settings").then(
    (m) => m.settings(),
    () => toast("Can't open Settings: reload scrap and try again"),
  ),
);
const routes: [RegExp, (m: RegExpMatchArray) => Promise<Node> | Node][] = [
  [/^\/$/, () => capture()],
  [/^\/recent$/, () => recent()], // Recent is the search screen now: old links and shortcuts
  [/^\/search$/, () => search()],
  // The Tags screen is retired (the Filters panel's Tags row offers and matches tags): its old
  // links and bookmarks are the search screen's, keeping Back's mark on the entry
  [
    /^\/tags$/,
    () => {
      address("/search");
      return search();
    },
  ],
  [/^\/todos$/, () => todos()],
  [/^\/topics$/, () => import("./topics").then((m) => m.topics())], // a lazy chunk
  // Store health (Settings): each check's count, a tap its search. A chunk of its own
  [/^\/health$/, () => import("./health").then((m) => m.health(current.signal))],
  [
    /^\/p\/([^/]+)$/,
    (m) => {
      const signal = current.signal; // this view's, taken before the chunk loads
      return import("./page").then((p) => p.page(decodeURIComponent(m[1]), signal));
    },
  ],
];

/** /recent (?kind=consume) as the search screen's address, ?kind=todo as the Todos screen's;
 * another kind= is ignored. */
function recent() {
  const kind = new URLSearchParams(location.search).get("kind");
  const name = KIND_ROW.find(([, , , api]) => api === kind)?.[1];
  address(
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
const backTo = document.getElementById("backto") as HTMLElement;
const header = document.querySelector("header") as HTMLElement;
const jump = document.getElementById("jump") as HTMLElement; // · Search, beside Back
const toList = document.getElementById("tolist") as HTMLButtonElement;
const pos = document.getElementById("pos") as HTMLElement; // a page's place in its list
/** go()'s marks on this entry, where they are behind it: the page a link was followed from
 * (prev) and the list the page was opened from. */
const marks = () => {
  const s = history.state;
  const at: number = s?.at ?? 0;
  const behind = (m?: { name: string; at: number }) => (m && at > m.at ? m : undefined);
  return { at, prev: behind(s?.up), list: behind(s?.back) };
};
// Back, named for where it goes, goes up one level: to the page a link was followed from,
// else to the list the page was opened from (past the pages stepped through by the pager),
// else up to a parent (back.ts, a chunk of its own), as its label says: a todo's is Todos, a
// topic's Topics, any other page's Capture, and Capture while the page is still loading. When
// it doesn't go to the list, the jump beside it does (· Search).
up.onclick = () => {
  const { at, prev, list } = marks();
  const to = prev ?? list;
  if (to) return history.go(to.at - at);
  const from = location.pathname;
  void import("./back").then(
    (m) => m.up(go, from), // unless gone elsewhere while it loaded
    () => go("/", true), // the chunk is not here (offline): Capture
  );
};
toList.onclick = () => {
  const { at, list } = marks();
  if (list) history.go(list.at - at);
};
/** The top bar's Back says where it goes: the linking page, the list, else the parent (for a
 * page, once its kind is known); the jump to the list shows when Back goes elsewhere. */
const nameBack = () => {
  const kind = document.querySelector<HTMLElement>("#view .page[data-kind]")?.dataset.kind;
  const { prev, list } = marks();
  const to =
    (prev && named(prev)) ??
    (list && named(list)) ??
    (kind === "todo" ? "Todos" : kind === "topic" ? "Topics" : "Capture");
  backTo.textContent = to;
  up.ariaLabel = `Back to ${to}`;
  crumb(!!(prev && list));
  if (prev && list) {
    toList.textContent = named(list);
    toList.ariaLabel = `Back to ${toList.textContent}`;
  }
};
/** The jump to the list shown (the header lays Back out beside it) or not. */
const crumb = (on: boolean) => {
  jump.hidden = !on;
  header.classList.toggle("crumb", on);
};
const VIEW_MS = 30_000; // a view that has not answered by then has failed
let rendering = 0;
let shown = ""; // the path on screen
let controller = new AbortController();

async function render() {
  const n = ++rendering;
  controller.abort();
  controller = new AbortController();
  current.signal = controller.signal;
  clearToasts();
  holdScroll(); // until it is drawn and put back where it was
  const path = location.pathname;
  markNav();
  // A page is reached from elsewhere: Back in the top bar instead of the wordmark, on every
  // phone and browser (named for where it goes: nameBack)
  const arrow = path.startsWith("/p/");
  pos.replaceChildren(); // a page puts its pager here
  if (arrow) nameBack();
  else crumb(false);
  if (LISTS[path]) remember(LISTS[path]); // a list's name: at once, even if left before drawn
  logo.hidden = arrow;
  up.hidden = !arrow;
  document.body.classList.toggle("paged", arrow); // its toolbar is the bottom bar: no nav
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
    // A view the server never answers ends in the problem state, with Retry (and its requests
    // and listeners end: aborted)
    const c = controller;
    let giveUp = 0;
    try {
      el = await whenSlow(
        Promise.race([
          Promise.resolve().then(() => fn(m)),
          new Promise<never>((_, no) => {
            giveUp = window.setTimeout(() => {
              no(new TypeError("timed out"));
              c.abort();
            }, VIEW_MS);
          }),
        ]),
        150,
        loading,
      );
    } catch (e) {
      el = problem(e);
    }
    clearTimeout(giveUp);
    if (n !== rendering) return;
    // The same page again (back from the editor, a retry): no fade-in, it is already here.
    if (path === shown && el instanceof Element) el.classList.add("still");
    shown = path;
    view.replaceChildren(el);
    // A list's name, for Back on the pages opened from it (crumbs.ts), at its own address
    // now (/recent is the search screen's); a page records its own as it shows it (page.ts)
    if (!arrow && LISTS[location.pathname]) remember(LISTS[location.pathname]);
    if (arrow) nameBack(); // a page opened cold: its kind is known now
    restoreScroll(c.signal); // Back or Forward: where it was left (scroll.ts)
    add.hidden = !(el instanceof Element && el.classList.contains("todos")); // not on a problem
    placeToasts(); // e.g. one placed for the view before
    return;
  }
  shown = "";
  view.replaceChildren(h("p", { className: "empty" }, "Not found"));
  restoreScroll(controller.signal);
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
  // The count first, as the compact badge shows it, then the words: "2 queued: 1 waiting · …"
  badge.ariaLabel = `${items.length} queued: ${badge.textContent}`;
  badge.dataset.n = String(items.length); // on a narrow page, the count alone (topbar.css)
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

// iPhone's text size sets the root (css/base.css), but never under scrap's 17 px: measured again
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

watchScroll();
if (kept(KEY) === "1") void import("./debugpanel").then((m) => m.debugPanel());
void render();
void showQueue();
flush();
