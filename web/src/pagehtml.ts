// A page as one self-contained HTML file, for Share (a chunk of its own, with sharing.ts): the
// page as scrap shows it, labelled as the page labels it (this reads the page's own view, so
// the two can't drift), with nothing added. Built by allow-list: only the tags and attributes
// below survive, so no script, form, style, handler or address on this server comes along;
// photos are inlined as small previews up to a total, and anything else is named, not linked.

/** The part of a DOM node this reads (so it can be tested without a browser). */
export interface N {
  nodeType: number;
  nodeName: string;
  data?: string;
  childNodes: ArrayLike<N>;
  getAttribute?(name: string): string | null;
  hasAttribute?(name: string): boolean;
}

const TEXT = 3;
const ELEMENT = 1;
export const PREVIEW = 480; // pixels, longest side
export const CAP = 4 * 2 ** 20; // bytes of photos in one file, as base64

// Markup that keeps its look: the page's own text, headings, lists, tables, its Claude card
const KEEP = new Set(
  "a abbr article aside b blockquote br caption code dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q s section small span strong sub summary sup table tbody td tfoot th thead time tr u ul".split(
    " ",
  ),
);
// Left out with everything inside: controls, scripts and drawings of the app, not the page
const DROP = new Set(
  "audio button canvas dialog embed form iframe link menu meta nav noscript object script select style svg template textarea video".split(
    " ",
  ),
);
const SAFE_HREF = /^(https?:|mailto:|#)/i;
const SHA = /\/api\/blobs\/([0-9a-f]{64})/;

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const el = (n: N) => n.nodeType === ELEMENT;
const tag = (n: N) => n.nodeName.toLowerCase();
const attr = (n: N, k: string) => n.getAttribute?.(k) ?? null;
const kids = (n: N) => Array.from(n.childNodes);

/** Whether a node is one of the page's controls (a Download, an Ask), not its content. */
function control(n: N): boolean {
  // A prompt or where Claude is up to ("Waiting for Claude", "Claude can describe it..."),
  // which means nothing in a file
  const cls = ` ${attr(n, "class") ?? ""} `;
  return (
    DROP.has(tag(n)) ||
    n.hasAttribute?.("download") === true ||
    n.hasAttribute?.("hidden") === true ||
    / (tools|headend|bar|state|did|hint) /.test(cls)
  );
}

/** The page's images that are this server's own photos, in the order they come. */
export function photos(root: N): N[] {
  const out: N[] = [];
  const walk = (n: N) => {
    if (!el(n) || control(n)) return;
    if (tag(n) === "img" && SHA.test(attr(n, "src") ?? "")) out.push(n);
    kids(n).forEach(walk);
  };
  walk(root);
  return out;
}

/** The page's plain-text sections that hold Markdown: Claude's summary (a paragraph in the app,
 * as typed), and a body shown as typed while the renderer was not loaded. */
export function prose(root: N): N[] {
  const out: N[] = [];
  const walk = (n: N) => {
    if (!el(n) || control(n)) return;
    const cls = ` ${attr(n, "class") ?? ""} `;
    if (
      (tag(n) === "p" && cls.includes(" summary ")) ||
      (tag(n) === "div" && cls.includes(" raw "))
    )
      out.push(n);
    else kids(n).forEach(walk);
  };
  walk(root);
  return out;
}

/** What a section's text is (the lines the page shows, links as their words). */
export const textOf = (n: N): string =>
  n.nodeType === TEXT ? (n.data ?? "") : tag(n) === "br" ? "\n" : kids(n).map(textOf).join("");

const previewOf = (src: string) =>
  `${src.replace(/[?#].*/, "").replace(/\/preview$/, "")}/preview?size=${PREVIEW}`;

const asData = (blob: Blob): Promise<string> =>
  new Promise((ok, no) => {
    const r = new FileReader();
    r.onload = () => ok(r.result as string);
    r.onerror = () => no(r.error);
    r.readAsDataURL(blob);
  });

/** Each photo's preview as a data: address, in order, until the cap is reached; the rest, and
 * any that can't be fetched, are null (they are named in the file instead). */
export async function inline(
  imgs: N[],
  get: (url: string) => Promise<Blob | null>,
  read: (b: Blob) => Promise<string> = asData,
  cap = CAP,
): Promise<Map<N, string | null>> {
  const out = new Map<N, string | null>();
  let total = 0;
  for (const img of imgs) {
    if (total >= cap) {
      out.set(img, null); // the file is full: no more fetching
      continue;
    }
    const blob = await get(previewOf(attr(img, "src") ?? "")).catch(() => null);
    const url = blob && blob.type === "image/jpeg" ? await read(blob) : null;
    if (url && total + url.length <= cap) {
      total += url.length;
      out.set(img, url);
    } else out.set(img, null);
  }
  return out;
}

/** The photo's name for the file: its alt text, else a plain word. */
const named = (n: N) => (attr(n, "alt") || "").trim() || "photo";

/** A section that was text, as the elements its Markdown makes (by node, from prose()). */
type Swaps = Map<N, N>;

function render(n: N, shown: Map<N, string | null>, swaps: Swaps = new Map()): string {
  if (n.nodeType === TEXT) return esc(n.data ?? "");
  if (!el(n) || control(n)) return "";
  const t = tag(n);
  const inner = () =>
    kids(swaps.get(n) ?? n)
      .map((k) => render(k, shown, swaps))
      .join("");
  if (t === "input") {
    // A task box (render.ts): its state as text, as the page shows it
    if (attr(n, "type") !== "checkbox") return "";
    return n.hasAttribute?.("checked") ? "[x] " : "[ ] ";
  }
  if (t === "img") {
    const url = shown.get(n);
    // A photo past the cap (or one that is not this server's): named, with no address
    if (!url) return `<em class="named">[${esc(named(n))}]</em>`;
    return `<img src="${url}" alt="${esc(named(n))}">`;
  }
  if (t === "a") {
    const href = attr(n, "href") ?? "";
    // A link to a page or file of this server goes nowhere from a file: its words only
    if (!SAFE_HREF.test(href)) return inner();
    return `<a href="${esc(href)}">${inner()}</a>`;
  }
  if (!KEEP.has(t)) return inner(); // unknown markup: its text stays
  const parts = [
    ["class", attr(n, "class")],
    ["dir", attr(n, "dir")],
  ] as const;
  const open = parts
    .filter(([, v]) => v)
    .map(([k, v]) => ` ${k}="${esc(v as string)}"`)
    .join("");
  const cell = ["td", "th"].includes(t) ? ["colspan", "rowspan"].map((k) => [k, attr(n, k)]) : [];
  const spans = cell
    .filter(([, v]) => v && /^\d{1,3}$/.test(v))
    .map(([k, v]) => ` ${k}="${v}"`)
    .join("");
  // <details> stays open: a file has nothing to tap
  const opens = t === "details" ? " open" : "";
  if (["br", "hr"].includes(t)) return `<${t}>`;
  // (a paragraph holding Markdown becomes a div: its own paragraphs go inside)
  const out = t === "p" && swaps.has(n) ? "div" : t;
  return `<${out}${open}${spans}${opens}>${inner()}</${out}>`;
}

// Light, plain, prints well; no web fonts, nothing fetched
const STYLE = `body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:1.5rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}
h1{font-size:1.6rem;line-height:1.25}img{max-width:100%;height:auto}pre,code{font-family:ui-monospace,monospace;background:#f3f3f3}
pre{padding:.6rem;overflow-x:auto;white-space:pre-wrap}blockquote{margin-left:0;padding-left:1rem;border-left:3px solid #ccc;color:#444}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .5rem}a{color:#0b57d0}
.claude{margin-top:1.5rem;padding:.75rem 1rem;border:1px solid #d8d8d8;border-radius:8px;background:#f7f7f7}
.claude summary{font-weight:600}.named{color:#555}small{color:#555}
@media print{body{max-width:none;margin:0}a{color:inherit}details>summary{break-after:avoid}img{break-inside:avoid}}`;

/** The page's view as one HTML file's text. */
export function pageHtml(
  root: N,
  title: string,
  shown: Map<N, string | null>,
  swaps: Swaps = new Map(),
): string {
  return `<!doctype html>\n<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>${esc(title)}</title><style>${STYLE}</style></head>
<body>${render(root, shown, swaps)}</body></html>\n`;
}

/** A file name for the page's HTML. */
export const htmlName = (title: string) =>
  `${
    title
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "page"
  }.html`;

/** Make the page's HTML file from the page's view (the article on the screen). */
export async function makeHtml(root: HTMLElement, title: string, fetcher = fetch): Promise<File> {
  const get = async (url: string) => {
    const r = await fetcher(url);
    return r.ok ? r.blob() : null;
  };
  const shown = await inline(photos(root), get);
  // Text sections that hold Markdown (Claude's summary) are rendered here, by the app's own
  // renderer, whatever state the screen's DOM is in: raw text would be a file of **marks**
  const swaps: Swaps = new Map();
  const texts = prose(root);
  if (texts.length) {
    const md = await import("./render").catch(() => null);
    if (!md) throw new Error("the page can't be made offline until scrap is reloaded");
    for (const n of texts) {
      const box = document.createElement("div");
      box.innerHTML = md.markdown(textOf(n));
      swaps.set(n, box);
    }
  }
  return new File([pageHtml(root, title, shown, swaps)], htmlName(title), { type: "text/html" });
}
