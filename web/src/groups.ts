// A list in sections, as both the search screen (group: in its query, terms.ts) and the Todos
// screen (Now) draw it: sections.ts draws them, each an h2.label "To watch · 4" over its rows,
// a folded one (Done) a .donefold at the end. No DOM here, so the unit tests run it.
import type { Summary } from "./api";
import { isOpen, now } from "./now";
import type { Group } from "./terms";

export interface Section<T> {
  label: string; // "" for no heading
  items: T[];
  fold?: boolean; // folded away at the end (Done)
  open?: boolean; // a fold open to start with
  trail?: string; // a pager trail of its own (the Todos screen's Done), else the list's
}

type Item = Pick<
  Summary,
  "title" | "kind" | "fields" | "due" | "priority" | "updated_at" | "snoozed_until"
> & { tags?: string[] };

/** Later's types, in their order: [subtype, heading]. */
const TYPES = [
  ["read", "To read"],
  ["watch", "To watch"],
  ["listen", "To listen"],
  ["play", "To play"],
];

/** A title's first letter, A to Z (its accent dropped), else "#". */
const letterOf = (title: string) => {
  const c = title.trim().normalize("NFD").charAt(0).toUpperCase();
  return c >= "A" && c <= "Z" ? c : "#";
};

/** Items put in named sections, each keeping the order they came in, the sections in order. */
function bucket<T>(items: T[], key: (t: T) => string, order: string[]): Section<T>[] {
  const by = new Map(order.map((k) => [k, [] as T[]]));
  for (const t of items) by.get(key(t))?.push(t);
  return [...by].filter(([, ts]) => ts.length).map(([label, ts]) => ({ label, items: ts }));
}

/** The list in sections, by how (terms.ts groupBy). tag: the tag filtered by (group:tag);
 * today: YYYY-MM-DD (group:now); ranked: Now's own order in its sections (no order chosen),
 * else each keeps the list's. */
export function sections<T extends Item>(
  how: Group,
  items: T[],
  { tag = "", today = "", ranked = true } = {},
): Section<T>[] {
  if (how === "letter") {
    const keys = [...new Set(items.map((t) => letterOf(t.title)))].sort((a, b) =>
      a === "#" ? 1 : b === "#" ? -1 : a.localeCompare(b),
    );
    return bucket(items, (t) => letterOf(t.title), keys);
  }
  if (how === "tag") {
    // One section per tag under the one filtered by (person: person/family as "family"),
    // alphabetically; a page with two goes in the first; one with none in Other, last
    const under = `${tag.toLowerCase()}/`;
    const subs = (t: T) =>
      (t.tags ?? [])
        .filter((x) => x.toLowerCase().startsWith(under))
        .map((x) => x.slice(under.length).split("/")[0])
        .sort();
    const key = (t: T) => subs(t)[0] ?? "Other";
    const keys = [...new Set(items.flatMap(subs))].sort();
    return bucket(items, key, [...keys, "Other"]);
  }
  const done = items.filter((t) => !isOpen(t));
  // Done, folded: open when it is all there is (is:done), so the list isn't one closed line
  const fold: Section<T>[] = done.length
    ? [{ label: "Done", items: done, fold: true, open: done.length === items.length }]
    : [];
  const open = items.filter(isOpen);
  if (how === "type") {
    const type = (t: T) => {
      const s = String(t.fields.subtype ?? "read");
      return TYPES.find(([k]) => k === s)?.[1] ?? "To read";
    };
    return [
      ...bucket(
        open,
        type,
        TYPES.map(([, label]) => label),
      ),
      ...fold,
    ];
  }
  // Now: the Todos screen's sections (now.ts), then the snoozed ones (out of Now till their
  // day, but still found), then Done
  const first = new Map(items.map((t, i) => [t, i]));
  const asFound = (ts: T[]) =>
    ranked ? ts : ts.sort((a, b) => (first.get(a) ?? 0) - (first.get(b) ?? 0));
  const groups = now(open, today).map(([label, ts]) => ({ label, items: asFound(ts) }));
  const shown = new Set(groups.flatMap((g) => g.items));
  const asleep = open.filter((t) => !shown.has(t));
  return [...groups, ...(asleep.length ? [{ label: "Snoozed", items: asleep }] : []), ...fold];
}
