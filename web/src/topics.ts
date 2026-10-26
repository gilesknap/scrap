// The Topics screen (/topics, #261): the topic pages Claude keeps, from the index the server
// makes from data (GET /api/topics, no model call), grouped by area (the top-level tag most
// common among a topic's sources), the biggest group first. Each row: its title, its
// synthesis's lead, how many sources and when it last changed; a dot on one new or changed
// since this device last looked (kept on the device, as recent searches are). A filter box
// narrows the list as typed. A lazy chunk.
import { api, type TopicRow } from "./api";
import { view } from "./app";
import { icon } from "./icons";
import { trail } from "./swipe";
import { changed, dots, look, seen } from "./topicseen";
import { empty, h, problem, whenShort } from "./ui";
import "./topics.css";

const OTHER = "Other"; // the group of topics whose sources have no tags

/** Whether a topic matches what is typed in the filter: every word, in its title, summary or
 * area, case aside. */
export function matches(r: TopicRow, typed: string): boolean {
  const text = `${r.title} ${r.summary} ${r.area ?? ""}`.toLocaleLowerCase();
  return typed
    .toLocaleLowerCase()
    .split(/\s+/)
    .every((w) => text.includes(w));
}

/** The rows by area, in the server's order (the biggest area first, no area last). */
export function groups(rows: TopicRow[]): [string, TopicRow[]][] {
  const by = new Map<string, TopicRow[]>();
  for (const r of rows) {
    const area = r.area ?? OTHER;
    by.set(area, [...(by.get(area) ?? []), r]);
  }
  return [...by];
}

/** "3 sources · 24 Oct, 10:04" */
export const said = (r: TopicRow) =>
  `${r.sources} ${r.sources === 1 ? "source" : "sources"} · ${whenShort(r.updated_at)}`;

function row(r: TopicRow, fresh: boolean) {
  return h(
    "li",
    { "data-id": r.id },
    h(
      "a",
      { href: `/p/${encodeURIComponent(r.slug)}` },
      h(
        "span",
        {},
        h("strong", { dir: "auto" }, r.title),
        r.summary && h("small", { className: "snip", dir: "auto" }, r.summary),
        h("small", {}, said(r)),
      ),
      // At the row's end, by its title; said in words too (its name and tooltip), not by
      // colour alone
      fresh &&
        h("b", {
          className: "new",
          role: "img",
          "aria-label": "new or changed",
          title: "New or changed since you last looked",
        }),
    ),
  );
}

/** The Topics screen. */
export async function topics(): Promise<Node> {
  const { signal } = view;
  let rows: TopicRow[];
  try {
    if (!navigator.onLine) throw new TypeError("offline");
    rows = await api<TopicRow[]>("topics", { signal });
  } catch (e) {
    return problem(e);
  }
  if (!rows.length) {
    look(rows); // looked, with none: the first ones made after this have a dot
    return h(
      "section",
      { className: "topics" },
      empty(
        "topic",
        "No topics yet.",
        h(
          "small",
          {},
          "Each week Claude looks across your pages for things they keep coming back to, and makes a topic page for each: what they say about it, citing them.",
        ),
      ),
    );
  }
  // Looked: the dots stay while the app is open (Back from a topic keeps them, but for that
  // one's: page.ts clears it),
  // and next time only what changed after now has one
  for (const id of changed(rows, seen())) dots.add(id);
  look(rows);
  const input = h("input", {
    type: "search",
    value: history.state?.filter ?? "", // as typed when a topic was opened from it
    placeholder: "Filter topics",
    "aria-label": "Filter topics",
    autocomplete: "off",
    enterKeyHint: "search",
  });
  const list = h("div", {});
  const count = h("p", { className: "count", role: "status" });
  const draw = () => {
    const typed = input.value.trim();
    const shown = rows.filter((r) => matches(r, typed));
    count.textContent = typed
      ? `${shown.length} of ${rows.length} topics`
      : `${rows.length} ${rows.length === 1 ? "topic" : "topics"}`;
    if (!shown.length) return list.replaceChildren(empty("search", "No topics match."));
    // One trail for the whole screen: a topic opened from it pages on through the others
    const slugs = shown.map((r) => r.slug);
    list.replaceChildren(
      ...groups(shown).map(([area, rs]) =>
        h(
          "section",
          {},
          h("h2", { className: "label" }, `${area} · ${rs.length}`),
          trail(
            h("ul", { className: "list" }, ...rs.map((r) => row(r, dots.has(r.id)))),
            "Topics",
            slugs,
          ),
        ),
      ),
    );
  };
  input.addEventListener(
    "input",
    () => {
      history.replaceState({ ...history.state, filter: input.value }, "");
      draw();
    },
    { signal },
  );
  draw();
  return h(
    "section",
    { className: "topics" },
    h("div", { className: "field-search" }, icon("search"), input),
    count,
    list,
  );
}
