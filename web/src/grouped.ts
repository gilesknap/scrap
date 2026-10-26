// The search screen's results in sections (group: in the query, or Later's and Todos' own:
// terms.ts groupBy), drawn as the Todos screen draws Now (sections.ts). Grouped here, in the
// app, from the hits fetched: a chunk of its own, loaded only for a grouped list.
import type { Hit } from "./api";
import { sections } from "./groups";
import { drawSections } from "./sections";
import { today } from "./status";
import { swipeRows, trail } from "./swipe";
import { adding, type Group, tagsIn, words } from "./terms";
import { h } from "./ui";

/** The hits in sections, by how; row draws a hit's row; label: the pager's list. */
export function grouped(
  hits: Hit[],
  how: Group,
  query: string,
  row: (hit: Hit) => Element,
  label: string,
) {
  const ranked = !/(^|\s)-?sort:/.test(query); // no order chosen: Now ranks its own
  const secs = sections(how, hits, { tag: tagsIn(query)[0], today: today(), ranked });
  if (how === "letter") return lettered(secs, row, label);
  // A Type heading is a quiet link to that type alone (later:watch), unless one is asked
  const typed = words(query).some(([, , k]) => k === "later");
  for (const s of secs)
    if (s.key && !typed)
      s.href = `/search?q=${encodeURIComponent(adding(query, `later:${s.key}`))}`;
  return h("div", { className: "groups" }, ...drawSections(secs, row, label, "group"));
}

/** A–Z as a phone's contacts list has it: one card, each letter a slim divider row inside it
 * (no count), sticky under the top bar while its rows scroll by. One pager trail. */
function lettered(
  secs: ReturnType<typeof sections<Tagged>>,
  row: (hit: Hit) => Element,
  label: string,
) {
  const pairs: [Element, Hit][] = [];
  const kids = secs.flatMap((s) => [
    h("li", { className: "letter" }, h("h2", { className: "label" }, s.label)),
    ...s.items.map((hit) => {
      const li = row(hit);
      pairs.push([li, hit]);
      return li;
    }),
  ]);
  const ul = trail(
    h("ul", { className: "list az" }, ...kids),
    label,
    pairs.map(([, hit]) => hit.slug),
  );
  swipeRows(pairs);
  return h("div", { className: "groups" }, ul);
}
