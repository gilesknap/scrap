// A public page's HTML (#497): the publish mode beside Share as HTML (pagehtml.ts), as
// docs/reference/public-site.md "What the publish mode writes" has it. It reads the page's own
// view, as the export does, by allow-list, and writes what scrap's check accepts and nothing
// else: the fixed head (the meta CSP, /assets/page.css, /assets/katex.css for maths) and no
// <style>; maths as KaTeX's own markup; a Mermaid diagram (#525), once publicpages.ts has drawn
// it, as two images, its light and its dark drawing as scrap-diagram:<n>-light and -dark
// placeholders, one shown by the page's theme (page.css, no script), else as its source; a code
// block's text as written, only scrap's own addresses in it hidden (#529); images and files as
// scrap-blob:<sha> placeholders and tags as scrap-tag:<tag> chips, which scrap replaces; links
// to public pages live, to private ones their words. A photo's drawing (#520), once
// publicpages.ts has drawn it, beside the photo with Photo | Drawing tabs (radio inputs and
// CSS, no script) and its links to open it on excalidraw.com and to download it, as
// scrap-drawing:<id> and scrap-excalidraw:<id> placeholders. Under a photo or file, Claude's
// reading of it (#521) in a fold, as the app has it, but published closed (every other fold
// is published open): a photo's description and text, a PDF's text (publicpages.ts fetches
// it), scrubbed as page text is. An image Claude made (add_svg) has none. Pure: publicpages.ts
// gathers what it needs. A task's box (#539) as an empty span, ticked or not, that page.css
// draws.
import { type Titles, titleOf } from "./linktext";
import { control, esc, KEEP, type N, type Swaps, textOf } from "./pagehtml";

/** What the page is published with, besides its view. */
export interface Context {
  title: string;
  tags: readonly string[]; // the page's, in order: its chips
  live: ReadonlySet<string>; // the public pages' slugs, this page's own too
  titles: Titles; // slug -> title, for a bare [[slug]] link (linktext.ts, as the app has it)
  origins: readonly string[]; // scrap's own (render.ts origins()): never linked
  site: string | null; // the public site's address (https://pages.example), for its name
  tex: ((tex: string, display: boolean) => string) | null; // KaTeX, for a page with maths
  date: string; // when it is published, for the footer
  drawn?: ReadonlySet<string>; // the drawings (by id) publicpages.ts drew: shown with their photos
  texts?: ReadonlyMap<string, string>; // a PDF's text (by sha) its fold shows: publicpages.ts's
  diagrams?: ReadonlyMap<string, DiagramKey>; // the diagrams publicpages.ts drew, by source
}

/** A diagram publicpages.ts drew (#525): its key, and the words drawn in it (its alt text). */
export interface DiagramKey {
  key: number;
  words: string;
}

/** The meta CSP every public page carries (the contract's, exactly): the site's own scripts
 * only, and the one it names is /assets/prefs.js, the theme and width switches (#519). */
const CSP =
  "default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; font-src 'self'; script-src 'self'";
/** The page's one script, from the head: deferred, and render-blocking where the browser
 * can, so a kept theme is on before the first paint (scrap's check allows only this). */
const PREFS = '<script src="/assets/prefs.js" defer blocking="render"></script>';
/** The reading fold's label, as the app's (reading.ts READING). */
const READING = "Claude's reading";
/** The site's icons, scrap's own (#527): the tab's and the home screen's (scrap's check allows
 * exactly these two links). */
const ICONS =
  '<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">\n<link rel="apple-touch-icon" href="/assets/icon-192.png">';
/** A bare link to a private page whose title is not known (it is not there any more). */
const PRIVATE = "a private page";

