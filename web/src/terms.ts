// The search query as text the chips edit (the server parses it: scrap/query.py). No DOM
// here, so the unit tests run it; no regular expressions over the query, so any input is
// handled in linear time.

/** A filter as typed: kind:todo, tag:tech/epics, tag:"two words". The query has no escape
 * for a quote, so a tag with one is asked for by its segments before the quote (tag:a for
 * a/b"c), or else by its words as text (tags are searched too). */
export function token(key: string, value: string): string {
  if (key === "tag" && value.includes('"')) {
    const kept = value.split("/");
    kept.length = kept.findIndex((s) => s.includes('"'));
    return kept.length
      ? token(key, kept.join("/"))
      : value.replaceAll('"', " ").split(" ").filter(Boolean).join(" ");
  }
  const v = value.replaceAll('"', "");
  return v.includes(" ") ? `${key}:"${v}"` : `${key}:${v}`;
}

const isSpace = (c: string | undefined) => c === undefined || c.trim() === "";

/** Where a token stands alone in a query (spaces or an end either side), or -1. */
function find(q: string, t: string): number {
  if (!t) return -1;
  for (let i = q.indexOf(t); i >= 0; i = q.indexOf(t, i + 1)) {
    if (isSpace(q[i - 1]) && isSpace(q[i + t.length])) return i;
  }
  return -1;
}

export const has = (q: string, t: string) => find(q, t) >= 0;

/** The query with a token added at the end (once). */
export const adding = (q: string, t: string) => (has(q, t) ? q : `${q.trim()} ${t}`.trim());

/** The query without a token, its spaces tidied. */
export function removing(q: string, t: string): string {
  const i = find(q, t);
  if (i < 0) return q;
  return `${q.slice(0, i).trimEnd()} ${q.slice(i + t.length).trimStart()}`.trim();
}

/** Where the query's words stand ([start, end) and the key before a colon, any case, or ""),
 * read the way the server reads a query (scrap/query.py parse): a quoted phrase is one word
 * (its own text, no key), - or ! negates, key:"a b" is one word. */
export function words(q: string): [number, number, string][] {
  const s = q;
  const n = s.length;
  // a space, or a control character (the server reads those as spaces)
  const gap = (c: string) => c < " " || c === "\x7f" || isSpace(c);
  const out: [number, number, string][] = [];
  let i = 0;
  while (i < n) {
    if (gap(s[i])) {
      i++;
      continue;
    }
    const start = i;
    if ("-!".includes(s[i])) i++;
    if (s[i] === '"') {
      // a phrase, to the next quote (or the end)
      const end = s.indexOf('"', i + 1);
      i = end < 0 ? n : end + 1;
      out.push([start, i, ""]);
      continue;
    }
    let j = i;
    while (j < n && !gap(s[j]) && s[j] !== '"') j++;
    const word = s.slice(i, j);
    const colon = word.indexOf(":");
    if (colon === word.length - 1 && s[j] === '"') {
      const end = s.indexOf('"', j + 1);
      j = end < 0 ? n : end + 1;
    }
    out.push([start, j, colon >= 0 ? word.slice(0, colon).toLowerCase() : ""]);
    i = j;
  }
  return out;
}

/** The query without some of its words, its spaces tidied (a phrase's own spaces kept). */
export const without = (q: string, spans: [number, number, string][]) =>
  spans
    .reduceRight((rest, [a, b]) => `${rest.slice(0, a).trimEnd()} ${rest.slice(b).trimStart()}`, q)
    .trim();

// ---- the search screen's kind row: All, Notes, Todos, Later, Boards, Docs

/** [label, the kind: it sets, every kind: value meaning it (what the server takes), the API's
 * kind] */
export const KIND_ROW: [string, string, string[], string][] = [
  ["Notes", "note", ["note"], "note"],
  ["Todos", "todo", ["todo"], "todo"],
  ["Later", "later", ["later", "read", "consume"], "consume"],
  ["Boards", "board", ["board", "whiteboard"], "whiteboard"],
  ["Docs", "doc", ["doc", "document"], "document"],
];

