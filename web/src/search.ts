// The list screen: with an empty box, every page newest first (what is still waiting to
// upload above them); with a query, full-text search as you type (snippets become text nodes
// and <mark>s, never HTML). The box's ✕ clears it. Under it the Filters panel (refine.ts),
// opened by the slider at the box's end; then a fixed row of kinds (one tap sets or clears
// kind:, Todos too), the filters on as a row of chips, and the results header: the count, with
// Pin and Copy link at its end. All of it is the query's text, kept in the address (/search?q=...), so Back, a reload and a deleted page
// come back to the same list, scrolled where it was.
import { api, type Hit, writeClock } from "./api";
import { address, go, markNav, view } from "./app";
import { icon, kindIcon } from "./icons";
import { build, pageList, pageRow, pendingList } from "./lists";
import { snippetParts } from "./snippet";
import { swipeRows, trail, trailOf } from "./swipe";
import { groupBy, KIND_ROW, kindsIn, listing, served, withKind } from "./terms";
import { empty, h, problem } from "./ui";

const PAGE = 100; // pages a list shows, then Show more adds as many (the API's most: 500)
const MOST = 1000; // search results, fetched PAGE at a time

interface State {
  scroll?: number; // where the list was scrolled to
  limit?: number; // how long it was (Show more)
}

