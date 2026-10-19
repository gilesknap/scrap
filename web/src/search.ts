// Full-text search as you type; snippets become text nodes and <mark>s, never HTML.
import { api, type Hit } from "./api";
import { go, view } from "./app";
import { icon, kindIcon } from "./icons";
import { snippetParts } from "./snippet";
import { empty, h } from "./ui";

export function search(): Node {
  const q = new URLSearchParams(location.search).get("q") ?? "";
  const input = h("input", {
    type: "search",
    value: q,
    placeholder: "Search",
    autofocus: true,
    "aria-label": "Search",
  });
  const results = h("ul", { className: "list hits" });
  const hint = () => h("li", {}, empty("search", "Search your notes, links and captions."));
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
    if (!query) return results.replaceChildren(hint());
    try {
      const hits = await api<Hit[]>(`search?q=${encodeURIComponent(query)}`, {
        signal: abort.signal,
      });
      results.replaceChildren(
        ...hits.map((hit) =>
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
                h("strong", {}, hit.title),
                h(
                  "small",
                  {},
                  ...snippetParts(hit.snippet).map((p) =>
                    p.mark ? h("mark", {}, p.text) : p.text,
                  ),
                ),
              ),
            ),
          ),
        ),
        ...(hits.length ? [] : [h("li", {}, empty("search", "No matches"))]),
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        results.replaceChildren(h("li", {}, empty("offline", "Search needs the server.")));
    }
  }
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  };
  // A statement body: an on* handler that returns false cancels the key (Backspace too).
  input.onkeydown = (e) => {
    const first = results.querySelector("a");
    if (e.key === "Enter" && first) go(first.pathname);
  };
  if (q) void run();
  else results.replaceChildren(hint());
  setTimeout(() => input.focus());
  return h(
    "section",
    { className: "search" },
    h("label", { className: "field-search" }, icon("search"), input),
    results,
  );
}
