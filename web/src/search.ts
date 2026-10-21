// The list screen: with an empty box, every page newest first (what is still waiting to
// upload above them); with a query, full-text search as you type (snippets become text nodes
// and <mark>s, never HTML). The box's ✕ clears it. Under it, a fixed row of kinds (one tap
// sets or clears kind:; Todos alone opens the Todos screen), then refine.ts's row: Filters
// and the results' top tags, and above the list their count and the filters on. All of it is
// the query's text, kept in the address (/search?q=...), so Back, a reload and a deleted page
// come back to the same list, scrolled where it was.
import { api, type Hit } from "./api";
import { go, markNav, view } from "./app";
import { icon } from "./icons";
import { build, pageList, pageRow, pendingList } from "./lists";
import { refine } from "./refine";
import { snippetParts } from "./snippet";
import { swipeRows, trail, trailOf } from "./swipe";
import { KIND_ROW, kindsIn, listing, withKind } from "./terms";
import { empty, h } from "./ui";

const PAGE = 100; // pages a list shows, then Show more adds as many (the API's most: 500)
const MOST = 1000; // search results, fetched PAGE at a time

interface State {
  scroll?: number; // where the list was scrolled to
  limit?: number; // how long it was (Show more)
}

export async function search(): Promise<Node> {
  const q = new URLSearchParams(location.search).get("q") ?? "";
  const saved = (history.state ?? {}) as State;
  let limit = saved.limit ?? PAGE;
  let scroll = saved.scroll ?? 0; // to scroll back to, once the list is here
  const keep = (s: State) => history.replaceState({ ...history.state, ...s }, "");
  const input = h("input", {
    type: "search",
    value: q,
    placeholder: "Search",
    "aria-label": "Search",
  });
  const pending = h("div");
  const results = h("div");
  const chips = h("div");
  // The kind row: made once, so a radio keeps its focus (arrow keys) as the query changes
  const radios = [["All", ""] as const, ...KIND_ROW].map(([label, v]) => {
    const radio = h("input", {
      type: "radio",
      name: "kind",
      value: v,
      // A click, not a change: tapping the one that is on clears it. Todos alone: the Todos
      // screen (Now), not a search
      onclick: () =>
        withKind(input.value, v) === "kind:todo" ? go("/todos") : apply((now) => withKind(now, v)),
    });
    return [radio, h("label", {}, radio, label)] as const;
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
  let saving: ReturnType<typeof setTimeout>;
  let abort = new AbortController();
  // Leaving the view: no late debounce rewrites the address bar, no late results land.
  view.signal.addEventListener("abort", () => {
    clearTimeout(timer);
    clearTimeout(saving);
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

  async function run(first = false) {
    const query = input.value.trim();
    if (!first) {
      limit = PAGE; // a new query: from the top
      scroll = 0;
      history.replaceState(null, "", query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    }
    markNav();
    showKinds(query);
    abort.abort();
    abort = new AbortController();
    const { signal } = abort;
    clear.hidden = !input.value;
    // Filters even before a query, then what refines its results
    refine(query, signal, apply)
      .then((el) => {
        if (signal.aborted) return;
        // Focus on Filters (the sheet just closed) stays on it, drawn again
        const had = document.activeElement?.matches(".refine .filter");
        chips.replaceChildren(el);
        if (had) (el.querySelector(".filter") as HTMLElement).focus();
      })
      .catch(() => signal.aborted || chips.replaceChildren());
    const shown = await list(query, signal);
    if (signal.aborted) return;
    results.replaceChildren(shown);
    if (scroll) {
      const y = scroll;
      scroll = 0;
      requestAnimationFrame(() => scrollTo(0, y));
    }
  }

  /** The newest-first list (an empty box, or a kind alone), else the search's hits. */
  async function list(query: string, signal: AbortSignal): Promise<Node> {
    const filter = listing(query);
    if (filter !== null) {
      const kind = kindsIn(query)[0];
      const more = () => {
        limit = Math.min(limit + PAGE, 500);
        keep({ limit });
        void run(true);
      };
      return pageList(limit, filter, kind ? kind[0] : "Latest", limit < 500 ? more : undefined);
    }
    const ul = h("ul", { className: "list hits" });
    try {
      // limit hits (Show more adds PAGE), fetched PAGE at a time: the API's most per request
      const hits: Hit[] = [];
      for (let offset = 0; offset < limit; offset += PAGE) {
        const q = `q=${encodeURIComponent(query)}&limit=${PAGE}&offset=${offset}`;
        const got = await api<Hit[]>(`search?${q}`, { signal });
        hits.push(...got);
        if (got.length < PAGE) break;
      }
      trail(
        ul,
        "Search results",
        hits.map((hit) => hit.slug),
      );
      const rows = hits.map((hit) =>
        pageRow(
          hit,
          h(
            "small",
            { className: "snip", dir: "auto" },
            ...snippetParts(hit.snippet).map((p) => (p.mark ? h("mark", {}, p.text) : p.text)),
          ),
        ),
      );
      swipeRows(rows.map((li, i) => [li, hits[i]]));
      ul.append(...rows, ...(hits.length ? [] : [h("li", {}, empty("search", "No matches"))]));
      if (hits.length === limit && limit < MOST) {
        const more = () => {
          limit += PAGE;
          keep({ limit });
          void run(true);
        };
        return h(
          "div",
          {},
          ul,
          h("button", { type: "button", className: "more", onclick: more }, "Show more"),
        );
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        ul.append(h("li", {}, empty("offline", "Search needs the server.")));
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
    clear.hidden = !input.value;
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  };
  // A statement body: an on* handler that returns false cancels the key (Backspace too).
  input.onkeydown = (e) => {
    const first = results.querySelector("a");
    if (e.key === "Enter" && first) go(first.pathname, false, trailOf(first));
  };
  const first = run(true);
  // The list: shown once here (main.ts says Loading if it is slow), so Back lands on it as it
  // was. No keyboard until the box is tapped.
  await first;
  const root = h(
    "section",
    { className: "search" },
    h("div", { className: "field-search" }, icon("search"), input, clear),
    kinds,
    chips,
    pending,
    results,
    build(),
  );
  // Leaving by a tap or a swipe: where the list is now, not 150 ms ago
  root.addEventListener("pointerdown", () => keep({ scroll: scrollY }), { capture: true });
  return root;
}
