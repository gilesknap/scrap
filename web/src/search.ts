// Full-text search as you type; snippets become text nodes and <mark>s, never HTML. Under
// the box, chips (a lazy chunk): browse the tags, a time range, and what refines the results.
import { api, type Hit } from "./api";
import { go, view } from "./app";
import { icon, kindIcon } from "./icons";
import { snippetParts } from "./snippet";
import { swipeRows, trail, trailOf } from "./swipe";
import { empty, h } from "./ui";

export function search(): Node {
  const q = new URLSearchParams(location.search).get("q") ?? "";
  const input = h("input", {
    type: "search",
    value: q,
    placeholder: "Search",
    autofocus: !q, // arriving with a query (a tag tapped): show the results, no keyboard
    "aria-label": "Search",
  });
  const results = h("ul", { className: "list hits" });
  const chips = h("div");
  const hint = () =>
    h(
      "li",
      {},
      empty(
        "search",
        "Search your notes, links and captions.",
        h("small", {}, 'Try -word, "a phrase", tag:name, kind:todo, is:personal or after:1w.'),
        h("a", { className: "button", href: "/tags" }, icon("tag"), "Browse tags"),
      ),
    );
  let timer: ReturnType<typeof setTimeout>;
  let abort = new AbortController();
  // Leaving the view: no late debounce rewrites the address bar, no late results land.
  view.signal.addEventListener("abort", () => {
    clearTimeout(timer);
    abort.abort();
  });

  async function run() {
    const query = input.value.trim();
    history.replaceState(null, "", query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    abort.abort();
    abort = new AbortController();
    const { signal } = abort;
    // The chips: tags and dates even before a query, then what refines its results
    import("./refine")
      .then((m) => m.refine(query, signal, apply))
      .then((el) => signal.aborted || chips.replaceChildren(el))
      .catch(() => signal.aborted || chips.replaceChildren());
    if (!query) return results.replaceChildren(hint());
    try {
      const hits = await api<Hit[]>(`search?q=${encodeURIComponent(query)}`, { signal });
      trail(
        results,
        "Search results",
        hits.map((hit) => hit.slug),
      );
      const rows = hits.map((hit) =>
        h(
          "li",
          {},
          h(
            "a",
            { href: `/p/${encodeURIComponent(hit.slug)}` },
            h("span", { className: "noimg" }, icon(kindIcon(hit.kind))),
            h(
              "span",
              {},
              h("strong", { dir: "auto" }, hit.title),
              h(
                "small",
                { dir: "auto" },
                ...snippetParts(hit.snippet).map((p) => (p.mark ? h("mark", {}, p.text) : p.text)),
              ),
            ),
          ),
        ),
      );
      swipeRows(rows.map((li, i) => [li, hits[i]]));
      results.replaceChildren(
        ...rows,
        ...(hits.length ? [] : [h("li", {}, empty("search", "No matches"))]),
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        results.replaceChildren(h("li", {}, empty("offline", "Search needs the server.")));
    }
  }
  // A chip tapped: its query now (no keyboard: the results stay in view)
  const apply = (edit: (q: string) => string) => {
    clearTimeout(timer);
    input.value = edit(input.value); // as it is now: the chips may be a keystroke behind
    void run();
  };
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  };
  // A statement body: an on* handler that returns false cancels the key (Backspace too).
  input.onkeydown = (e) => {
    const first = results.querySelector("a");
    if (e.key === "Enter" && first) go(first.pathname, false, trailOf(first));
  };
  void run();
  if (!q) setTimeout(() => input.focus());
  return h(
    "section",
    { className: "search" },
    h("label", { className: "field-search" }, icon("search"), input),
    chips,
    results,
  );
}
