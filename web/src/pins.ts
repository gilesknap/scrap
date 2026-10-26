// Pinned searches and pages (design mock, #309 phase 2): a server page that is only a list of
// links, titled Pinned (slug `pinned`), made on the first pin. Its links, in order, are the
// launcher under the empty search box (searches.ts); a search's count line (searchacts.ts) and
// a page's Share menu (page.ts) pin and unpin by adding or taking out a line. Being a page, it
// syncs across devices and is edited, reordered and renamed (a link's text) like any page.
//   - [People](/search?q=tag:person%20group:letter)
//   - [Contacts](/p/contacts)
import { ApiError, api, type Page } from "./api";
import { checkName } from "./checks";
import { MEDIA } from "./termedit";
import { KIND_ROW, words } from "./terms";
import { h, toast } from "./ui";

export const SLUG = "pinned";
export const PINS_PAGE = `/p/${SLUG}`;
/** Fired on document when the pins change (here, or read again). */
export const CHANGED = "pinschange";

export interface Pin {
  name: string; // the link's text
  href: string; // as written: /search?q=..., /p/slug, or any address
  key: string; // what it is, for "is it pinned?": s:<query> or p:<slug> ("" for elsewhere)
}

const tidy = (q: string) => q.trim().replace(/\s+/g, " ");

/** A search's address as a link on the page: readable (: and / kept), and safe in Markdown. */
export const searchHref = (q: string) =>
  `/search?q=${encodeURIComponent(tidy(q))
    .replaceAll("%3A", ":")
    .replaceAll("%2F", "/")
    .replaceAll("(", "%28")
    .replaceAll(")", "%29")}`;
export const pageHref = (slug: string) => `/p/${encodeURIComponent(slug)}`;

/** What a link points at, so the same search typed differently is still the same pin. */
export function keyOf(href: string): string {
  let u: URL;
  try {
    u = new URL(href, location.origin);
  } catch {
    return "";
  }
  if (u.origin !== location.origin) return "";
  if (u.pathname === "/search") return `s:${tidy(u.searchParams.get("q") ?? "")}`;
  const p = /^\/p\/([^/]+)$/.exec(u.pathname);
  if (!p) return "";
  try {
    return `p:${decodeURIComponent(p[1])}`;
  } catch {
    return "";
  }
}

// A list item that is only a link: - [name](href)
const LINE = /^\s*[-*+]\s+\[((?:\\.|[^\]\\])*)\]\(\s*<?([^)\s>]+)>?\s*\)\s*$/;
const unslash = (s: string) => s.replace(/\\(.)/g, "$1");
const slashed = (s: string) => s.replace(/[[\]\\]/g, "\\$&");

/** The pins in a page's text, in order. */
export function parse(body: string): Pin[] {
  const out: Pin[] = [];
  for (const line of body.split("\n")) {
    const m = LINE.exec(line);
    // (only a search or a page here: the page is editable over MCP, so no javascript: or
    // off-site link is ever shown, keyOf being empty for those)
    const key = m ? keyOf(m[2]) : "";
    if (m && key) out.push({ name: unslash(m[1]).trim(), href: m[2], key });
  }
  return out;
}

export const line = (name: string, href: string) => `- [${slashed(name)}](${href})`;

/** The text with a pin added at its end (or at a line: Undo puts one back where it was). */
export function adding(body: string, name: string, href: string, at?: number): string {
  const lines = body.replace(/\s+$/, "").split("\n");
  if (!body.trim()) return `${line(name, href)}\n`;
  if (at === undefined || at >= lines.length) lines.push(line(name, href));
  else lines.splice(at, 0, line(name, href));
  return `${lines.join("\n")}\n`;
}

/** The text without the lines that pin key, and where the first of them was. */
export function removing(body: string, key: string): [string, number] {
  const lines = body.split("\n");
  let at = -1;
  const kept = lines.filter((l, i) => {
    const m = LINE.exec(l);
    const hit = !!m && keyOf(m[2]) === key;
    if (hit && at < 0) at = i;
    return !hit;
  });
  return [kept.join("\n"), at];
}

// ---- a search's default name: its query made readable ("#person · grouped A–Z")

const GROUPS: Record<string, string> = {
  letter: "grouped A–Z",
  tag: "grouped by tag",
  type: "grouped by type",
  now: "grouped by Now",
  due: "grouped by due",
  area: "grouped by area",
  none: "not grouped",
};
const SORTS: Record<string, string> = {
  title: "A–Z",
  created: "newest",
  "-created": "oldest",
  updated: "last edited",
  "-updated": "first edited",
  due: "due soonest",
  priority: "by priority",
};
const RANGES: Record<string, string> = { "1w": "past week", "1m": "past month", "1y": "past year" };
const IS: Record<string, string> = { claude: "by Claude", snoozed: "snoozed", topic: "topics" };

