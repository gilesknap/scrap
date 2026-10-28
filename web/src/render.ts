// Page text as HTML: Markdown by markdown-it (a chunk of its own, kept for offline use), with
// GitHub's tables, task lists, ~~strikethrough~~, bare links and footnotes, plus [[slug]] and
// [[slug|label]] links to other pages. Raw HTML is shown as text; a line break stays one.
// Links are http(s), mailto, a page or screen here (/search?q=..., /todos; a full address of
// one opens in the app, as [[slug]] does) or a heading of this page; images only this
// server's own files, each marked with its file's data-sha for the page to make a figure of.
// A ```mermaid block is drawn as a diagram, by Mermaid, a chunk of its own loaded only then.
// The server parses text the same way for search (src/scrap/markdown.py). The stored text is
// never changed. On a Later page, a link on its own line is drawn as a card (cards()).
import markdownit, { type StateCore, type StateInline, type Token } from "markdown-it";
import footnote from "markdown-it-footnote";
import { icon } from "./icons";

const IMAGE = /^\/api\/blobs\/([0-9a-f]{64})(\/preview\?size=(480|2048))?$/;
const EXTERNAL = /^(https?:\/\/|mailto:)/i;
// A link to one of this server's files (a PDF, a .md) where the text puts it (#403)
const FILE = /^\/api\/blobs\/([0-9a-f]{64})(\?download=1)?$/;
const PAGE = /^\/p\/[a-z0-9-]+$/;
// The app's own screens a link may open in place: Capture, Search (with its query), Todos, Topics
const SCREEN = /^\/(search|todos|topics)?$/;
/** A path the app opens in place: a page here, or one of its screens. */
const inApp = (path: string) => PAGE.test(path) || SCREEN.test(path);
const FOOTNOTE = /^#fn(ref)?\d+(:\d+)?$/;
const WIKI = /^([a-z0-9-]+)(?:\\?\|(.+))?$/;

const md = markdownit({ html: false, breaks: true, linkify: true });
md.linkify.set({ fuzzyLink: false, fuzzyEmail: false }).add("ftp:", null).add("//", null);
md.use(footnote);
md.inline.ruler.before("link", "wiki", wiki);
md.core.ruler.push("scrap", tidy);
// A table scrolls sideways in a box of its own, not the page
md.renderer.rules.table_open = () => '<div class="table"><table>\n';
md.renderer.rules.table_close = () => "</table></div>\n";

/** [[slug]] and [[slug|label]] (the label may be formatted; in a table cell, [[slug\|label]]).
 * One scan to the next bracket or line end, so no text is read twice. */
function wiki(state: StateInline, silent: boolean): boolean {
  const { src, pos, posMax } = state;
  if (!src.startsWith("[[", pos)) return false;
  let end = pos + 2;
  while (end < posMax && !"[]\n".includes(src[end])) end++;
  const m = src.startsWith("]]", end) && WIKI.exec(src.slice(pos + 2, end));
  if (!m) return false;
  if (!silent) {
    const open = state.push("link_open", "a", 1);
    open.attrs = [["href", `/p/${m[1]}`]];
    open.meta = { wiki: true };
    if (m[2]) {
      state.pos = end - m[2].length;
      state.posMax = end;
      state.linkLevel++;
      state.md.inline.tokenize(state);
      state.linkLevel--;
      state.posMax = posMax;
    } else state.push("text", "", 0).content = m[1];
    state.push("link_close", "a", -1);
  }
  state.pos = end + 2;
  return true;
}

/** A URL's origin, as the browser writes it (lower case, no default port); else null. */
function originOf(href: string): string | null {
  try {
    return new URL(href).origin;
  } catch {
    return null;
  }
}

/** The origins this server is reached at: the one this app was loaded from, and every address
 * in $SCRAP_PUBLIC_URL, which the server writes into index.html's scrap-origins meta tag (in
 * the shell the service worker keeps, so offline too). */
export function origins(): string[] {
  const here = globalThis.location?.origin;
  const meta = globalThis.document?.querySelector<HTMLMetaElement>('meta[name="scrap-origins"]');
  const listed = (meta?.content ?? "").split(/\s+/).filter(Boolean).map(originOf);
  return [here, ...listed].filter((o): o is string => !!o && o !== "null");
}

/** A web address of a page or screen on this server (/p/slug, /search?q=..., /todos, /topics
 * or / on any of its origins), as its own path (with any query or #heading); else null. */