export async function search(): Promise<Node> {
  const q = new URLSearchParams(location.search).get("q") ?? "";
  const saved = (history.state ?? {}) as State;
  // (a stale or hand-edited entry: -5 or "abc" is the first page)
  let limit = saved.limit && saved.limit > 0 ? Math.min(Math.ceil(saved.limit), MOST) : PAGE;
  let scroll = saved.scroll ?? 0; // to scroll back to, once the list is here
  const keep = (s: State) => history.replaceState({ ...history.state, ...s }, "");
  const input = h("input", {
    type: "search",
    value: q,
    placeholder: "Search",
    "aria-label": "Search",
  });
  const pending = h("div");
  // Recent searches under the empty box (searches.ts, a chunk of its own); a search is kept
  // when it is run: Enter, opening a result, or the same query left 3 s with a result
  const recents = h("div");
  const later = import("./searches").then(
    (m) => m.attach(input, recents, (q) => apply(() => q), view.signal),
    () => null, // offline before it was kept: no recents, search as before
  );
  const remember = (query = input.value.trim()) => {
    if (query) void later.then((r) => r?.remember(query));
  };
  let settle: ReturnType<typeof setTimeout>;
  const results = h("div");
  // In order down the screen: the box, the Filters panel (opened by the box's slider), the
  // kinds, the filters on as chips, then the results header (the count, Pin and Copy link)
  const panel = h("div");
  const chips = h("div");
  const found = h("div");
  // Filters: a slider at the box's end (how many are on, in a dot); refine.ts, a chunk of its
  // own, fills it and opens its panel under the kinds
  const filters = h(
    "button",
    { type: "button", className: "ffield", "aria-label": "Filters" },
    icon("filter"),
  );
  const refining = import("./refine");
  // The kind row: made once, so a radio keeps its focus (arrow keys) as the query changes
  const radios = [["All", "", [], ""] as const, ...KIND_ROW].map(([label, v, , apiKind]) => {
    const radio = h("input", {
      type: "radio",
      name: "kind",
      value: v,
      // A click, not a change: tapping the one that is on clears it. Todos filter as the
      // others do (the Todos screen is the nav bar's)
      onclick: () => apply((now) => withKind(now, v)),
    });
    // Each kind with its icon, as the editor's kinds have them (All: every kind's tiles)
    return [radio, h("label", {}, radio, icon(v ? kindIcon(apiKind) : "all"), label)] as const;
  });
  const kinds = h(
    "div",
    { className: "chips kindrow", role: "radiogroup", "aria-label": "Kind" },
    ...radios.map(([, label]) => label),
  );
  const showKinds = (query: string) => {
    const on = kindsIn(query);
    const value = on.length === 1 ? on[0][1] : on.length ? null : "";
    for (const [radio] of radios) radio.checked = radio.value === value;
  };
  let timer: ReturnType<typeof setTimeout>;
  let typed = false; // typed, and its run not yet started
  let busy: Promise<void> | undefined; // the run for what was typed, until it ends
  let saving: ReturnType<typeof setTimeout>;
  let abort = new AbortController();
  // Leaving the view: no late debounce rewrites the address bar, no late results land.
  view.signal.addEventListener("abort", () => {
    clearTimeout(timer);
    clearTimeout(saving);
    clearTimeout(settle);
    abort.abort();
  });
  // Where the list is scrolled to rides in its history entry, for Back
  addEventListener(
    "scroll",
    () => {
      clearTimeout(saving);
      saving = setTimeout(() => keep({ scroll: scrollY }), 150);
    },
    { passive: true, signal: view.signal },
  );
  const pend = async () => pending.replaceChildren(await pendingList());
  document.addEventListener("queuechange", pend, { signal: view.signal });
  void pend();
  // A capture that uploads (or is queued) may belong in the results: run the same query again.
  // Debounced (a queue drains in a burst); not while the box holds something other than what
  // ran (typing: its own run is coming), nor while a finger is down, the page is scrolling or
  // a scroll is being restored, nor with focus or a selection inside the results: it waits and
  // tries again, so a swipe, tap or selection is never replaced under the user.
  let keeps: typeof import("./refresh").keeps = () => true; // whether a refresh leaves the rows be
  let calm = () => true; // whether the user has the rows to themselves again
  let kick = () => {}; // asks for a refresh (it waits until it is safe)
  const watching = import("./refresh").then((m) => {
    keeps = m.keeps;
    const refresh = m.watch(
      view.signal,
      input,
      () => scroll !== 0,
      () => {
        scroll = scrollY;
        void run(true, true);
      },
    );
    calm = refresh.calm;
    kick = refresh;
    return refresh;
  });
  // (a change before the chunk is here waits for it; offline before it was kept: no refresh)
  document.addEventListener(
    "queuechange",
    () =>
      watching.then(
        (kick) => kick(),
        () => {},
      ),
    {
      signal: view.signal,
    },
  );

  async function run(first = false, quiet = false) {
    const query = input.value.trim();
    pending.hidden = query !== ""; // waiting uploads pin on the empty box only
    if (!first) {
      limit = PAGE; // a new query: from the top
      scroll = 0;
      address(query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    }
    // A refresh shares the signal of the run before it: it never cancels that run's refine
    if (!quiet) {
      abort.abort();
      abort = new AbortController();
    }
    const { signal } = abort;
    // A refresh (quiet) redraws the rows only: never the kinds, filters, chips or the timer
    if (!quiet) {
      markNav();
      showKinds(query);
      clear.hidden = !input.value;
      // Filters even before a query, then what refines its results
      refining
        .then((m) => m.refine(query, signal, apply, filters))
        .then((els) => {
          if (signal.aborted) return;
          // (refine puts focus back on the control it was on)
          for (const [i, d] of [panel, chips, found].entries()) d.replaceChildren(els[i] || "");
        })
        .catch(() => signal.aborted || chips.replaceChildren());
      clearTimeout(settle);
    }
    const clock = writeClock();
    const shown = await list(query, signal);
    if (signal.aborted) return;
    // A change (a tick) began or ended while it was read: it may predate it. Read again
    if (quiet && clock !== writeClock()) return run(first, quiet);
    // A finger, scroll or selection came while it was read: not under them. Later
    if (quiet && !calm()) return kick();
    // A refresh that found nothing new leaves the rows (and any gesture or lookup on them) be
    if (quiet && keeps(shown, results)) {
      scroll = 0;
      return;
    }
    results.replaceChildren(shown);
    // Not when the screen opens on a query (Back, a reload): only one typed or tapped here
    if (!first && query && results.querySelector(".hits a, .groups a"))
      settle = setTimeout(() => remember(query), 3000); // the query that ran, not what is typed since
    if (scroll) {
      const y = scroll;
      scroll = 0;
      requestAnimationFrame(() => scrollTo(0, y));
    }
  }

  /** The newest-first list (an empty box, or a kind alone), else the search's hits, in
   * sections when grouped (group: in the query, or Later's and Todos' own: grouped.ts). */
  async function list(query: string, signal: AbortSignal): Promise<Node> {
    const filter = listing(query);
    const how = groupBy(query);
    const one = kindsIn(query);
    if (filter !== null && !how) {
      const kind = one[0];
      const more = () => {
        limit = Math.min(limit + PAGE, 500);
        keep({ limit });
        void run(true);
      };
      const shown = pageList(
        Math.min(limit, 500),
        filter,
        kind ? kind[0] : "Latest",
        limit < 500 ? more : undefined,
      );
      // An empty box: the newest pages, under a heading as on Capture (a kind alone: its row says)
      return kind ? shown : h("div", {}, h("h2", { className: "label" }, "Latest"), await shown);
    }
    const ul = h("ul", { className: "list hits" });
    try {
      // limit hits (Show more adds PAGE), fetched PAGE at a time: the API's most per request.
      // The server gets the group in force (terms.ts served)
      const hits: Hit[] = [];
      for (let offset = 0; offset < limit; offset += PAGE) {
        const q = `q=${encodeURIComponent(served(query))}&limit=${PAGE}&offset=${offset}`;
        const got = await api<Hit[]>(`search?${q}`, { signal });
        hits.push(...got);
        if (got.length < PAGE) break;
      }
      const rowOf = (hit: Hit) => {
        const li = pageRow(
          hit,
          h(
            "small",
            { className: "snip", dir: "auto" },
            ...snippetParts(hit.snippet).map((p) => (p.mark ? h("mark", {}, p.text) : p.text)),
          ),
        );
        // A topic page (#261), Claude's: its icon, and "· Topic" after its date
        if (hit.topic) {
          li.querySelector(".noimg")?.replaceChildren(icon("topic"));
          li.querySelector(".sub > small")?.after(h("span", { className: "topic" }, "Topic"));
        }
        return li;
      };
      let shown: Node = ul;
      if (how && hits.length) {
        // In sections (a chunk of its own, with the Todos screen's): one pager trail through
        // them all, in the order shown
        const label = one.length === 1 ? one[0][0] : "Search results";
        const m = await import("./grouped");
        shown = m.grouped(hits, how, query, rowOf, label);
      } else {
        trail(
          ul,
          "Search results",
          hits.map((hit) => hit.slug),
        );
        const rows = hits.map(rowOf);
        swipeRows(rows.map((li, i) => [li, hits[i]]));
        ul.append(...rows, ...(hits.length ? [] : [h("li", {}, empty("search", "No matches"))]));
      }
      if (hits.length === limit && limit < MOST) {
        const more = () => {
          limit += PAGE;
          keep({ limit });
          void run(true);
        };
        return h(
          "div",
          {},
          shown,
          h("button", { type: "button", className: "more", onclick: more }, "Show more"),
        );
      }
      return shown;
    } catch (e) {
      if ((e as Error).name !== "AbortError") ul.append(h("li", {}, problem(e))); // as every screen says it: why, and Retry
    }
    return ul;
  }

  // A chip tapped: its query now (no keyboard: the results stay in view)
  const apply = (edit: (q: string) => string) => {
    clearTimeout(timer);
    input.value = edit(input.value); // as it is now: the chips may be a keystroke behind
    void run();
  };
  // The box's ✕: one tap back to every page, newest first (no keyboard, unless by key)
  const clear = h(
    "button",
    {
      type: "button",
      className: "clear",
      "aria-label": "Clear search",
      onclick: (e: MouseEvent) => {
        apply(() => "");
        if (!e.detail) input.focus();
      },
    },
    icon("close"),
  );
  input.oninput = () => {
    clearTimeout(settle); // typed on: not settled
    clear.hidden = !input.value;
    clearTimeout(timer);
    typed = true;
    timer = setTimeout(() => {
      typed = false;
      busy = run();
    }, 250);
  };
  // A statement body: an on* handler that returns false cancels the key (Backspace too).
  input.onkeydown = (e) => {
    if (e.key !== "Enter") return;
    remember();
    const open = () => {
      const first = results.querySelector("a");
      if (first) go(first.pathname, false, trailOf(first));
    };
    // Typed within the debounce, or its run still going: open the typed query's first hit
    if (typed) {
      clearTimeout(timer);
      typed = false;
      busy = run();
    }
    if (busy) void busy.then(open);
    else open();
  };
  results.addEventListener("click", (e) => (e.target as Element).closest("a") && remember());
  const first = run(true);
  // The list: shown once here (main.ts says Loading if it is slow), so Back lands on it as it
  // was. No keyboard until the box is tapped.
  await first;
  const root = h(
    "section",
    { className: "search" },
    h("div", { className: "field-search" }, icon("search"), input, clear, filters),
    recents,
    panel, // under the box whose slider opens it
    kinds, // always here
    chips, // the filters on, when any are
    found, // the results header
    pending,
    results,
    build(),
  );
  // Leaving by a tap or a swipe: where the list is now, not 150 ms ago
  root.addEventListener("pointerdown", () => keep({ scroll: scrollY }), { capture: true });
  return root;
}
