// Full-text search as you type; snippets become text nodes and <mark>s, never HTML.
import { api, type Hit } from "./api";
import { go } from "./app";
import { snippetParts } from "./snippet";
import { h } from "./ui";

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
  let timer: ReturnType<typeof setTimeout>;
  let abort = new AbortController();

  async function run() {
    const query = input.value.trim();
    history.replaceState(null, "", query ? `/search?q=${encodeURIComponent(query)}` : "/search");
    abort.abort();
    abort = new AbortController();
    if (!query) return results.replaceChildren();
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
        ...(hits.length ? [] : [h("li", { className: "empty" }, "No matches")]),
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError")
        results.replaceChildren(h("li", { className: "empty" }, "Search needs the server."));
    }
  }
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  };
  input.onkeydown = (e) =>
    e.key === "Enter" &&
    results.querySelector("a") &&
    go((results.querySelector("a") as HTMLAnchorElement).pathname);
  if (q) void run();
  setTimeout(() => input.focus());
  return h("section", { className: "search" }, input, results);
}
