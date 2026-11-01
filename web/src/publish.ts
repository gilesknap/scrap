// A public page's HTML (#497): the publish mode beside Share as HTML (pagehtml.ts), as
// docs/reference/public-site.md "What the publish mode writes" has it. It reads the page's own
// view, as the export does, by allow-list, and writes what scrap's check accepts and nothing
// else: the fixed head (the meta CSP, /assets/page.css, /assets/katex.css for maths) and no
// <style>; maths as KaTeX's own markup; a Mermaid diagram as its source; images and files as
// scrap-blob:<sha> placeholders and tags as scrap-tag:<tag> chips, which scrap replaces; links
// to public pages live, to private ones their words. Claude's notes on a photo, drawings and a
// file's text read for search are left out. Pure: publicpages.ts gathers what it needs.
import { control, esc, KEEP, type N, type Swaps, textOf } from "./pagehtml";

/** What the page is published with, besides its view. */
export interface Context {
  title: string;
  tags: readonly string[]; // the page's, in order: its chips
  live: ReadonlySet<string>; // the public pages' slugs, this page's own too
  titles: ReadonlyMap<string, string>; // slug -> title, for a bare [[slug]] link
  origins: readonly string[]; // scrap's own (render.ts origins()): never linked
  site: string | null; // the public site's address (https://pages.example), for its name
  tex: ((tex: string, display: boolean) => string) | null; // KaTeX, for a page with maths
  date: string; // when it is published, for the footer
}

/** The meta CSP every public page carries (the contract's, exactly): no script at all. */
export const CSP =
  "default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; font-src 'self'";
/** A bare link to a private page whose title is not known (it is not there any more). */
export const PRIVATE = "a private page";

