// A small HTML parser for the unit tests (they run in node, with no DOM): well-formed markup,
// as render.ts, KaTeX and the publish mode write it, into pagehtml.ts's node shape (N), with
// each element's attributes and parent kept for the checks.
import type { N } from "../src/pagehtml";

export interface El extends N {
  attrs: [string, string][];
  parent: El | null;
  childNodes: (El | T)[];
}
export interface T extends N {
  parent: El | null;
}

const VOID = new Set("area base br col embed hr img input link meta source track wbr".split(" "));
const RAW = new Set(["script", "style", "textarea", "title"]);
const NAMED: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

const decode = (s: string) =>
  s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e: string) => {
    if (e[0] === "#")
      return String.fromCodePoint(
        e[1].toLowerCase() === "x" ? Number.parseInt(e.slice(2), 16) : Number(e.slice(1)),
      );
    return NAMED[e] ?? m;
  });

function element(name: string, attrs: [string, string][], parent: El | null): El {
  return {
    nodeType: 1,
    nodeName: name.toUpperCase(),
    attrs,
    parent,
    childNodes: [],
    getAttribute: (k) => attrs.find(([a]) => a === k)?.[1] ?? null,
    hasAttribute: (k) => attrs.some(([a]) => a === k),
  };
}
const text = (data: string, parent: El | null): T => ({
  nodeType: 3,
  nodeName: "#text",
  data,
  childNodes: [],
  parent,
});

/** Parse markup into a root element (#root) holding what it makes; the doctype and comments
 * are left out. */
export function parse(html: string): El {
  const root = element("#root", [], null);
  let at = root;
  let i = 0;
  const add = (n: El | T) => at.childNodes.push(n);
  while (i < html.length) {
    if (html.startsWith("<!--", i)) {
      i = html.indexOf("-->", i) + 3;
      continue;
    }
    if (html.startsWith("<!", i)) {
      i = html.indexOf(">", i) + 1;
      continue;
    }
    if (html.startsWith("</", i)) {
      const end = html.indexOf(">", i);
      const name = html
        .slice(i + 2, end)
        .trim()
        .toLowerCase();
      let n: El | null = at;
      while (n && n.nodeName.toLowerCase() !== name) n = n.parent;
      if (!n) throw new Error(`</${name}> closes nothing at ${i}`);
      at = n.parent ?? root;
      i = end + 1;
      continue;
    }
    if (html[i] === "<" && /[a-zA-Z]/.test(html[i + 1] ?? "")) {
      const m = /^<([a-zA-Z][\w-]*)/.exec(html.slice(i)) as RegExpExecArray;
      const name = m[1].toLowerCase();
      i += m[0].length;
      const attrs: [string, string][] = [];
      const ATTR = /^\s*([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/;
      for (;;) {
        const rest = html.slice(i);
        const close = /^\s*(\/?)>/.exec(rest);
        if (close) {
          i += close[0].length;
          const el = element(name, attrs, at);
          add(el);
          if (RAW.has(name)) {
            const end = html.toLowerCase().indexOf(`</${name}`, i);
            el.childNodes.push(text(decode(html.slice(i, end)), el));
            i = html.indexOf(">", end) + 1;
          } else if (!close[1] && !VOID.has(name)) at = el;
          break;
        }
        const a = ATTR.exec(rest);
        if (!a) throw new Error(`bad attribute at ${i}: ${rest.slice(0, 20)}`);
        attrs.push([a[1].toLowerCase(), decode(a[2] ?? a[3] ?? a[4] ?? "")]);
        i += a[0].length;
      }
      continue;
    }
    const next = html.indexOf("<", i + 1);
    const end = next < 0 ? html.length : next;
    add(text(decode(html.slice(i, end)), at));
    i = end;
  }
  return root;
}

/** The first element under n with this name and class (any, if not given). */
export function first(n: El, name: string, cls?: string): El | null {
  for (const k of n.childNodes) {
    if (k.nodeType !== 1) continue;
    const e = k as El;
    const classes = (e.getAttribute?.("class") ?? "").split(/\s+/);
    if (e.nodeName.toLowerCase() === name && (!cls || classes.includes(cls))) return e;
    const got = first(e, name, cls);
    if (got) return got;
  }
  return null;
}
