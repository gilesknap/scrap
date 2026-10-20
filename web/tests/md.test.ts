import { describe, expect, it } from "vitest";
import { unembedded } from "../src/md";
import { markdown } from "../src/render";

const SHA = "a".repeat(64);
const a = (href: string, text = href) =>
  `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
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
      '<ul>\n<li class="task"><input type="checkbox" disabled> todo</li>\n' +
        '<li class="task"><input type="checkbox" disabled checked> done</li>\n' +
        "<li>[y] not a box</li>\n</ul>",
    );
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

  it("leaves a ```mermaid block as code, for the diagram chunk", () => {
    expect(one("```mermaid\ngraph TD; A-->B\n```")).toBe(
      '<pre><code class="language-mermaid">graph TD; A--&gt;B\n</code></pre>',
    );
  });

  it("nests code in links, and never a link in a link (#52)", () => {
    expect(one("[`code`](https://e.com)")).toBe(
      `<p>${a("https://e.com", "<code>code</code>")}</p>`,
    );
    expect(one("[see [[a|Label]]](http://x)")).not.toMatch(/<a[^>]*>[^<]*<a/);
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
    const html = markdown(payload);
    const ALLOWED =
      /^(p|br|h[1-6]|strong|em|s|code|pre|ul|ol|li|blockquote|hr|a|img|div|table|thead|tbody|tr|th|td|input|sup|section)$/;
    const ATTRS = ["href", "target", "rel", "src", "alt", "loading", "data-sha", "id", "class"];
    for (const [, name, attrs] of html.matchAll(/<\/?([^\s>/]+)([^>]*)>/g)) {
      expect(name).toMatch(ALLOWED);
      const pairs = [...attrs.matchAll(/ ([a-z-]+)(?:="([^"]*)")?/g)];
      expect(pairs.map((p) => p[0]).join("")).toBe(attrs); // nothing but name="value"
      for (const [, attr, value = ""] of pairs) {
        expect([...ATTRS, "style", "type", "disabled", "checked", "start"]).toContain(attr);
        if (attr === "href") expect(value).toMatch(/^(https?:\/\/|mailto:|\/p\/[a-z0-9-]+$|#)/);
        if (attr === "src") expect(value).toMatch(/^\/api\/blobs\/[0-9a-f]{64}/);
        if (attr === "data-sha") expect(value).toMatch(/^[0-9a-f]{64}$/);
        if (attr === "style") expect(value).toMatch(/^text-align:(left|right|center)$/);
        if (attr === "type") expect(value).toBe("checkbox");
        if (attr === "class") expect(value).not.toMatch(/[<>"]/); // escaped
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
    const took = (n: number) => {
      const start = performance.now();
      markdown(piece.repeat(n / piece.length));
      return performance.now() - start;
    };
    took(20_000); // warm up
    expect(took(200_000)).toBeLessThan(2000);
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