const TEXT = 3;
const ELEMENT = 1;
const ID = /^[a-z0-9_-]{1,80}$/;
const SLUG = /^[a-z0-9-]{1,120}$/;
const BLOB = /^\/api\/blobs\/([0-9a-f]{64})(?:[/?#].*)?$/;
const PAGE = /^\/p\/([^/?#]+)(?:[?#].*)?$/;
const FOOTNOTE_ID = /^fn(ref)?\d+(:\d+)?$/;
const HEADING = /^h[1-6]$/;

const el = (n: N) => n.nodeType === ELEMENT;
const tag = (n: N) => n.nodeName.toLowerCase();
const attr = (n: N, k: string) => n.getAttribute?.(k) ?? null;
const kids = (n: N) => Array.from(n.childNodes);
const classes = (n: N) => new Set((attr(n, "class") ?? "").split(/\s+/).filter(Boolean));
const has = (n: N, c: string) => classes(n).has(c);

/** Text that names a placeholder ("scrap-blob:", "scrap-tag:") would be refused anywhere but
 * a src or href: a word joiner after "scrap-" keeps it as it reads. */
const defuse = (s: string) => s.replace(/scrap-(blob|tag):/gi, "scrap-\u2060$1:");
const words = (s: string) => esc(defuse(s));

const decoded = (s: string) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** The first element under n (n too) that ok() takes. */
function find(n: N, ok: (n: N) => boolean): N | null {
  if (!el(n)) return null;
  if (ok(n)) return n;
  for (const k of kids(n)) {
    const got = find(k, ok);
    if (got) return got;
  }
  return null;
}

/** A link's words that only say where it goes: a bare [[slug]] (or [[slug#heading]]), or a
 * page's address written out. Its page's title is shown instead. */
export function bare(said: string, slug: string): boolean {
  const s = said.trim();
  if (s === slug || s.startsWith(`${slug}#`) || s === `/p/${slug}`) return true;
  return new RegExp(`^https?://[^/\\s]+/p/${slug}(?:[/?#].*)?$`, "i").test(s);
}

const hostOf = (o: string) => {
  try {
    return new URL(o).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }
};

/** Whether an address of the web may be linked from a public page: http or https, with no
 * user name, not one of scrap's own hosts, and not under /api/ anywhere. */
export function webLink(href: string, origins: readonly string[]): boolean {
  if (!/^https?:\/\//i.test(href)) return false;
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return false;
  }
  if (url.username || url.password || /^\/api\//i.test(url.pathname)) return false;
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  return !origins.some((o) => hostOf(o) === host);
}

/** The ids headings and footnotes keep: render.ts's where they fit the contract's
 * [a-z0-9_-]{1,80}, else a safe one in their place (a heading in other letters, a second
 * footnote reference's fnref1:1), each once. */
export function idsOf(root: N, swaps: Swaps): Map<string, string> {
  const found: string[] = [];
  const walk = (n: N) => {
    if (!el(n)) return;
    const id = attr(n, "id");
    if (id && (HEADING.test(tag(n)) || ["a", "li"].includes(tag(n)))) found.push(id);
    kids(swaps.get(n) ?? n).forEach(walk);
  };
  walk(root);
  const used = new Set(found.filter((id) => ID.test(id)));
  const out = new Map<string, string>();
  for (const id of found) {
    if (out.has(id)) continue;
    if (ID.test(id)) {
      out.set(id, id);
      continue;
    }
    const base =
      id
        .toLowerCase()
        .normalize("NFKD")
        .replace(/\p{M}+/gu, "") // é is e
        .replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 70) || "h";
    let safe = ID.test(base) && !used.has(base) ? base : "";
    for (let i = 1; !safe; i++) if (!used.has(`${base}-${i}`)) safe = `${base}-${i}`;
    used.add(safe);
    out.set(id, safe);
  }
  return out;
}

/** The page's view (the article on the screen) as its public HTML. */
export function publishHtml(root: N, ctx: Context, swaps: Swaps = new Map()): string {
  const ids = idsOf(root, swaps);
  let maths = false;
  let listed = false; // in Claude's Related, Topics or Sources: a private page's line goes

  const anchor = (href: string) => {
    const id = decoded(href.slice(1));
    return ids.get(id) ?? (ID.test(id) ? id : null);
  };

  const math = (n: N): string | null => {
    const t = tag(n);
    const code = t === "pre" && kids(n).filter(el);
    const block = code && code.length === 1 && tag(code[0]) === "code" ? code[0] : null;
    const isMath = (t === "span" || t === "div") && has(n, "math");
    if (!isMath && !(block && has(block, "language-math"))) return null;
    const tex = (block ? textOf(block) : (attr(n, "data-tex") ?? textOf(n))).trim();
    const display = !!block || t === "div" || has(n, "display");
    const box = t === "span" ? "span" : "div";
    const cls = display ? "math display" : "math";
    if (ctx.tex) {
      try {
        // (less KaTeX's class on a MathML cell of a numbered equation: the contract allows
        // class on HTML only, and the MathML half is not drawn)
        const out = ctx.tex(tex, display).replace(/<mtd class\s*="[^"]*">/g, "<mtd>");
        maths = true;
        return `<${box} class="${cls}">${out}</${box}>`;
      } catch {} // a formula KaTeX can't draw: its TeX, as the page shows it
    }
    const fence = display ? "$$" : "$";
    return box === "span"
      ? `<code class="math">${fence}${words(tex)}${fence}</code>`
      : `<pre class="math">${words(tex.startsWith("\\begin") ? tex : `$$\n${tex}\n$$`)}</pre>`;
  };

  /** An element's id as published: a heading's, or a footnote's a or li. */
  const idOf = (n: N, t: string) => {
    const own = attr(n, "id");
    const ok = own && (HEADING.test(t) || ((t === "a" || t === "li") && FOOTNOTE_ID.test(own)));
    const id = ok ? ids.get(own) : undefined;
    return id ? ` id="${id}"` : "";
  };

  const link = (n: N, inner: () => string): string => {
    const href = attr(n, "href") ?? "";
    const blob = BLOB.exec(href);
    if (blob) return `<a href="scrap-blob:${blob[1]}">${inner()}</a>`;
    const page = PAGE.exec(href);
    if (page) {
      const slug = decoded(page[1]);
      const said = textOf(n);
      const named = SLUG.test(slug) && bare(said, slug) ? ctx.titles.get(slug) : undefined;
      if (SLUG.test(slug) && ctx.live.has(slug))
        return `<a href="/p/${slug}">${named === undefined ? inner() : words(named)}</a>`;
      // A private page: its words only, a bare link its title, never its slug
      const plain = SLUG.test(slug) && bare(said, slug) ? words(named ?? PRIVATE) : inner();
      return `<span>${plain}</span>`;
    }
    if (href.startsWith("#")) {
      const id = anchor(href);
      return id ? `<a href="#${id}"${idOf(n, "a")}>${inner()}</a>` : inner();
    }
    if (/^mailto:/i.test(href) || webLink(href, ctx.origins))
      return `<a href="${esc(href)}">${inner()}</a>`;
    return inner(); // a screen of the app, or anywhere else: its words
  };

  const chips = () =>
    ctx.tags.length
      ? `<p class="tags">${ctx.tags
          .map((t) => `<a href="scrap-tag:${encodeURIComponent(t)}">#${words(t)}</a>`)
          .join("")}</p>`
      : "";

  const render = (n: N, shown = false): string => {
    if (n.nodeType === TEXT) return words(n.data ?? "");
    if (!el(n)) return "";
    const t = tag(n);
    const cls = classes(n);
    // A photo with Claude's notes and drawing: the photo alone; a file, its row alone
    if (cls.has("photo-panel")) {
      const fig = find(n, (k) => tag(k) === "figure" && has(k, "orig") && !has(k, "drawing"));
      return fig ? render(fig, true) : "";
    }
    if (cls.has("file-panel")) {
      const row = find(n, (k) => has(k, "filerow"));
      return row ? render(row) : "";
    }
    if (!shown && control(n)) return "";
    // The app's own: "by Claude", the topic's prompt, Public's own line, Claude's guidance
    if (
      ["notes", "written", "pubdate", "pubchip", "choice", "tabs"].some((c) => cls.has(c)) ||
      (cls.has("claude-text") && cls.has("sub"))
    )
      return "";
    if (t === "p" && cls.has("tags")) return chips();
    const m = math(n);
    if (m !== null) return m;
    if (cls.has("diagram")) {
      const src = attr(n, "data-source");
      return src ? `<pre><code class="language-mermaid">${words(src)}</code></pre>` : "";
    }
    const apart = t === "span" && cls.has("parts");
    const inner = () =>
      kids(swaps.get(n) ?? n)
        .map((k) => render(k))
        .filter((s) => !apart || s)
        .join(apart ? " · " : "");
    if (t === "input") {
      if (attr(n, "type") !== "checkbox") return "";
      return n.hasAttribute?.("checked") ? "[x] " : "[ ] ";
    }
    if (t === "img") {
      const sha = BLOB.exec(attr(n, "src") ?? "")?.[1];
      const alt = attr(n, "alt") ?? "";
      if (!sha) return `<em class="named">[${words(alt.trim() || "image")}]</em>`;
      return `<img src="scrap-blob:${sha}" alt="${words(alt)}">`;
    }
    if (t === "a") return link(n, inner);
    // Claude's lists of pages: a line to a private page goes, title and all
    if (t === "li" && listed) {
      const a = find(n, (k) => tag(k) === "a" && PAGE.test(attr(k, "href") ?? ""));
      const slug = a && decoded(PAGE.exec(attr(a, "href") ?? "")?.[1] ?? "");
      if (!slug || !ctx.live.has(slug)) return "";
    }
    if (t === "details" && (cls.has("related") || cls.has("sources"))) {
      const was = listed;
      listed = true;
      const out = element(n, t, inner);
      listed = was;
      return out.includes("<li") ? out : ""; // none of them public: the fold goes
    }
    if (cls.has("enrich")) {
      const out = element(n, t, inner);
      return out.includes("<details") ? out : ""; // Claude's card with nothing left in it
    }
    return element(n, t, inner);
  };

  const element = (n: N, t: string, inner: () => string): string => {
    if (!KEEP.has(t)) return inner(); // unknown markup: its text stays
    if (["br", "hr"].includes(t)) return `<${t}>`;
    const parts: [string, string | null | undefined][] = [
      ["class", attr(n, "class")],
      ["dir", attr(n, "dir")],
    ];
    if (t === "td" || t === "th")
      for (const k of ["colspan", "rowspan"]) {
        const v = attr(n, k);
        if (v && /^\d{1,3}$/.test(v)) parts.push([k, v]);
      }
    const open = parts
      .filter(([, v]) => v)
      .map(([k, v]) => ` ${k}="${esc(v as string)}"`)
      .join("");
    const out = t === "p" && swaps.has(n) ? "div" : t; // a paragraph holding Markdown
    return `<${out}${idOf(n, t)}${open}${t === "details" ? " open" : ""}>${inner()}</${out}>`;
  };

  const body = render(root);
  // The site's home is / (its name, the site's host, or Pages as its own pages say)
  const host = ctx.site ? (hostOf(ctx.site) ?? "Pages") : "Pages";
  const top = `<div class="site top"><a href="/">${esc(host)}</a></div>`;
  const foot = `<div class="site foot">Published ${esc(ctx.date)} from scrap · <a href="/">All pages</a></div>`;
  const css = [...(maths ? ["/assets/katex.css"] : []), "/assets/page.css"]
    .map((href) => `<link rel="stylesheet" href="${href}">`)
    .join("\n");
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${CSP}">
<title>${words(ctx.title)}</title>
${css}
</head>
<body>${top}${body}${foot}</body></html>
`;
}

/** Whether the view has maths to draw (KaTeX is loaded only then). */
export function hasMaths(root: N): boolean {
  return !!find(
    root,
    (n) => has(n, "math") || (tag(n) === "code" && has(n, "language-math")) || has(n, "math-error"),
  );
}

/** The pages a bare link names ([[slug]], an address written out): their titles are shown. */
export function bareSlugs(root: N, swaps: Swaps = new Map()): string[] {
  const out = new Set<string>();
  const walk = (n: N) => {
    if (!el(n)) return;
    const page = tag(n) === "a" && PAGE.exec(attr(n, "href") ?? "");
    const slug = page && decoded(page[1]);
    if (slug && SLUG.test(slug) && bare(textOf(n), slug)) out.add(slug);
    kids(swaps.get(n) ?? n).forEach(walk);
  };
  walk(root);
  return [...out];
}
