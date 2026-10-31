import { readFileSync } from "node:fs";
import katex from "katex";
import { describe, expect, it } from "vitest";
import { type N, pageHtml } from "../src/pagehtml";
import { markdown as marked } from "../src/render";
import { OFFLINE } from "../vite.config";

const markdown = (s: string) => marked(s).replace(/ data-at="\d+,\d+"/g, "");
const one = (s: string) => markdown(s).trim();
// The same cases tests/test_markdown_math.py holds the server's parser (maths.py) to
const CASES = JSON.parse(readFileSync("../tests/maths_cases.json", "utf8")).cases as [
  string,
  [string, string][],
][];

describe("maths in page text", () => {
  it("takes $...$ inline and $$...$$ inline as display", () => {
    expect(one("so $x^2$ is")).toBe('<p>so <span class="math">x^2</span> is</p>');
    expect(one("$x$ is 5")).toBe('<p><span class="math">x</span> is 5</p>');
    expect(one("a $$\\frac{1}{2}$$ b")).toBe(
      '<p>a <span class="math display">\\frac{1}{2}</span> b</p>',
    );
  });

  it("takes $$ blocks, a top-level amsmath environment, and leaves ```math as code", () => {
    expect(one("$$\na_1 = b\n$$")).toBe('<div class="math display">a_1 = b</div>');
    expect(one("$$x$$")).toBe('<div class="math display">x</div>');
    expect(marked("$$\nx\n$$")).toBe('<div class="math display" data-at="0,3">x</div>\n');
    expect(one("\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}")).toBe(
      '<div class="math display">\\begin{align}\na &amp;= b \\\\\nc &amp;= d\n\\end{align}</div>',
    );
    expect(one("```math\n\\begin{aligned} a &= b \\end{aligned}\n```")).toBe(
      '<pre><code class="language-math">\\begin{aligned} a &amp;= b \\end{aligned}\n</code></pre>',
    );
  });

  it("finds the maths the server finds (tests/maths_cases.json)", () => {
    const kinds: Record<string, string> = {
      'span class="math"': "inline",
      'span class="math display"': "double",
      'div class="math display"': "block",
    };
    const unhtml = (s: string) =>
      s
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&");
    for (const [text, found] of CASES) {
      const html = markdown(text);
      const got = [...html.matchAll(/<((?:span|div) class="math[^"]*")>([^<]*)<\/(?:span|div)>/g)];
      expect(
        got.map((m) => [kinds[m[1]], unhtml(m[2]).trim()]),
        text,
      ).toEqual(found);
      if (!found.length) expect(html, text).not.toContain("math");
    }
    // [[...]] in a formula is no link; one beside it is
    expect(one("$[[c]]$ [[real]]")).toBe(
      '<p><span class="math">[[c]]</span> <a href="/p/real">real</a></p>',
    );
    expect(one("$5 and $10")).toBe("<p>$5 and $10</p>");
  });

  it("escapes HTML in a formula", () => {
    expect(one("$a<b>c$")).toBe('<p><span class="math">a&lt;b&gt;c</span></p>');
  });

  it("is TeX KaTeX can draw, and KaTeX throws on a mistake (math.ts leaves its TeX)", () => {
    const opts = { throwOnError: true, trust: false, displayMode: true };
    expect(
      katex.renderToString("\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}", opts),
    ).toContain("katex-display");
    expect(() => katex.renderToString("\\frac{1}{", opts)).toThrow();
    // trust: false: no links from a formula
    expect(
      katex.renderToString("\\href{https://e.com}{x}", { ...opts, throwOnError: false }),
    ).not.toContain("<a ");
  });

  it("keeps the KaTeX chunk for offline use", () => {
    expect(OFFLINE).toContain("math");
  });
});

describe("Share's file", () => {
  const t = (data: string): N => ({ nodeType: 3, nodeName: "#text", data, childNodes: [] });
  const e = (name: string, attrs: Record<string, string>, ...kids: N[]): N => ({
    nodeType: 1,
    nodeName: name.toUpperCase(),
    childNodes: kids,
    getAttribute: (k) => attrs[k] ?? null,
    hasAttribute: (k) => k in attrs,
  });

  it("has a formula's TeX, not KaTeX's markup", () => {
    const drawn = e(
      "span",
      { class: "math", "data-tex": "a<b" },
      e("span", { class: "katex" }, e("math", {}, t("a<b")), e("span", {}, t("a<b"))),
    );
    const display = e("div", { class: "math display", "data-tex": "x^2" }, t("x2"));
    const ams = e("div", { class: "math display" }, t("\\begin{align}a\\end{align}"));
    const html = pageHtml(e("p", {}, t("so "), drawn, display, ams), "T", new Map());
    expect(html).toContain('<p>so <code class="math">$a&lt;b$</code>');
    expect(html).toContain('<pre class="math">$$\nx^2\n$$</pre>');
    expect(html).toContain('<pre class="math">\\begin{align}a\\end{align}</pre>');
    expect(html).not.toContain("katex");
  });
});