const ROW_KINDS = new Set(KIND_ROW.flatMap(([, , names]) => names.map((n) => `kind:${n}`)));
/** A token the kind row stands for, in any case as the server takes it (kind:Todo too). */
const rowKind = (t: string) => ROW_KINDS.has(t.toLowerCase());

/** The words the kind row stands for (kind:todo, kind:consume; not -kind:todo, nor inside a
 * quoted phrase). */
const kindWords = (q: string) => words(q).filter(([a, b]) => rowKind(q.slice(a, b)));

/** The query without the kind row's kinds. */
export const unkinded = (q: string) => without(q, kindWords(q));

/** The kinds of the row a query asks for (two kinds mean either). */
export function kindsIn(q: string) {
  const asked = new Set(kindWords(q).map(([a, b]) => q.slice(a, b).toLowerCase()));
  return KIND_ROW.filter(([, , names]) => names.some((n) => asked.has(`kind:${n}`)));
}

/** The query with the row's kind tapped: set, or cleared if it was the only one (value "":
 * All, clearing any). */
export function withKind(q: string, value: string): string {
  const on = kindsIn(q);
  const rest = unkinded(q);
  if (!value || (on.length === 1 && on[0][1] === value)) return rest;
  return adding(rest, `kind:${value}`);
}

/** A query the newest-first list answers (with its thumbnails): nothing, or one kind alone.
 * Its API filter (kind=todo, or ""), else null: a search. */
export function listing(q: string): string | null {
  if (unkinded(ungrouped(q)).trim()) return null;
  const on = kindsIn(q);
  if (on.length > 1) return null;
  return on.length ? `kind=${on[0][3]}` : "";
}

// ---- grouping the results (group:letter, group:tag, group:type, group:now, group:none): read
// by the app, never sent to the server (served())

/** How a list can be grouped (groups.ts makes the sections). */
export type Group = "letter" | "tag" | "type" | "now";

const keyed = (q: string, key: string) => words(q).filter(([, , k]) => k === key);
/** A word's value: after its colon, its quotes taken off. */
const wordValue = (q: string, [a, b]: [number, number, string]) => {
  const w = q.slice(a, b);
  return w
    .slice(w.indexOf(":") + 1)
    .replaceAll('"', "")
    .toLowerCase();
};

/** The query without its group: words. */
export const ungrouped = (q: string) => without(q, keyed(q, "group"));

/** The group: asked for (the last one), as typed in lower case ("none" too), or null. */
export function groupAsked(q: string): string | null {
  const g = keyed(q, "group").filter(([a]) => !"-!".includes(q[a]));
  return g.length ? wordValue(q, g[g.length - 1]) : null;
}

/** The tags the query filters by (tag:person, not -tag:person). */
export const tagsIn = (q: string) =>
  keyed(q, "tag")
    .filter(([a]) => !"-!".includes(q[a]))
    .map((w) => wordValue(q, w));

/** A list's own grouping when none is asked for: Later alone by type, Todos alone by Now. */
export function groupDefault(q: string): Group | null {
  const on = kindsIn(q);
  if (on.length !== 1) return null;
  return on[0][1] === "later" ? "type" : on[0][1] === "todo" ? "now" : null;
}

/** How the results are grouped, if at all: as asked, where it applies (by tag needs a tag
 * filter; by type and Now only for Later and Todos alone), else the list's own. */
export function groupBy(q: string): Group | null {
  const asked = groupAsked(q);
  if (asked === null) return groupDefault(q);
  if (asked === "letter") return "letter";
  if (asked === "tag") return tagsIn(q).length ? "tag" : null;
  if (asked === "type" || asked === "now") return groupDefault(q) === asked ? asked : null;
  return null; // none, or a word we don't know
}

/** The query with its grouping chosen ("none" for a flat list): the list's own is no word. */
export function withGroup(q: string, g: Group | "none"): string {
  const rest = ungrouped(q);
  return g === (groupDefault(rest) ?? "none") ? rest : adding(rest, `group:${g}`);
}

/** The query as the server gets it: no group: words, and A–Z groups sorted A–Z unless an
 * order is chosen. */
export function served(q: string): string {
  const rest = ungrouped(q);
  return groupBy(q) === "letter" && !keyed(rest, "sort").length ? adding(rest, "sort:title") : rest;
}
