// The search query as text the chips edit (the server parses it: scrap/query.py), and
// the tree of tags. No DOM here, so the unit tests run it; no regular expressions over the
// query, so any input is handled in linear time.

/** A filter as typed: kind:todo, tag:tech/epics, tag:"two words". */
export function token(key: string, value: string): string {
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

/** Where the query's orders stand ([start, end) of sort:due, -SORT:created, sort:"a b"),
 * read the way the server reads a query (scrap/query.py parse): a quoted phrase is text,
 * the key is any case, - or ! negates. */
function sortSpans(q: string): [number, number][] {
  const s = q;
  const n = s.length;
  // a space, or a control character (the server reads those as spaces)
  const gap = (c: string) => c < " " || c === "\x7f" || isSpace(c);
  const spans: [number, number][] = [];
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
      continue;
    }
    let j = i;
    while (j < n && !gap(s[j]) && s[j] !== '"') j++;
    const word = s.slice(i, j);
    const colon = word.indexOf(":");
    if (colon >= 0 && word.slice(0, colon).toLowerCase() === "sort") {
      if (colon === word.length - 1 && s[j] === '"') {
        const end = s.indexOf('"', j + 1);
        j = end < 0 ? n : end + 1;
      }
      spans.push([start, j]);
    }
    i = j;
  }
  return spans;
}

/** The orders a query has, as typed. */
export const sortsIn = (q: string) => sortSpans(q).map(([a, b]) => q.slice(a, b));

/** The query without its orders, its spaces tidied (a phrase's own spaces kept). */
export const unsorted = (q: string) =>
  sortSpans(q)
    .reduceRight((rest, [a, b]) => `${rest.slice(0, a).trimEnd()} ${rest.slice(b).trimStart()}`, q)
    .trim();

/** A date picker's value as after:/before: take it (YYYY-MM-DD, years 1 to 9999), or ""
 * (a typed year past 9999 is clamped to 9999-12-31). */
export function day(v: string): string {
  if (v.length === 10 && v[4] === "-" && v[7] === "-") return v;
  return v.length > 10 && /^\+?\d{5,}-/.test(v) ? "9999-12-31" : "";
}

export interface TagNode {
  path: string;
  name: string; // its last part
  n: number; // pages with it or a tag under it
  kids: TagNode[];
}

/** The tree of tags; the server lists a/b's parent a too, in order. */
export function tree(list: [string, number][]): TagNode[] {
  const top: TagNode[] = [];
  const at = new Map<string, TagNode>();
  for (const [path, n] of list) {
    const cut = path.lastIndexOf("/");
    const node = { path, name: path.slice(cut + 1), n, kids: [] };
    at.set(path, node);
    (at.get(path.slice(0, Math.max(cut, 0)))?.kids ?? top).push(node);
  }
  return top;
}

// ---- the search screen's kind row: All, Notes, Todos, Reads, Boards, Docs

/** [label, the kind: it sets, every kind: value meaning it (what the server takes), the API's
 * kind] */
export const KIND_ROW: [string, string, string[], string][] = [
  ["Notes", "note", ["note"], "note"],
  ["Todos", "todo", ["todo"], "todo"],
  ["Reads", "read", ["read", "consume"], "consume"],
  ["Boards", "board", ["board", "whiteboard"], "whiteboard"],
  ["Docs", "doc", ["doc", "document"], "document"],
];

const ROW_KINDS = new Set(KIND_ROW.flatMap(([, , names]) => names.map((n) => `kind:${n}`)));
/** A token the kind row stands for, in any case as the server takes it (kind:Todo too). */
const rowKind = (t: string) => ROW_KINDS.has(t.toLowerCase());

/** The query without the kind row's kinds (kind:todo, kind:consume; not -kind:todo). */
export const unkinded = (q: string) =>
  q
    .split(/\s+/)
    .filter((t) => t && !rowKind(t))
    .join(" ");

/** The kinds of the row a query asks for (two kinds mean either). */
export function kindsIn(q: string) {
  const asked = new Set(q.toLowerCase().split(/\s+/).filter(rowKind));
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
  if (unkinded(q).trim()) return null;
  const on = kindsIn(q);
  if (on.length > 1) return null;
  return on.length ? `kind=${on[0][3]}` : "";
}
