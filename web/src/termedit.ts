// Writing chips into the query (the Filters panel, the Later type): a chunk of its own, with
// the panel, not the app shell
import { adding, find, type Group, groupDefault, ungrouped } from "./terms";

/** The query without a token, its spaces tidied. */
export function removing(q: string, t: string): string {
  const i = find(q, t);
  if (i < 0) return q;
  return `${q.slice(0, i).trimEnd()} ${q.slice(i + t.length).trimStart()}`.trim();
}

/** The query with its grouping chosen ("none" for a flat list): the list's own is no word. */
export function withGroup(q: string, g: Group | "none"): string {
  const rest = ungrouped(q);
  return g === (groupDefault(rest) ?? "none") ? rest : adding(rest, `group:${g}`);
}

// ---- Later's own: media:book (its medium) and later:watch (what it is for: read, watch,
// listen, play): the server filters by both; the app says them as chips

/** media: values, and how a filter chip says each. */
export const MEDIA: Record<string, string> = {
  book: "books",
  article: "articles",
  film: "films",
  tv: "TV",
  video: "videos",
  podcast: "podcasts",
  music: "music",
  game: "games",
};
