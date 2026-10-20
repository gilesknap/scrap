// Page text as HTML: Markdown by markdown-it (a chunk of its own, kept for offline use), with
// GitHub's tables, task lists, ~~strikethrough~~, bare links and footnotes, plus [[slug]] and
// [[slug|label]] links to other pages. Raw HTML is shown as text; a line break stays one.
// Links are http(s), mailto, a page here or a heading of this page; images only this
// server's own files, each marked with its file's data-sha for the page to make a figure of.
// A ```mermaid block is drawn as a diagram, by Mermaid, a chunk of its own loaded only then.
// The server parses text the same way for search (src/scrap/markdown.py). The stored text is
// never changed.
import markdownit, { type StateCore, type StateInline, type Token } from "markdown-it";
import footnote from "markdown-it-footnote";

const IMAGE = /^\/api\/blobs\/([0-9a-f]{64})(\/preview\?size=(480|2048))?$/;
const EXTERNAL = /^(https?:\/\/|mailto:)/i;
const PAGE = /^\/p\/[a-z0-9-]+$/;
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

/** After parsing: safe links and images, heading ids, task list boxes. */
function tidy(state: StateCore) {
  const ids = new Map<string, number>();
  const tokens = state.tokens;
  tokens.forEach((t, i) => {
    if (t.type === "heading_open") {
      const text = tokens[i + 1]?.children?.map((c) => c.content).join("") ?? "";
      const id = anchor(text);
      const n = ids.get(id) ?? 0;
      ids.set(id, n + 1);
      t.attrSet("id", n ? `${id}-${n}` : id);
    }
    if (t.type !== "inline" || !t.children) return;
    if (tokens[i - 1]?.type === "paragraph_open" && tokens[i - 2]?.type === "list_item_open")
      task(t, tokens[i - 2], state);
    t.children = inline(t.children, state);
  });
}

/** A list item that starts [ ] or [x]: a box, ticked or not (it can't be ticked here). */
function task(t: Token, item: Token, state: StateCore) {
  const first = t.children?.[0];
  const m = first?.type === "text" && /^\[([ xX])\](?: |$)/.exec(first.content);
  if (!first || !m) return;
  first.content = first.content.slice(m[0].length);
  const box = new state.Token("html_inline", "", 0);
  box.content = `<input type="checkbox" disabled${m[1] === " " ? "" : " checked"}> `;
  t.children?.unshift(box);
  item.attrJoin("class", "task");
}

function inline(children: Token[], state: StateCore): Token[] {
  const out: Token[] = [];
  const opened: Token[] = []; // the open links: a close is dropped with its open
  for (const t of children) {
    if (t.type === "link_open") {
      const href = String(t.attrGet("href") ?? "");
      // A link in a link (a bare URL in a link's text): its text only
      if (opened.some((o) => !o.hidden)) t.hidden = true;
      else if (EXTERNAL.test(href)) {
        t.attrSet("target", "_blank");
        t.attrSet("rel", "noopener noreferrer");
      } else if (href.startsWith("#")) t.attrSet("href", `#${anchor(decoded(href.slice(1)))}`);
      else if (!t.meta?.wiki && !PAGE.test(href)) t.hidden = true; // its text stays
      opened.push(t);
    } else if (t.type === "link_close") {
      t.hidden = !!opened.pop()?.hidden;
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
        if (!EXTERNAL.test(src)) {
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