export function own(href: string, here: readonly string[] = origins()): string | null {
  if (!here.length || !/^https?:\/\//i.test(href)) return null;
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  return here.includes(url.origin) && inApp(url.pathname)
    ? url.pathname + url.search + url.hash
    : null;
}

/** A heading's id: its text, as GitHub makes one, after "h-" (no clash with the app's). */
const anchor = (text: string) =>
  `h-${text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s/g, "-")}`;

/** A link's text as typed: markdown-it percent-encodes an href (a malformed % stays). */
function decoded(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/** A list item's first line: quote markers, then a bullet or number, then its task marker (as
 * the server counts them, markdown.py ITEM; tasks.ts ticks it there). */
export const ITEM = /^((?:[ \t]*>)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[([ xX])\]/;

/** After parsing: safe links and images, heading ids, task list boxes, and each block's lines
 * in the source (data-at="start,end"), so a page's Edit opens where it is read (readat.ts). */
function tidy(state: StateCore) {
  const ids = new Map<string, number>();
  const tokens = state.tokens;
  let lines: string[] | undefined; // the source's, for task boxes, split once
  tokens.forEach((t, i) => {
    if (t.map) t.attrSet("data-at", t.map.join());
    if (t.type === "heading_open") {
      const text = tokens[i + 1]?.children?.map((c) => c.content).join("") ?? "";
      const id = anchor(text);
      const n = ids.get(id) ?? 0;
      ids.set(id, n + 1);
      t.attrSet("id", n ? `${id}-${n}` : id);
    }
    if (t.type !== "inline" || !t.children) return;
    const item = tokens[i - 2];
    if (tokens[i - 1]?.type === "paragraph_open" && item?.type === "list_item_open" && item.map) {
      lines ??= state.src.split("\n");
      task(t, item, lines[item.map[0]] ?? "", state);
    }
    t.children = inline(t.children, state);
  });
}

/** A list item that starts [ ] or [x], typed so on its first line (so not escaped, nor a link
 * named [x]): a box, ticked or not, disabled here, named by its item's text; data-line is
 * that line in the source, so a page can tick it there (tasks.ts), and a label around it
 * gives it a --tap target. */
function task(t: Token, item: Token, line: string, state: StateCore) {
  const first = t.children?.[0];
  const m = first?.type === "text" && /^\[([ xX])\](?: |$)/.exec(first.content);
  if (!first || !m || !ITEM.test(line)) return;
  first.content = first.content.slice(m[0].length);
  const said = (t.children ?? [])
    .map((c) => (c.type === "text" || c.type === "code_inline" ? c.content : " "))
    .join("")
    .replace(/\s+/g, " ")
    .trim();
  const name = state.md.utils.escapeHtml([...said].slice(0, 120).join("") || "Task");
  const box = new state.Token("html_inline", "", 0);
  box.content = `<label class="taskbox"><input type="checkbox" aria-label="${name}" data-line="${item.map?.[0]}" disabled${m[1] === " " ? "" : " checked"}></label> `;
  t.children?.unshift(box);
  item.attrJoin("class", "task");
}

function inline(children: Token[], state: StateCore): Token[] {
  const out: Token[] = [];
  const opened: Token[] = []; // the open links: a close is dropped with its open
  for (const t of children) {
    if (t.type === "link_open") {
      const href = String(t.attrGet("href") ?? "");
      const here = own(href);
      // A link in a link (a bare URL in a link's text): its text only
      if (opened.some((o) => !o.hidden)) t.hidden = true;
      else if (here) {
        // A page here written as a full address (as a model writes one): opened in the app, as
        // [[slug]] is, not in a new window (in the phone's app, one with no Back to this page)
        t.attrSet("href", here);
      } else if (FILE.test(href)) {
        // opened as a file row's is; the page's figures make one on a line of its own a row
        t.attrSet("target", "_blank");
        t.attrSet("rel", "noopener");
        t.attrSet("data-sha", href.slice(11, 75));
      } else if (EXTERNAL.test(href)) {
        t.attrSet("target", "_blank");
        t.attrSet("rel", "noopener noreferrer");
      } else if (href.startsWith("#")) {
        // A heading's id; a footnote's (fn1, fnref1, as markdown-it-footnote makes) as it is
        if (!FOOTNOTE.test(href)) t.attrSet("href", `#${anchor(decoded(href.slice(1)))}`);
      } else if (!t.meta?.wiki && !inApp(href.replace(/[?#].*/s, ""))) {
        // its text stays (a page's or a screen's path may have a query or #heading)
        t.hidden = true;
      }
      opened.push(t);
    } else if (t.type === "link_close") {
      t.hidden = !!opened.pop()?.hidden;
    } else if (t.type === "footnote_ref" && opened.some((o) => !o.hidden)) {
      // A footnote's link in a link's text: its number only
      const text = new state.Token("text", "", 0);
      text.content = `[${Number(t.meta?.id) + 1}]`;
      out.push(text);
      continue;
    } else if (t.type === "image") {
      const src = String(t.attrGet("src") ?? "");
      const own = IMAGE.exec(src);
      if (own) {
        t.attrSet("loading", "lazy");
        t.attrSet("data-sha", own[1]);
      } else {
        // Not this server's: no image from elsewhere, a link to it if it is the web's
        const alt = state.md.renderer.renderInlineAsText(t.children ?? [], state.md.options, {});
        const text = new state.Token("text", "", 0);
        text.content = alt || src;
        // Not a link either inside a link (a badge in a link): the text only
        if (!EXTERNAL.test(src) || opened.some((o) => !o.hidden)) {
          out.push(text);
          continue;
        }
        const open = new state.Token("link_open", "a", 1);
        open.attrs = [
          ["href", src],
          ["target", "_blank"],
          ["rel", "noopener noreferrer"],
        ];
        out.push(open, text, new state.Token("link_close", "a", -1));
        continue;
      }
    }
    out.push(t);
  }
  return out;
}

/** Markdown to HTML that is safe to set as innerHTML. */
export function markdown(text: string): string {
  return md.render(text);
}

/** Draw the ```mermaid blocks in el as diagrams (Mermaid is loaded only for them; offline, or
 * if one can't be drawn, it stays as code). */
export async function diagrams(el: HTMLElement) {
  const blocks = [...el.querySelectorAll<HTMLElement>("pre > code.language-mermaid")];
  if (!blocks.length) return;
  const mod = await import("./mermaid").catch(() => null);
  await mod?.draw(blocks);
}

/** A link's path as a line to read: its words, not its escapes ("wiki / Integrated
 * information theory"), no trailing slash nor .html. */
function tidyPath(url: URL): string {
  const parts = decoded(url.pathname).replace(/\/+$/, "").split("/").filter(Boolean);
  const last = parts.pop()?.replace(/\.(html?|php|aspx?)$/i, "");
  // Its last part's words, when it is words joined by _ or - (not an id like 3f2a9c1e-4b7d)
  const words = last?.split(/[_-]+/);
  if (last && words && words.length > 1 && words.every((w) => /^(\p{L}+|\p{N}+)$/u.test(w)))
    parts.push(words.join(" "));
  else if (last) parts.push(last);
  return parts.join(" / ");
}

/** On a Later page: each paragraph that is only a link to the web, as a card that opens it,
 * its site over its path (or the link's own text, if it was given one) and an Open button.
 * The whole card is the link, so it is one tab stop; Open only says what tapping it does. */
export function cards(el: HTMLElement) {
  for (const p of el.querySelectorAll<HTMLParagraphElement>(":scope > p")) {
    const a = p.firstElementChild;
    const href = a?.getAttribute("href") ?? ""; // as written: a.href would make /p/x a URL
    const said = a?.textContent?.trim() ?? "";
    if (!(a instanceof HTMLAnchorElement) || p.children.length > 1 || a.children.length) continue;
    if (!/^https?:\/\//i.test(href) || p.textContent?.trim() !== said) continue;
    // Its own text, unless that is only the link again (a bare URL, <https://...>)
    const bare = [href, decoded(href)].some(
      (u) => u.replace(/\/$/, "") === said.replace(/\/$/, ""),
    );
    let url: URL;
    try {
      url = new URL(href);
    } catch {
      continue;
    }
    const text = (cls: string, s: string) =>
      Object.assign(document.createElement("span"), { className: cls, textContent: s });
    const open = text("button", "Open");
    open.prepend(icon("open"));
    const words = document.createElement("span");
    words.className = "words";
    words.append(text("site", url.hostname.replace(/^www\./, "")));
    const line = bare ? tidyPath(url) : said;
    if (line) words.append(text("path", line));
    a.className = "file linkcard";
    a.title = href;
    a.replaceChildren(words, open);
    p.replaceWith(a);
  }
}
