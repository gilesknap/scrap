// Browse by tag (#84): every tag with how many pages have it, as a tree (tech, then
// tech/epics under it), A to Z or most used first; a filter box narrows it. Tapping a tag
// searches for it (tag:tech finds tech/epics too). A chunk of its own (needs the server).
import { api } from "./api";
import { view } from "./app";
import { icon } from "./icons";
import { type TagNode, token, tree } from "./terms";
import { empty, h, problem } from "./ui";

const SORTS = [
  ["A–Z", ""],
  ["Most used", "n"],
] as const;

export async function tags(): Promise<HTMLElement> {
  let list: [string, number][];
  try {
    list = await api<[string, number][]>("tags", { signal: view.signal });
  } catch (e) {
    return h("section", {}, problem(e));
  }
  const roots = tree(list);
  const open = new Set<string>(); // the parents shown opened
  let by = new URLSearchParams(location.search).get("sort") === "n" ? "n" : "";
  const filter = h("input", {
    type: "search",
    placeholder: "Filter tags",
    "aria-label": "Filter tags",
  });
  const ul = h("ul", { className: "list tagtree" });

  const order = (ns: TagNode[]) =>
    by ? [...ns].sort((a, b) => b.n - a.n || a.path.localeCompare(b.path)) : ns;
  // A node is shown if it or one under it matches the filter; matches open their parents
  const matches = (node: TagNode, f: string): boolean =>
    !f || node.path.includes(f) || node.kids.some((k) => matches(k, f));

  function rows(nodes: TagNode[], depth: number, f: string): HTMLLIElement[] {
    return order(nodes)
      .filter((node) => matches(node, f))
      .flatMap((node) => {
        const opened = open.has(node.path) || (!!f && node.kids.some((k) => matches(k, f)));
        const li = h(
          "li",
          {},
          h(
            "a",
            { href: `/search?q=${encodeURIComponent(token("tag", node.path))}` },
            h("span", { dir: "auto" }, `#${depth ? node.name : node.path}`),
            h("small", {}, String(node.n)),
          ),
          node.kids.length > 0 &&
            h(
              "button",
              {
                type: "button",
                className: "ghost",
                "aria-expanded": String(opened),
                "aria-label": `${opened ? "Hide" : "Show"} tags under ${node.path}`,
                onclick: () => {
                  if (opened) open.delete(node.path);
                  else open.add(node.path);
                  draw();
                },
              },
              icon("next"),
            ),
        );
        li.style.setProperty("--depth", String(depth));
        return [li, ...(opened ? rows(node.kids, depth + 1, f) : [])];
      });
  }

  function draw() {
    const f = filter.value.trim().toLowerCase();
    const shown = rows(roots, 0, f);
    ul.replaceChildren(...shown);
    if (!shown.length)
      ul.replaceChildren(h("li", {}, empty("tag", list.length ? "No such tag" : "No tags yet")));
  }
  filter.oninput = draw;

  const sorts = h(
    "div",
    { className: "chips filters", role: "radiogroup", "aria-label": "Order" },
    ...SORTS.map(([label, key]) =>
      h(
        "label",
        {},
        h("input", {
          type: "radio",
          name: "sort",
          checked: key === by,
          onchange: () => {
            by = key;
            history.replaceState(null, "", key ? "/tags?sort=n" : "/tags");
            draw();
          },
        }),
        label,
      ),
    ),
  );
  draw();
  return h(
    "section",
    { className: "tags-view" },
    h("label", { className: "field-search" }, icon("tag"), filter),
    sorts,
    ul,
  );
}
