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