/** One word of a query, said as the Filters on row says it. */
function say(word: string, key: string): string {
  const neg = "-!".includes(word[0]);
  const raw = neg ? word.slice(1) : word;
  const value = raw.slice(raw.indexOf(":") + 1).replaceAll('"', "");
  const v = value.toLowerCase();
  const not = neg ? "not " : "";
  switch (key.toLowerCase()) {
    case "":
      return word;
    case "tag":
      return `${not}#${v}`;
    case "kind":
      return `${not}${KIND_ROW.find(([, , names]) => names.includes(v))?.[0] ?? v}`;
    case "group":
      return GROUPS[v] ?? `group:${v}`;
    case "sort":
      return SORTS[`${neg ? "-" : ""}${v}`] ?? word;
    case "after":
      return RANGES[v] ?? `since ${v}`;
    case "before":
      return `before ${v}`;
    case "media":
      return `${not}${MEDIA[v] ?? v}`;
    case "later":
      return `${not}to ${v}`;
    case "is":
      return `${not}${checkName(`is:${v}`) ?? IS[v] ?? v.replace("_", " ")}`;
    default:
      return `${not}${checkName(`${key}:${v}`) ?? word}`;
  }
}

/** A search's default pin name: its words in order, each as a chip says it. */
export function nameOf(q: string): string {
  const said = words(q).map(([a, b, k]) => say(q.slice(a, b), k));
  return said.join(" · ") || "Every page";
}

// ---- the page on the server

let cache: Promise<Page | null> | null = null;
let watching = false;
// A change anywhere in the app (an edit of the Pinned page itself, say), or the app back from
// the background (another device may have pinned meanwhile): read it again
const watch = () => {
  if (watching) return;
  watching = true;
  const forget = () => {
    cache = null;
  };
  addEventListener("scrap:wrote", forget);
  document.addEventListener("visibilitychange", forget);
};

// (GET /api/pinned: null while there is none, not a 404 in the console on every visit)
const read = () => api<Page | null>("pinned");

/** The Pinned page (null: none yet), read once until something changes. */
const pinnedPage = () => {
  watch();
  cache ??= read();
  cache.catch(() => {
    cache = null; // offline: ask again next time
  });
  return cache;
};

/** The pins, in order (none offline, or before the first). */
export const pins = (): Promise<Pin[]> =>
  pinnedPage().then(
    (p) => (p ? parse(p.body) : []),
    () => [],
  );

export const isPinned = async (key: string) => (await pins()).some((p) => p.key === key);

/** Change the Pinned page's text, making it on the first pin (POST /api/pinned: the server
 * reserves the slug, so two first pins at once make one page). Two devices at once: the PATCH
 * carries the revision it was made from, and on a 409 it is read and made again. */
export async function change(edit: (body: string) => string): Promise<void> {
  for (let tries = 0; tries < 3; tries++) {
    let p = await read();
    if (!p) {
      if (!edit("").trim()) return; // nothing to take out of a page not there
      p = await api<Page>("pinned", { method: "POST" }); // the server makes it once
    }
    try {
      const after = await api<Page>(`pages/${p.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: edit(p.body), base_rev: p.rev }),
      });
      cache = Promise.resolve(after);
      break;
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409) || tries === 2) throw e;
    }
  }
  document.dispatchEvent(new Event(CHANGED));
}

const failed = (e: unknown) =>
  toast(`Not pinned: ${(e as Error).message || "can't reach the server"}`, "", undefined, 8000);

/** Pin a search or a page (toast "Pinned", with Undo). */
export async function pin(name: string, href: string): Promise<void> {
  const key = keyOf(href);
  try {
    await change((body) =>
      parse(body).some((p) => p.key === key) ? body : adding(body, name, href),
    );
  } catch (e) {
    return failed(e);
  }
  toast("Pinned", "Undo", () => void change((body) => removing(body, key)[0]).catch(failed));
}

/** Take a pin out (toast "Unpinned", with Undo: it goes back where it was, named as it was). */
export async function unpin(key: string): Promise<void> {
  let was: Pin | undefined;
  let at = -1;
  try {
    await change((body) => {
      was = parse(body).find((p) => p.key === key);
      const [rest, i] = removing(body, key);
      at = i;
      return rest;
    });
  } catch (e) {
    return failed(e);
  }
  const back = was;
  if (back)
    toast(
      "Unpinned",
      "Undo",
      () => void change((body) => adding(body, back.name, back.href, at)).catch(failed),
    );
}

/** A page's Share menu row: Pin to Search, or Unpin from Search once pinned. */
export function pinPageButton(slug: string, title: string): HTMLButtonElement {
  const href = pageHref(slug);
  const key = keyOf(href);
  const b = h("button", { type: "button" }, pinIcon(), "Pin to Search");
  const show = (on: boolean) =>
    b.replaceChildren(pinIcon(), on ? "Unpin from Search" : "Pin to Search");
  void isPinned(key).then(show);
  b.onclick = async () => {
    if (await isPinned(key)) await unpin(key);
    else await pin(title, href);
    show(await isPinned(key));
  };
  return b;
}

/** A pushpin, kept here (not icons.ts) so the app shell does not carry it. */
export function pinIcon(): SVGSVGElement {
  const t = document.createElement("template");
  t.innerHTML =
    '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 3.5h7M10 3.5v5.5l-3.5 4v1.5h11V13L14 9V3.5M12 14.5v6"/></svg>';
  return t.content.firstChild as SVGSVGElement;
}
