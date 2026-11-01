// The contract's check of a public page (docs/reference/public-site.md, "The HTML scrap
// accepts"), as a test's stand-in for scrap's own (Python, html5lib): the publish mode's output
// must pass it. Returns the problems found, none for a page scrap would take.
import { type El, parse, type T } from "./htmlparse";

export const CSP =
  "default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; font-src 'self'; script-src 'self'";
const PAIR = /^pair-[0-9]{1,3}(-photo|-drawing)?$/;
const TASKBOX: Record<string, string> = { taskbox: "To do", "taskbox done": "Done" };
const DRAWING = /^scrap-drawing:[1-9][0-9]{0,17}$/;
const DIAGRAM = /^scrap-diagram:[1-9][0-9]{0,2}-(light|dark)$/;
const EXCALIDRAW = /^scrap-excalidraw:[1-9][0-9]{0,17}$/;
const ICON_LINKS = [
  [
    ["href", "/assets/icon.svg"],
    ["rel", "icon"],
    ["type", "image/svg+xml"],
  ],
  [
    ["href", "/assets/icon-192.png"],
    ["rel", "apple-touch-icon"],
  ],
].map((a) => JSON.stringify(a));

const KEPT = new Set(
  "a abbr article aside b blockquote br caption code dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img ins kbd li mark ol p pre q s section small span strong sub summary sup table tbody td tfoot th thead time tr u ul input label".split(
    " ",
  ),
);
const MATHML = new Set(
  "math semantics annotation mrow mi mn mo mtext mspace msup msub msubsup mfrac msqrt mroot mover munder munderover mtable mtr mtd mstyle mpadded mphantom menclose".split(
    " ",
  ),
);
const SVG = new Set(["svg", "path", "line"]);
const MATHML_ATTRS = new Set(
  "display encoding accent accentunder columnalign columnlines columnspacing rowlines rowspacing depth voffset lspace rspace width height displaystyle scriptlevel mathsize mathvariant mathcolor mathbackground linethickness fence stretchy separator largeop minsize maxsize linebreak notation".split(
    " ",
  ),
);
const LENGTH = /^-?([0-9]+|[0-9]*\.[0-9]+)(em|ex|px)?$/;
const COLOUR = /^(#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})|rgba?\([0-9.%,\s]+\)|[a-z]+)$/i;
const STYLE: Record<string, (v: string, el: string) => boolean> = {};
for (const p of "height width min-width vertical-align top bottom left margin-left margin-right margin-top padding-left border-width border-top-width border-right-width border-bottom-width".split(
  " ",
))
  STYLE[p] = (v) => LENGTH.test(v);
STYLE.margin = (v) => v.split(/\s+/).length <= 2 && v.split(/\s+/).every((x) => LENGTH.test(x));
for (const p of ["color", "background-color", "border-color"]) STYLE[p] = (v) => COLOUR.test(v);
STYLE.border = (v, el) => {
  const [a, b, c] = v.split(/\s+/);
  return el === "mpadded" && LENGTH.test(a) && b === "solid" && COLOUR.test(c ?? "");
};
STYLE["border-style"] = STYLE["border-right-style"] = (v) => v === "solid" || v === "dashed";
STYLE.position = (v) => v === "relative";
STYLE["text-shadow"] = (v, el) =>
  ["span", "mstyle"].includes(el) && v.split(/\s+/).every((x) => LENGTH.test(x));

const PLACEHOLDER = /scrap-(blob|tag|drawing|excalidraw|diagram):/i;
const BLOB = /^scrap-blob:[0-9a-f]{64}$/;

/** Whether an a's href is one scrap takes: public is the public pages' slugs, own scrap's hosts. */
function hrefOk(href: string, live: ReadonlySet<string>, own: readonly string[]): boolean {
  if (BLOB.test(href) || /^scrap-tag:\S+$/.test(href)) return true;
  if (DRAWING.test(href) || EXCALIDRAW.test(href)) return true;
  if (/^mailto:/i.test(href) || /^#[a-z0-9_-]{1,80}$/.test(href)) return true;
  const page = /^\/p\/([a-z0-9-]{1,120})$/.exec(href);
  if (page) return live.has(page[1]);
  if (/^\/t\/[a-z0-9-]{1,80}$/.test(href) || href === "/" || href === "/tags") return true;
  if (!/^https?:\/\/[^/\\]/i.test(href)) return false;
  const url = new URL(href);
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  return !url.username && !url.password && !url.pathname.startsWith("/api/") && !own.includes(host);
}

/** The problems scrap's check would refuse the page for. */
export function check(html: string, live: ReadonlySet<string>, own: readonly string[] = []) {
  const bad: string[] = [];
  if (!/^<!DOCTYPE html>/i.test(html)) bad.push("no doctype");
  const root = parse(html);
  const kids = (n: El) => n.childNodes.filter((k) => k.nodeType === 1) as El[];
  const name = (n: El) => n.nodeName.toLowerCase();
  const [doc] = kids(root);
  if (!doc || name(doc) !== "html") return ["no html element"];
  const [head, body, ...more] = kids(doc);
  if (name(head) !== "head" || name(body) !== "body" || more.length) bad.push("not head, body");
  for (const n of [doc, head, body])
    for (const [k] of n.attrs) if (!["lang", "dir"].includes(k)) bad.push(`${name(n)}@${k}`);
  let csp = false;
  const icons = new Set<string>();
  for (const n of kids(head)) {
    const a = (k: string) => n.getAttribute?.(k) ?? null;
    if (name(n) === "meta" && n.attrs.length === 1 && a("charset")?.toLowerCase() === "utf-8")
      continue;
    if (name(n) === "meta" && a("name") === "viewport" && n.attrs.length === 2) continue;
    if (name(n) === "meta" && a("http-equiv") === "Content-Security-Policy") {
      csp = (a("content") ?? "").replace(/\s+/g, " ").trim() === CSP;
      if (!csp) bad.push("a different CSP");
      continue;
    }
    if (name(n) === "title") continue;
    // the one script: prefs.js, deferred (or async), render-blocking if it likes
    if (name(n) === "script") {
      const keys = n.attrs.map(([k]) => k).sort();
      const ok =
        a("src") === "/assets/prefs.js" &&
        n.childNodes.every((k) => k.nodeType === 3 && !(k as T).data) &&
        ["async", "defer"].filter((k) => keys.includes(k)).length === 1 &&
        keys.every((k) => ["src", "async", "defer", "blocking"].includes(k)) &&
        (a("blocking") ?? "render") === "render";
      if (ok) continue;
    }
    const href = a("href") ?? "";
    if (
      name(n) === "link" &&
      a("rel") === "stylesheet" &&
      /^\/assets\/(page|katex)\.css$/.test(href)
    )
      continue;
    // the site's two icons (#527), exactly so
    const attrs = JSON.stringify([...n.attrs].sort());
    if (name(n) === "link" && ICON_LINKS.includes(attrs)) {
      if (icons.has(attrs)) bad.push("in head: an icon link twice");
      icons.add(attrs);
      continue;
    }
    bad.push(`in head: <${name(n)}>`);
  }
  if (!csp) bad.push("no CSP");

  const walk = (n: El, katex: boolean, space: "html" | "math" | "svg") => {
    const t = name(n);
    const cls = (n.getAttribute?.("class") ?? "").split(/\s+/);
    let ns = space;
    if (t === "math") ns = "math";
    if (t === "svg") ns = "svg";
    const ok =
      ns === "html"
        ? KEPT.has(t)
        : katex &&
          (ns === "math" ? MATHML.has(t) : SVG.has(t) && !(t === "svg" && space !== "html"));
    if (!ok) bad.push(`element <${t}>`);
    if (t === "input" && n.getAttribute?.("type") !== "radio") bad.push("an input not a radio");
    // A task's box (#539): exactly the publish mode's empty span, its label by its state
    const box = t === "span" && (n.getAttribute?.("role") != null || cls.includes("taskbox"));
    if (box) {
      const label = TASKBOX[n.getAttribute?.("class") ?? ""];
      const attrs = n.attrs.map(([k, v]) => `${k}=${v}`).join(" ");
      if (!label || attrs !== `class=${n.getAttribute?.("class")} role=img aria-label=${label}`)
        bad.push(`a task box ${attrs}`);
      if (n.childNodes?.length) bad.push("a task box with content");
    }
    const inKatex = katex || (t === "span" && cls.includes("katex"));
    const seen = new Set<string>();
    for (const [k, v] of n.attrs) {
      if (seen.has(k)) bad.push(`<${t}> has ${k} twice`);
      seen.add(k);
      if (PLACEHOLDER.test(v) && !((t === "img" && k === "src") || (t === "a" && k === "href")))
        bad.push(`a placeholder in ${t}@${k}`);
      const fine = (() => {
        if (ns === "html" && (k === "class" || k === "dir")) return true;
        if (k === "id" && t === "input") return PAIR.test(v);
        if (k === "id")
          return (/^h[1-6]$/.test(t) || t === "a" || t === "li") && /^[a-z0-9_-]{1,80}$/.test(v);
        if (k === "colspan" || k === "rowspan")
          return ["td", "th"].includes(t) && /^\d{1,3}$/.test(v);
        if (k === "open") return t === "details" && v === "";
        if (k === "alt") return t === "img";
        if (k === "src") {
          // a diagram's image (#525) is classed as its theme
          const theme = DIAGRAM.exec(v)?.[1];
          if (theme) return t === "img" && n.getAttribute?.("class") === theme;
          return t === "img" && (BLOB.test(v) || DRAWING.test(v));
        }
        const href = n.getAttribute?.("href") ?? "";
        if (k === "download") return t === "a" && v === "" && DRAWING.test(href);
        if (k === "target") return t === "a" && v === "_blank" && EXCALIDRAW.test(href);
        if (k === "rel") return t === "a" && v === "noopener noreferrer" && EXCALIDRAW.test(href);
        if (t === "input")
          return (
            (k === "type" && v === "radio") ||
            ((k === "name" || k === "id") && PAIR.test(v)) ||
            (k === "checked" && v === "") ||
            k === "aria-label"
          );
        if (box) return true; // checked whole, above
        if (t === "label") return k === "for" && PAIR.test(v);
        if (t === "div" && k === "role") return v === "radiogroup";
        if (t === "div" && k === "aria-label") return true;
        if (k === "href") return t === "a" && hrefOk(v, live, own);
        if (k === "aria-hidden") return t === "span" && inKatex && v === "true";
        if (k === "style") {
          if (!inKatex || !["span", "mstyle", "mpadded", "svg"].includes(t)) return false;
          return v
            .split(";")
            .map((d) => d.trim())
            .filter(Boolean)
            .every((d) => {
              const [p, ...rest] = d.split(":");
              const check = STYLE[p.trim()];
              return !!check && check(rest.join(":").trim(), t);
            });
        }
        if (k === "xmlns")
          return (
            (t === "math" && v === "http://www.w3.org/1998/Math/MathML") ||
            (t === "svg" && v === "http://www.w3.org/2000/svg")
          );
        if (t === "svg" && ["width", "height", "viewbox", "preserveaspectratio"].includes(k))
          return !v.includes("url(");
        if (t === "path") return k === "d";
        if (t === "line") return ["x1", "y1", "x2", "y2", "stroke-width"].includes(k);
        if (ns === "math") return MATHML_ATTRS.has(k) && !v.includes("url(");
        return false;
      })();
      if (!fine) bad.push(`attribute ${t}@${k}="${v.slice(0, 40)}"`);
    }
    for (const k of n.childNodes) {
      if (k.nodeType === 3) {
        if (PLACEHOLDER.test((k as T).data ?? "")) bad.push("a placeholder in text");
      } else walk(k as El, inKatex, ns);
    }
  };
  for (const n of kids(body)) walk(n, false, "html");
  if (/<style[\s>]/i.test(html)) bad.push("a <style> element");
  return bad;
}