const TEXT = 3;
const ELEMENT = 1;
const ID = /^[a-z0-9_-]{1,80}$/;
const SLUG = /^[a-z0-9-]{1,120}$/;
const BLOB = /^\/api\/blobs\/([0-9a-f]{64})(?:[/?#].*)?$/;
const PAGE = /^\/p\/([^/?#]+)(?:[?#].*)?$/;
const FOOTNOTE_ID = /^fn(ref)?\d+(:\d+)?$/;
const HEADING = /^h[1-6]$/;
const DRAWING_ID = /^[1-9][0-9]{0,17}$/;

const el = (n: N) => n.nodeType === ELEMENT;
const tag = (n: N) => n.nodeName.toLowerCase();
const attr = (n: N, k: string) => n.getAttribute?.(k) ?? null;
const kids = (n: N) => Array.from(n.childNodes);
const classes = (n: N) => new Set((attr(n, "class") ?? "").split(/\s+/).filter(Boolean));
const has = (n: N, c: string) => classes(n).has(c);

/** Text that names a placeholder ("scrap-blob:", "scrap-tag:") would be refused anywhere but
 * a src or href: a word joiner after "scrap-" keeps it as it reads. */
const defuse = (s: string) =>
  s.replace(/scrap-(blob|tag|drawing|excalidraw|diagram):/gi, "scrap-\u2060$1:");
/** What text says in place of an address of scrap's own, or of its API. */
const PRIVATE_LINK = "a private link";
const reEscape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Addresses of scrap's own (its hosts, with or without a scheme) and of /api/, as text; in
 * code (#529), only its hosts' and /api/blobs/ (a stored file's), what scrap's check refuses:
 * an /api/ path in a code block or a diagram is the text's own, not a link. */
function privates(origins: readonly string[], code = false): RegExp {
  // the rest of an address: up to a space, not its last full stop, comma or bracket (in
  // code, nor a square one: Mermaid's B[address] keeps its bracket)
  const tail = `[^\\s<>"]*[^\\s<>".,;:!?)${code ? "\\]" : ""}]`;
  // each host as text may hide it: a zero-width character between its letters, a
  // full-width or ideographic dot for a dot (scrap's check reads past both)
  const zw = "[\\u200b-\\u200d\\u2060\\ufeff\\u00ad]*";
  const hosts = origins
    .map(hostOf)
    .filter((h): h is string => !!h)
    .map((h) => [...h].map((c) => (c === "." ? "[.\\u3002\\uff0e\\uff61]" : reEscape(c))).join(zw));
  const own = hosts.length
    ? `(?:(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://)?(?<![\\w.-])(?:${hosts.join("|")})(?![\\w-]|\\.[\\w-])\\.?(?::\\d+)?(?:[/?#]${tail})?|`
    : "";
  const blobs = `/api/blobs/(?:${tail})?`;
  const api = code
    ? blobs
    : `https?://[^\\s/<>"]*/api/(?:${tail})?|(?<![\\w.~/-])/api/(?:${tail})?|${blobs}`;
  return new RegExp(own + api, "gi");
}
/** Code's text as published (#529): only scrap's own addresses hidden. A diagram is drawn
 * from its source so (#525): Mermaid may split a long word across a label's lines. */
export const codeText = (s: string, origins: readonly string[]) =>
  s.replace(privates(origins, true), PRIVATE_LINK);
/** A tag as a scrap-tag: placeholder, every character but letters, digits and -_.~ escaped. */
const tagHref = (t: string) =>
  `scrap-tag:${encodeURIComponent(t).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)}`;

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
  // Text never names an address of scrap's own, or of its API (S3): it says "a private link"
  const hidden = privates(ctx.origins);
  const words = (s: string) => esc(defuse(s.replace(hidden, PRIVATE_LINK)));
  const hiddenInCode = privates(ctx.origins, true);
  const codeWords = (s: string) => esc(defuse(s.replace(hiddenInCode, PRIVATE_LINK)));
  let fenced = false; // in a code block: its text as written (#529)
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
      const named = SLUG.test(slug) && bare(said, slug) ? titleOf(slug, ctx.titles) : undefined;
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

  // A photo and its drawing, Photo | Drawing tabs over them (the drawing chosen, as in the
  // app), pure CSS (page.css): without it both show. Then its links: Open in Excalidraw (only
  // with the site's https address, which excalidraw.com fetches it from) and Download.
  let pairs = 0;
  const pair = (photo: string, id: string, name: string) => {
    const n = ++pairs;
    const tab = (which: "photo" | "drawing", label: string) =>
      `<input type="radio" name="pair-${n}" id="pair-${n}-${which}" class="tab-input"${
        which === "drawing" ? " checked" : ""
      }><label for="pair-${n}-${which}">${label}</label>`;
    const tabs = `<div class="tabs" role="radiogroup" aria-label="Show">${tab("photo", "Photo")}${tab("drawing", "Drawing")}</div>`;
    const drawing = `<figure class="drawing"><img src="scrap-drawing:${id}" alt="${words(`Drawing of ${name}`)}"></figure>`;
    const download = (said: string) => `<a href="scrap-drawing:${id}" download>${said}</a>`;
    const links = /^https:\/\//i.test(ctx.site ?? "")
      ? `<a href="scrap-excalidraw:${id}" target="_blank" rel="noopener noreferrer">Open in Excalidraw</a> · ${download("Download")}`
      : download("Download, then open in excalidraw.com to edit");
    return `<div class="pair">${tabs}${photo}${drawing}</div><p class="drawing-get">${links}</p>`;
  };

  // Claude's reading of a photo or file (#521): the app's fold, its words only, published
  // closed, so the page reads as the owner's (Pagefind indexes it all the same). None where the
  // app's has nothing read (Generate, a file's pages alone) or there is no fold (add_svg's).
  const reading = (panel: N, sha?: string): string => {
    const fold = find(panel, (k) => tag(k) === "details" && has(k, "reading-fold"));
    if (!fold) return "";
    const said = (k: N | null) => (k ? textOf(k).trim() : "");
    const desc = said(find(fold, (k) => tag(k) === "p" && has(k, "desc")));
    const read = said(find(fold, (k) => tag(k) === "pre" && !has(k, "filetext")));
    const file = find(fold, (k) => tag(k) === "pre" && has(k, "filetext"));
    const text = file && sha ? (ctx.texts?.get(sha)?.trim() ?? "") : read;
    if (!desc && !text) return "";
    const parts = (desc ? `<p>${words(desc)}</p>` : "") + (text ? `<pre>${words(text)}</pre>` : "");
    return `<details class="reading"><summary>${READING}</summary><div class="claude">${parts}</div></details>`;
  };

  const chips = () =>
    ctx.tags.length
      ? `<p class="tags">${ctx.tags
          .map((t) => `<a href="${tagHref(t)}">#${words(t)}</a>`)
          .join("")}</p>`
      : "";

  const render = (n: N, shown = false): string => {
    if (n.nodeType === TEXT) return (fenced ? codeWords : words)(n.data ?? "");
    if (!el(n)) return "";
    const t = tag(n);
    const cls = classes(n);
    // A photo with Claude's reading and drawing: the photo, and its drawing if drawn, then the
    // reading, folded; a file, its row and its reading
    if (cls.has("photo-panel")) {
      const fig = find(n, (k) => tag(k) === "figure" && has(k, "orig") && !has(k, "drawing"));
      if (!fig) return "";
      const d = find(n, (k) => tag(k) === "figure" && has(k, "drawing"));
      const id = d && attr(d, "data-drawing");
      if (!id || !DRAWING_ID.test(id) || !ctx.drawn?.has(id)) return render(fig, true) + reading(n);
      const alt = attr(find(fig, (k) => tag(k) === "img") ?? fig, "alt")?.trim();
      return pair(render(fig, true), id, alt || "the photo") + reading(n);
    }
    if (cls.has("file-panel")) {
      const row = find(n, (k) => has(k, "filerow"));
      if (!row) return "";
      const a = find(row, (k) => tag(k) === "a" && BLOB.test(attr(k, "href") ?? ""));
      return render(row) + reading(n, (a && BLOB.exec(attr(a, "href") ?? "")?.[1]) || undefined);
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
    // A diagram drawn for the page (#525): its two images, else its source as a code block
    const source = sourceOf(n);
    const drawn = source === null ? undefined : ctx.diagrams?.get(source);
    if (drawn !== undefined) {
      const alt = codeWords(drawn.words ? `Diagram: ${drawn.words}` : "Diagram");
      const img = (theme: string) =>
        `<img class="${theme}" src="scrap-diagram:${drawn.key}-${theme}" alt="${alt}">`;
      return `<figure class="diagram">${img("light")}${img("dark")}</figure>`;
    }
    if (cls.has("diagram")) {
      const src = attr(n, "data-source");
      return src ? `<pre><code class="language-mermaid">${codeWords(src)}</code></pre>` : "";
    }
    const apart = t === "span" && cls.has("parts");
    const inner = () =>
      kids(swaps.get(n) ?? n)
        .map((k) => render(k))
        .filter((s) => !apart || s)
        .join(apart ? " · " : "");
    // A task's box (render.ts, #539): no <input>, an empty span page.css draws as the app's
    // box, its state in its label
    if (t === "input") {
      if (attr(n, "type") !== "checkbox") return "";
      return n.hasAttribute?.("checked")
        ? '<span class="taskbox done" role="img" aria-label="Done"></span>'
        : '<span class="taskbox" role="img" aria-label="To do"></span>';
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
    const was = fenced;
    fenced ||= t === "pre";
    const within = inner();
    fenced = was;
    return `<${out}${idOf(n, t)}${open}${t === "details" ? " open" : ""}>${within}</${out}>`;
  };

  const body = render(root);
  // The site's home is / (its name, the site's host, or Pages as its own pages say)
  // (not a host of scrap's own: a site on scrap's host has its name, Pages, instead)
  const named = ctx.site ? hostOf(ctx.site) : null;
  const own = ctx.origins.map(hostOf);
  const host = named && !own.includes(named) ? named : "Pages";
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
${ICONS}
${PREFS}
</head>
<body>${top}${body}${foot}</body></html>
`;
}

/** The PDFs whose text the view's reading folds show (filecard.ts), each with its capture:
 * publicpages.ts fetches their text. */
export function fileTextsOf(root: N): { cid: string; sha: string }[] {
  const out: { cid: string; sha: string }[] = [];
  const walk = (n: N) => {
    if (!el(n)) return;
    const cid = tag(n) === "pre" && has(n, "filetext") ? attr(n, "data-cid") : null;
    const sha = attr(n, "data-sha");
    if (cid && sha && /^[0-9a-f]{64}$/.test(sha) && !out.some((f) => f.sha === sha))
      out.push({ cid, sha });
    kids(n).forEach(walk);
  };
  walk(root);
  return out;
}

/** The drawings on the view, each with the photo it is of: publicpages.ts draws them. */
export function drawingsOf(root: N): { id: string; cid: string; sha: string }[] {
  const out: { id: string; cid: string; sha: string }[] = [];
  const walk = (n: N) => {
    if (!el(n)) return;
    const id = tag(n) === "figure" && has(n, "drawing") ? attr(n, "data-drawing") : null;
    const cid = attr(n, "data-cid");
    const sha = attr(n, "data-sha");
    if (id && DRAWING_ID.test(id) && cid && sha && !out.some((d) => d.id === id))
      out.push({ id, cid, sha });
    kids(n).forEach(walk);
  };
  walk(root);
  return out;
}

/** A Mermaid diagram's source, if n is one: one the app drew, or a ```mermaid block it has not
 * drawn (yet: a view drawn off the screen, or one redrawn while it is published). */
function sourceOf(n: N): string | null {
  if (!el(n)) return null;
  if (has(n, "diagram")) return attr(n, "data-source") || null;
  const code = tag(n) === "pre" ? kids(n).filter(el) : [];
  if (code.length === 1 && tag(code[0]) === "code" && has(code[0], "language-mermaid"))
    return textOf(code[0]);
  return null;
}

/** The view's Mermaid diagrams (#525), each once, in order, by their sources: publicpages.ts
 * draws them for the page (keyed by source, as the view may be drawn again meanwhile); one it
 * cannot draw goes out as its source. */
export function diagramsOf(root: N): string[] {
  const out = new Set<string>();
  const walk = (n: N) => {
    if (!el(n)) return;
    const source = sourceOf(n);
    if (source !== null) out.add(source);
    else kids(n).forEach(walk);
  };
  walk(root);
  return [...out];
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
