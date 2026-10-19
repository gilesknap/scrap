import { describe, expect, it } from "vitest";
import { inline, markdown } from "../src/md";

const SHA = "a".repeat(64);

describe("markdown", () => {
  it("renders the basics", () => {
    expect(markdown("# Title\n\nSome **bold** and *it* and _it_ and `x<y`")).toBe(
      "<h1>Title</h1>\n<p>Some <strong>bold</strong> and <em>it</em> and <em>it</em> and <code>x&lt;y</code></p>",
    );
    expect(markdown("line one\nline two\n\nnext")).toBe("<p>line one<br>line two</p>\n<p>next</p>");
    expect(markdown("- a\n* b\n\n1. one\n2) two")).toBe(
      "<ul><li>a</li><li>b</li></ul>\n<ol><li>one</li><li>two</li></ol>",
    );
    expect(markdown("> quoted\n> **more**\n\n---")).toBe(
      "<blockquote><p>quoted<br><strong>more</strong></p></blockquote>\n<hr>",
    );
    expect(markdown("```\n<b>**not bold**</b>\n```")).toBe(
      "<pre><code>&lt;b&gt;**not bold**&lt;/b&gt;</code></pre>",
    );
  });

  it("leaves snake_case and lone stars alone", () => {
    expect(inline("snake_case_name and 2 * 3 * 4")).toBe("snake_case_name and 2 * 3 * 4");
  });

  it("links http(s) and mailto only, bare URLs too", () => {
    const a = (href: string, text = href) =>
      `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    expect(inline("[site](https://e.com/a?b=1&c=2)")).toBe(
      a("https://e.com/a?b=1&amp;c=2", "site"),
    );
    expect(inline("[me](mailto:x@e.com)")).toBe(a("mailto:x@e.com", "me"));
    expect(inline("see https://e.com/x.")).toBe(`see ${a("https://e.com/x")}.`);
    expect(inline("(https://e.com/x)")).toBe(`(${a("https://e.com/x")})`);
    expect(inline("[**b**](http://e.com)")).toBe(a("http://e.com", "<strong>b</strong>"));
  });

  it("shows images only from this server's files", () => {
    expect(inline(`![photo](/api/blobs/${SHA})`)).toBe(
      `<img src="/api/blobs/${SHA}" alt="photo" loading="lazy">`,
    );
    expect(inline(`![](/api/blobs/${SHA}/preview?size=480)`)).toContain("<img");
    expect(inline("![x](https://evil.example/t.png)")).not.toContain("<img");
    expect(inline(`![x](/api/blobs/${SHA}/../../x)`)).not.toContain("<img");
  });

  it.each([
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html,<script>alert(1)</script>)",
    "[x](&#x6A;avascript:alert(1))",
    '[x](https://e.com/"onmouseover="alert(1))',
    "![x](javascript:alert(1))",
    `![" onerror="alert(1)](/api/blobs/${SHA})`,
    "https://e.com/<script>alert(1)</script>",
    'https://e.com/"onclick="alert(1)',
    "```\n</code><script>alert(1)</script>\n```",
    "# <svg onload=alert(1)>",
    "> <iframe src=javascript:alert(1)>",
    "- <a href=javascript:alert(1)>x</a>",
    "`<b>`**<i>**",
    "0<script>",
  ])("never lets HTML through: %s", (payload) => {
    // Text is escaped, so every "<" and '"' left is the renderer's own: check each tag.
    const html = markdown(payload);
    const ALLOWED = /^(p|br|h[1-6]|strong|em|code|pre|ul|ol|li|blockquote|hr|a|img)$/;
    for (const [, name, attrs] of html.matchAll(/<\/?([^\s>/]+)([^>]*)>/g)) {
      expect(name).toMatch(ALLOWED);
      const pairs = [...attrs.matchAll(/ ([a-z]+)="([^"]*)"/g)];
      expect(pairs.map((p) => p[0]).join("")).toBe(attrs); // nothing but name="value"
      for (const [, attr, value] of pairs) {
        expect(["href", "target", "rel", "src", "alt", "loading"]).toContain(attr);
        if (attr === "href") expect(value).toMatch(/^(https?:\/\/|mailto:)/);
        if (attr === "src") expect(value).toMatch(/^\/api\/blobs\/[0-9a-f]{64}/);
      }
    }
  });
});
