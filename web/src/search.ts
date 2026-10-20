// Full-text search as you type; snippets become text nodes and <mark>s, never HTML. Under
// the box, chips to refine the results (a lazy chunk), and a way to browse the tags.
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
        h("small", {}, 'Try -word, "a phrase", tag:name, kind:todo or is:personal.'),
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
    if (!query) {
      chips.replaceChildren();
      return results.replaceChildren(hint());
    }
    const { signal } = abort;
    import("./refine")
      .then((m) => m.refine(query, signal, apply))
      .then((el) => signal.aborted || chips.replaceChildren(el ?? ""))
      .catch(() => signal.aborted || chips.replaceChildren());
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
  const apply = (next: string) => {
    clearTimeout(timer);
    input.value = next;
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
  if (q) void run();
  else {
    results.replaceChildren(hint());
    setTimeout(() => input.focus());
  }
  return h(
    "section",
    { className: "search" },
    h(
      "div",
      { className: "searchbar" },
      h("label", { className: "field-search" }, icon("search"), input),
      h("a", { className: "button", href: "/tags", "aria-label": "Browse tags" }, icon("tag")),
    ),
    chips,
    results,
  );
}
