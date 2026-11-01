import { afterEach, describe, expect, it, vi } from "vitest";
import { unembedded } from "../src/md";
import { markdown as marked, origins, own } from "../src/render";

const SHA = "a".repeat(64);
const a = (href: string, text = href) =>
  `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
// Each block marked with its lines (data-at, tested on its own below): taken out to compare
const markdown = (s: string) => marked(s).replace(/ data-at="\d+,\d+"/g, "");
const one = (s: string) => markdown(s).trim();

describe("markdown", () => {
  it("renders the basics, a line break staying one", () => {
    expect(markdown("# Title\n\nSome **bold** and *it* and _it_ and `x<y`")).toBe(
      '<h1 id="h-title">Title</h1>\n<p>Some <strong>bold</strong> and <em>it</em> and <em>it</em> and <code>x&lt;y</code></p>\n',
    );
    expect(one("line one\nline two\n\nnext")).toBe("<p>line one<br>\nline two</p>\n<p>next</p>");
    expect(one("> quoted\n> **more**\n\n---")).toBe(
      "<blockquote>\n<p>quoted<br>\n<strong>more</strong></p>\n</blockquote>\n<hr>",
    );
    expect(one("```\n<b>**not bold**</b>\n```")).toBe(
      "<pre><code>&lt;b&gt;**not bold**&lt;/b&gt;\n</code></pre>",
    );
  });

  it("marks each block with its lines in the text", () => {
    expect(marked("# T\n\none\ntwo\n\n- a\n- b\n\n```\nx\n```")).toBe(
      '<h1 data-at="0,1" id="h-t">T</h1>\n<p data-at="2,4">one<br>\ntwo</p>\n' +
        '<ul data-at="5,8">\n<li data-at="5,6">a</li>\n<li data-at="6,8">b</li>\n</ul>\n' +
        '<pre><code data-at="8,11">x\n</code></pre>\n',
    );
  });

  it("closes a fence only on a matching one", () => {
    expect(one("````\n```\n``` not a close\n````")).toBe(
      "<pre><code>```\n``` not a close\n</code></pre>",
    );
    expect(one("~~~\n```\n~~~\nafter")).toBe("<pre><code>```\n</code></pre>\n<p>after</p>");
  });

  it("renders GitHub's tables, task lists, strikethrough and footnotes", () => {
    const table = one("| a | b |\n|---|--:|\n| [[c]] | ~~d~~ |");
    expect(table).toMatch(/^<div class="table"><table>\n<thead>/);
    expect(table).toContain('<td><a href="/p/c">c</a></td>');
    expect(table).toContain('<td style="text-align:right"><s>d</s></td>');
    expect(table).toMatch(/<\/table><\/div>$/);
    expect(one("- [ ] todo\n- [x] done\n- [y] not a box")).toBe(
      '<ul>\n<li class="task"><label class="taskbox"><input type="checkbox" aria-label="todo" data-line="0" disabled></label> todo</li>\n' +
        '<li class="task"><label class="taskbox"><input type="checkbox" aria-label="done" data-line="1" disabled checked></label> done</li>\n' +
        "<li>[y] not a box</li>\n</ul>",
    );
    // Named by its item's text, escaped; the boxes the server counts (markdown.py tasks):
    // one with its text on the next line, not one escaped, a link named [x], or one not on
    // its item's first line
    expect(one('- [ ] *buy* `"milk"` & <eggs>')).toContain(
      'aria-label="buy &quot;milk&quot; &amp; &lt;eggs&gt;"',
    );
    expect(one("- [ ]\n  continued")).toContain('aria-label="continued"');
    expect(one("- [ ]")).toContain('aria-label="Task"');
    expect(one(`- [ ] ${"a".repeat(119)}😀b`)).toContain(`aria-label="${"a".repeat(119)}😀"`);
    const boxes = (text: string) => one(text).match(/type="checkbox"/g)?.length ?? 0;
    expect(boxes("- \\[ ] escaped")).toBe(0);
    expect(boxes("[x]: https://e.com\n\n- [x] ref")).toBe(0);
    expect(boxes("-\n  [ ] below its bullet\n- - [ ] an item in an item")).toBe(0);
    const notes = one("Said[^1].\n\n[^1]: The source.");
    expect(notes).toContain('<a href="#fn1" id="fnref1">[1]</a>');
    expect(notes).toContain('<li id="fn1" class="footnote-item"><p>The source.');
  });

  it("gives headings ids, and links to them", () => {
    const html = one("## Next steps!\n\n## Next steps\n\nSee [them](#next-steps)");
    expect(html).toContain('<h2 id="h-next-steps">');
    expect(html).toContain('<h2 id="h-next-steps-1">');
    expect(html).toContain('<a href="#h-next-steps">them</a>');
  });

  it("links to a heading with spaces, accents or quotes as it is typed", () => {
    const html = one(
      "# Café ünïcode\n\n## Two words\n\n[a](#café-ünïcode) [b](<#Two words>) [c](#100%)",
    );
    expect(html).toContain('<h1 id="h-café-ünïcode">');
    expect(html).toContain('<a href="#h-café-ünïcode">a</a>');
    expect(html).toContain('<a href="#h-two-words">b</a>');
    expect(html).toContain('<a href="#h-100">c</a>'); // a malformed % is no error
  });

  it("leaves a ```mermaid block as code, for the diagram chunk", () => {
    expect(one("```mermaid\ngraph TD; A-->B\n```")).toBe(
      '<pre><code class="language-mermaid">graph TD; A--&gt;B\n</code></pre>',
    );
  });

  it("nests code in links, and never a link in a link (#52)", () => {
    expect(one("[`code`](https://e.com)")).toBe(
      `<p>${a("https://e.com", "<code>code</code>")}</p>`,
    );
    const nested = /<a[^>]*>(?:(?!<\/a>).)*<a/s;
    for (const text of [
      "[see [[a|Label]]](http://x)",
      "[[a|<https://x.y>]]",
      "[a <https://x.y>](https://y.z)",
      "[[a|see https://x.y]]",
      "[a https://x.y b](https://y.z)",
      "[![x.y](https://e.com/i.png)](https://y.z)", // a README badge
      "[x ![x.y](https://e.com/i.png)](/p/b)",
      "[[b|![x.y](https://e.com/i.png)]]",
    ]) {
      const html = one(text);
      expect(html, text).not.toMatch(nested);
      expect(html, text).toMatch(/x(\.y)?/); // the inner link's text stays
    }
  });

  it("draws a footnote reference in a link's text as plain [n] (#108)", () => {
    const nested = /<a[^>]*>(?:(?!<\/a>).)*<a/s;
    for (const text of ["[a ^[note]](https://y.z)", "[a ^[note]](/p/b)"]) {
      const html = one(text);
      expect(html, text).not.toMatch(nested);
      expect(html, text).toMatch(/a ?\[1\]/);
    }
    expect(one("a ^[note]")).toContain('<a href="#fn1"'); // outside a link it stays one
  });

  it("never nests a link, whatever links, images and page links are combined", () => {
    const SHA_SRC = `/api/blobs/${SHA}`;
    const inner = [
      "<https://x.y>",
      "https://x.y",
      "[[a]]",
      "[t](https://x.y)",
      "[t](/p/a)",
      "[t](#h)",
      "![i](https://e.com/i.png)",
      "![i](/x.png)",
      `![i](${SHA_SRC})`,
      "[![i](https://e.com/i.png)](https://x.y)",
      "`code`",
    ];
    const outer = [
      (x: string) => `[${x}](https://y.z)`,
      (x: string) => `[${x}](/p/b)`,
      (x: string) => `[${x}](#top)`,
      (x: string) => `[${x}](javascript:x)`,
      (x: string) => `[[b|${x}]]`,
      (x: string) => `[w ${x} w](https://y.z)`,
    ];
    const depth = (html: string) => {
      let open = 0;
      for (const m of html.matchAll(/<(\/?)a[\s>]/g)) {
        open += m[1] ? -1 : 1;
        if (open > 1) return open;
      }
      return open;
    };
    for (const f of outer)
      for (const g of [...outer, (x: string) => x])
        for (const x of inner) {
          const text = f(g(x));
          expect(depth(one(text)), text).toBeLessThanOrEqual(1);
        }
  });

  it("keeps a hand-written link to a footnote as it is", () => {
    const html = one("See [the note](#fn1) and [back](#fnref1:1).\n\nSaid[^1].\n\n[^1]: Note.");
    expect(html).toContain('<a href="#fn1">the note</a>');
    expect(html).toContain('<a href="#fnref1:1">back</a>');
    expect(html).toContain('id="fn1"');
  });

  it("leaves snake_case and lone stars alone", () => {
    expect(one("snake_case_name and 2 * 3 * 4")).toBe("<p>snake_case_name and 2 * 3 * 4</p>");
  });

  it("links http(s) and mailto, pages here and bare URLs; nothing else", () => {
    expect(one("[site](https://e.com/a?b=1&c=2)")).toBe(
      `<p>${a("https://e.com/a?b=1&amp;c=2", "site")}</p>`,
    );
    expect(one("[me](mailto:x@e.com)")).toBe(`<p>${a("mailto:x@e.com", "me")}</p>`);
    expect(one("see https://e.com/x.")).toBe(`<p>see ${a("https://e.com/x")}.</p>`);
    expect(one("(https://e.com/x)")).toBe(`<p>(${a("https://e.com/x")})</p>`);
    expect(one("[**b**](http://e.com)")).toBe(`<p>${a("http://e.com", "<strong>b</strong>")}</p>`);
    expect(one("[p](/p/other) [r](notes/x.md) [f](file:///etc/passwd)")).toBe(
      '<p><a href="/p/other">p</a> r [f](file:///etc/passwd)</p>',
    );
  });

  it("links [[slug]] and [[slug|label]] to pages here", () => {
    expect(one("see [[a-page]]")).toBe('<p>see <a href="/p/a-page">a-page</a></p>');
    expect(one("[[a-page|The **page**]]")).toBe(
      '<p><a href="/p/a-page">The <strong>page</strong></a></p>',
    );
    expect(one("[[a-page|`x` & y]]")).toBe('<p><a href="/p/a-page"><code>x</code> &amp; y</a></p>');
    expect(one('[[Not A Slug]] [[../x]] [[a"b]]')).not.toContain("<a");
  });

  it("links [[slug#heading]] to the page, as the server counts it (markdown.py wiki_page)", () => {
    expect(one("[[a-page#intro]]")).toBe('<p><a href="/p/a-page">a-page#intro</a></p>');
    expect(one("[[a-page#Some heading|Intro]]")).toBe('<p><a href="/p/a-page">Intro</a></p>');
    expect(one("[[a-page#]]")).toContain('<a href="/p/a-page">');
    const table = one("| a |\n|---|\n| [[a-page#x\\|Label]] |");
    expect(table).toContain('<a href="/p/a-page">Label</a>');
    expect(one("[[a-page# x]]")).toContain('<a href="/p/a-page">');
    // a space before the # is no slug, nor is it on the server (markdown.py wiki_page)
    expect(one("[[#intro]] [[Not A Slug#x]] [[a page#x]] [[a-page #x]]")).not.toContain("<a");
  });

  it("shows images only from this server's files", () => {
    expect(one(`![photo](/api/blobs/${SHA})`)).toBe(
      `<p><img src="/api/blobs/${SHA}" alt="photo" loading="lazy" data-sha="${SHA}"></p>`,
    );
    expect(one(`![](/api/blobs/${SHA}/preview?size=480)`)).toContain(`data-sha="${SHA}"`);
    expect(one("![x](https://evil.example/t.png)")).toBe(
      `<p>${a("https://evil.example/t.png", "x")}</p>`,
    );
    expect(one(`![x](/api/blobs/${SHA}/../../x)`)).toBe("<p>x</p>");
  });

  it.each([
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html,<script>alert(1)</script>)",
    "[x](&#x6A;avascript:alert(1))",
    "[x](java\tscript:alert(1))",
    '[x](https://e.com/"onmouseover="alert(1))',
    "![x](javascript:alert(1))",
    "![x](data:image/svg+xml,<svg onload=alert(1)>)",
    `![" onerror="alert(1)](/api/blobs/${SHA})`,
    "https://e.com/<script>alert(1)</script>",
    'https://e.com/"onclick="alert(1)',
    "```\n</code><script>alert(1)</script>\n```",
    '```js" onclick="alert(1)\nx\n```',
    "# <svg onload=alert(1)>",
    "> <iframe src=javascript:alert(1)>",
    "- <a href=javascript:alert(1)>x</a>",
    "- [ ] <img src=x onerror=alert(1)>",
    "| <b>x</b> | y |\n|---|---|\n| <script> | [a](javascript:x) |",
    "[[a|<img src=x onerror=alert(1)>]]",
    "[^1]\n\n[^1]: <script>alert(1)</script>",
    "[a]: javascript:alert(1)\n\n[x][a]",
    "`<b>`**<i>**",
    "0<script>",
    "<!-- x --><style>*{}</style>",
  ])("never lets HTML through: %s", (payload) => {
    // Text is escaped, so every "<" and '"' left is the renderer's own: check each tag.
    const html = marked(payload);
    const ALLOWED =
      /^(p|br|h[1-6]|strong|em|s|code|pre|ul|ol|li|blockquote|hr|a|img|div|table|thead|tbody|tr|th|td|input|label|sup|section)$/;
    const ATTRS = [
      ...[
        "href",
        "target",
        "rel",
        "src",
        "alt",
        "loading",
        "data-sha",
        "data-line",
        "data-at",
        "id",
      ],
      "class",
      "aria-label",
    ];
    for (const [, name, attrs] of html.matchAll(/<\/?([^\s>/]+)([^>]*)>/g)) {
      expect(name).toMatch(ALLOWED);
      const pairs = [...attrs.matchAll(/ ([a-z-]+)(?:="([^"]*)")?/g)];
      expect(pairs.map((p) => p[0]).join("")).toBe(attrs); // nothing but name="value"
      for (const [, attr, value = ""] of pairs) {
        expect([...ATTRS, "style", "type", "disabled", "checked", "start"]).toContain(attr);
        if (attr === "href") expect(value).toMatch(/^(https?:\/\/|mailto:|\/p\/[a-z0-9-]+$|#)/);
        if (attr === "src") expect(value).toMatch(/^\/api\/blobs\/[0-9a-f]{64}/);
        if (attr === "data-sha") expect(value).toMatch(/^[0-9a-f]{64}$/);
        if (attr === "data-line") expect(value).toMatch(/^\d+$/);
        if (attr === "data-at") expect(value).toMatch(/^\d+,\d+$/);
        if (attr === "style") expect(value).toMatch(/^text-align:(left|right|center)$/);
        if (attr === "type") expect(value).toBe("checkbox");
        if (attr === "class" || attr === "aria-label") expect(value).not.toMatch(/[<>"]/); // escaped
      }
    }
  });

  it.each([
    "[",
    "[[",
    "[[a|",
    "[a](",
    "![",
    "`",
    "*a",
    "_a ",
    "**_",
    "<",
    "> ",
    "- ",
    "|",
    "\\",
    "a\n",
    "https://e.com/",
  ])("takes linear time on a run of %j", (piece) => {
    // Best of a few runs, so a stall on a busy runner doesn't count
    const took = (n: number) => {
      let best = Infinity;
      for (let i = 0; i < 3; i++) {
        const start = performance.now();
        markdown(piece.repeat(n / piece.length));
        best = Math.min(best, performance.now() - start);
      }
      return best;
    };
    took(20_000); // warm up
    // Compare scaling, not wall time (a slow runner is slower at both sizes):
    // 4x the input is ~4x the time if linear, ~16x if quadratic.
    const small = Math.max(took(50_000), 1);
    expect(took(200_000) / small).toBeLessThan(10);
  });
});

describe("a page here by its full address (#288)", () => {
  const HERE = "https://scrap.example.org";
  const LAN = "http://192.168.1.10:8000";
  afterEach(() => vi.unstubAllGlobals());
  /** A document whose index.html lists these in its scrap-origins meta tag, as served. */
  const served = (content: string) =>
    vi.stubGlobal("document", {
      querySelector: (q: string) => (q === 'meta[name="scrap-origins"]' ? { content } : null),
    });

  it("is its path: opened in the app, not a new window", () => {
    expect(own(`${HERE}/p/a-page`, [HERE])).toBe("/p/a-page");
    expect(own(`${HERE}/p/a-page?x=1#h-top`, [HERE])).toBe("/p/a-page?x=1#h-top");
    expect(own(`HTTPS://SCRAP.example.org/p/a-page`, [HERE])).toBe("/p/a-page");
  });

  it("is not another site's, another path here, or with no origin known", () => {
    expect(own("https://elsewhere.org/p/a-page", [HERE])).toBeNull();
    expect(own("http://scrap.example.org/p/a-page", [HERE])).toBeNull(); // another origin
    expect(own(`${HERE}/api/blobs/x`, [HERE])).toBeNull();
    expect(own(`${HERE}/p/Not_A_Slug`, [HERE])).toBeNull();
    expect(own("/p/a-page", [HERE])).toBeNull(); // already a path
    expect(own(`${HERE}/p/a-page`, [])).toBeNull();
  });

  it("is the path of one of the app's screens too, opened in place", () => {
    expect(own(`${HERE}/search?q=tag:person%20group:tag`, [HERE])).toBe(
      "/search?q=tag:person%20group:tag",
    );
    expect(own(`${HERE}/todos`, [HERE])).toBe("/todos");
    expect(own(`${HERE}/topics`, [HERE])).toBe("/topics");
    expect(own(`${HERE}/`, [HERE])).toBe("/");
    expect(own(`${HERE}/settings`, [HERE])).toBeNull();
    // written as a path: a link, opened in place (main.ts routes it), not dropped to text
    expect(one("[Everyone](/search?q=tag:person%20group:letter)")).toBe(
      '<p><a href="/search?q=tag:person%20group:letter">Everyone</a></p>',
    );
    expect(one("[Todos](/todos) [Home](/)")).toBe(
      '<p><a href="/todos">Todos</a> <a href="/">Home</a></p>',
    );
    expect(one("[x](/api/blobs/x)")).toBe("<p>x</p>");
    // one of this server's files, by its full address: a link, opened as a file (#403)
    expect(one(`[a.pdf](/api/blobs/${SHA})`)).toBe(
      `<p><a href="/api/blobs/${SHA}" target="_blank" rel="noopener" data-sha="${SHA}">a.pdf</a></p>`,
    );
    expect(one(`[x](/api/blobs/${SHA}/../x)`)).toBe("<p>x</p>");
  });

  it("is on any of the server's addresses (#290)", () => {
    expect(own(`${HERE}/p/a-page`, [HERE, LAN])).toBe("/p/a-page");
    expect(own(`${LAN}/p/b-page#h-x`, [HERE, LAN])).toBe("/p/b-page#h-x");
    expect(own("http://192.168.1.10:8001/p/a-page", [HERE, LAN])).toBeNull(); // another port
  });

  it("knows the addresses the server lists, and the one it was loaded from (#290)", () => {
    vi.stubGlobal("location", { origin: LAN });
    served(`${HERE} https://SCRAP.example.org:443/ not-a-url`);
    expect(origins()).toEqual([LAN, HERE, HERE]);
    expect(one(`[A](${HERE}/p/a-page) and [B](${LAN}/p/b-page)`)).toBe(
      '<p><a href="/p/a-page">A</a> and <a href="/p/b-page">B</a></p>',
    );
    served("");
    expect(origins()).toEqual([LAN]); // the dev server's index.html: no addresses filled in
  });

  it("a page's path with a query or #heading is a link in the app too, as the server counts it", () => {
    expect(one("[A](/p/a-page?x=1) and [B](/p/b-page#h-top) and [C](/p/Bad#x)")).toBe(
      '<p><a href="/p/a-page?x=1">A</a> and <a href="/p/b-page#h-top">B</a> and C</p>',
    );
  });

  it("renders as a link in the app; another site's still opens a new window", () => {
    vi.stubGlobal("location", { origin: HERE });
    expect(one(`[A](${HERE}/p/a-page) and ${HERE}/p/b-page`)).toBe(
      `<p><a href="/p/a-page">A</a> and <a href="/p/b-page">${HERE}/p/b-page</a></p>`,
    );
    expect(one("[A](https://elsewhere.org/p/a-page)")).toBe(
      `<p>${a("https://elsewhere.org/p/a-page", "A")}</p>`,
    );
  });
});

describe("unembedded", () => {
  const e = (n = 2048) => `![](/api/blobs/${SHA}/preview?size=${n})`;
  it("drops lines that only embed this server's images, and the gap each leaves", () => {
    expect(unembedded(`Title\n\n${e()}\n\n${e(480)} ${e()}\n\nafter`)).toBe("Title\n\nafter");
    expect(unembedded(`Notes\n\n${e()}`)).toBe("Notes");
    expect(unembedded(e())).toBe("");
  });
  it("keeps everything else as typed", () => {
    const code = `  indented\n\n\n\nkept gaps\n\`\`\`\n${e()}\n\n\n\`\`\`\nsee ${e()} inline`;
    expect(unembedded(code)).toBe(code);
    expect(unembedded("![x](https://e.com/a.png)")).toBe("![x](https://e.com/a.png)");
  });
});

describe("a page link with no label shows the page's title (#508)", () => {
  const HERE = "https://scrap.example.org";
  const TITLES = { "a-page": "A page & more", "b-page": "B page" };
  const titled = (s: string) =>
    marked(s, TITLES)
      .replace(/ data-at="\d+,\d+"/g, "")
      .trim();
  afterEach(() => vi.unstubAllGlobals());

  it("is the title for [[slug]] and [[slug#heading]], escaped", () => {
    expect(titled("see [[a-page]]")).toBe('<p>see <a href="/p/a-page">A page &amp; more</a></p>');
    expect(titled("[[b-page#intro]]")).toBe('<p><a href="/p/b-page">B page</a></p>');
    expect(titled("| a |\n|---|\n| [[b-page]] |")).toContain('<a href="/p/b-page">B page</a>');
  });

  it("keeps a label as typed, and a dangling link (no title known) as typed", () => {
    expect(titled("[[a-page|my words]]")).toBe('<p><a href="/p/a-page">my words</a></p>');
    expect(titled("[[gone-page#x]]")).toBe('<p><a href="/p/gone-page">gone-page#x</a></p>');
    expect(one("[[a-page]]")).toBe('<p><a href="/p/a-page">a-page</a></p>'); // none given yet
  });

  it("is never one of Object's own names", () => {
    expect(titled("[[constructor]] [[tostring]]")).toBe(
      '<p><a href="/p/constructor">constructor</a> <a href="/p/tostring">tostring</a></p>',
    );
  });

  it("is the title for a page's bare address, not for a link with words of its own", () => {
    vi.stubGlobal("location", { origin: HERE });
    expect(titled(`see ${HERE}/p/a-page`)).toBe(
      '<p>see <a href="/p/a-page">A page &amp; more</a></p>',
    );
    expect(titled(`<${HERE}/p/b-page#h-x>`)).toBe('<p><a href="/p/b-page#h-x">B page</a></p>');
    expect(titled("[/p/b-page](/p/b-page)")).toBe('<p><a href="/p/b-page">B page</a></p>');
    expect(titled(`[Words](${HERE}/p/a-page) [x **y**](/p/b-page)`)).toBe(
      '<p><a href="/p/a-page">Words</a> <a href="/p/b-page">x <strong>y</strong></a></p>',
    );
    expect(titled(`${HERE}/p/gone-page`)).toBe(
      `<p><a href="/p/gone-page">${HERE}/p/gone-page</a></p>`,
    );
    // another site's /p/ page is not this server's
    expect(titled("https://elsewhere.org/p/a-page")).not.toContain("A page");
  });
});
