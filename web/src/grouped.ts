// The search screen's results in sections (group: in the query, or Later's and Todos' own:
// terms.ts groupBy), drawn as the Todos screen draws Now (sections.ts). Grouped here, in the
// app, from the hits fetched: a chunk of its own, loaded only for a grouped list.
import type { Hit } from "./api";
import { sections } from "./groups";
import { drawSections } from "./sections";
import { today } from "./status";
import { adding, type Group, tagsIn, words } from "./terms";
import { h } from "./ui";

// The tags each hit has, for group:tag (the mock's server sends them with each hit)
type Tagged = Hit & { tags?: string[] };

/** The hits in sections, by how; row draws a hit's row; label: the pager's list. */
export function grouped(
  hits: Tagged[],
  how: Group,
  query: string,
  row: (hit: Hit) => Element,
  label: string,
) {
  const ranked = !/(^|\s)-?sort:/.test(query); // no order chosen: Now ranks its own
  const secs = sections(how, hits, { tag: tagsIn(query)[0], today: today(), ranked });
  // A Type heading is a quiet link to that type alone (later:watch), unless one is asked
  const typed = words(query).some(([, , k]) => k === "later");
  for (const s of secs)
    if (s.key && !typed)
      s.href = `/search?q=${encodeURIComponent(adding(query, `later:${s.key}`))}`;
  return h("div", { className: "groups" }, ...drawSections(secs, row, label, "group"));
}
