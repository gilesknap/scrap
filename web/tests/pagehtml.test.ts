import { describe, expect, it } from "vitest";
import {
  articleHtml,
  htmlName,
  inline,
  type N,
  pageHtml,
  photos,
  prose,
  textOf,
} from "../src/pagehtml";

type Attrs = Record<string, string>;
const t = (data: string): N => ({ nodeType: 3, nodeName: "#text", data, childNodes: [] });
const e = (name: string, attrs: Attrs = {}, ...kids: (N | string)[]): N => ({
  nodeType: 1,
  nodeName: name.toUpperCase(),
  childNodes: kids.map((k) => (typeof k === "string" ? t(k) : k)),
  getAttribute: (k) => attrs[k] ?? null,
  hasAttribute: (k) => k in attrs,
});
const SHA = "a".repeat(64);
const none = new Map<N, string | null>();

describe("pageHtml", () => {
  it("keeps the page's text and its own labels, and adds nothing", () => {
    const page = e(
      "article",
      { class: "page" },
      e("h1", {}, "Title"),
      e("section", { class: "enrich claude" }, e("h3", { class: "ctitle" }, "About this page")),
    );
    const html = pageHtml(page, "Title", none);
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain('<h3 class="ctitle">About this page</h3>');
    expect(html).not.toMatch(/may be wrong|written by a model/i);
  });

  it("drops scripts, buttons, forms and the page's tool row, with what is in them", () => {
    const page = e(
      "article",
      {},
      e("script", {}, "alert(1)"),
      e("p", { onclick: "x()", style: "color:red" }, "hi"),
      e("button", {}, "Delete"),
      e("div", { class: "bar tools" }, "tools"),
      e("a", { href: "/api/blobs/x", download: "" }, "Download"),
      e("svg", {}, "drawing"),
    );
    const html = pageHtml(page, "T", none);
    expect(html).toContain("<p>hi</p>");
    for (const gone of ["alert", "Delete", "tools", "Download", "drawing", "onclick", "red"])
      expect(html).not.toContain(gone);
  });

  it("links only to the web, and lists a scrap link or file by its words", () => {
    const page = e(
      "p",
      {},
      e("a", { href: "https://example.com/x?a=1&b=2" }, "web"),
      e("a", { href: "javascript:alert(1)" }, "js"),
      e("a", { href: "/p/other" }, "page"),
      e("a", { href: `/api/blobs/${SHA}` }, "scan.pdf"),
    );
    const html = pageHtml(page, "T", none);
    expect(html).toContain('<a href="https://example.com/x?a=1&amp;b=2">web</a>');
    expect(html).toContain("jspagescan.pdf");
    expect(html).not.toMatch(/javascript:|\/p\/other|\/api\//);
  });

  it("escapes text and the title", () => {
    const html = pageHtml(e("p", {}, "<b>&"), '</title><script>"', none);
    expect(html).toContain("<p>&lt;b&gt;&amp;</p>");
    expect(html).toContain("<title>&lt;/title&gt;&lt;script&gt;&quot;</title>");
    expect(html).not.toContain("<script>");
  });

  it("has no script, and a policy that fetches nothing", () => {
    const html = pageHtml(e("p", {}, "x"), "T", none);
    expect(html).toContain("default-src 'none'; img-src data:");
    expect(html).not.toMatch(/<script|<link|@import|url\(/);
  });

  it("inlines a photo as its data address and names one that was not", () => {
    const a = e("img", { src: `/api/blobs/${SHA}/preview?size=2048`, alt: "cat" });
    const b = e("img", { src: `/api/blobs/${SHA}/preview?size=2048`, alt: "dog" });
    const html = pageHtml(
      e("div", {}, a, b),
      "T",
      new Map([
        [a, "data:image/jpeg;base64,AA"],
        [b, null],
      ]),
    );
    expect(html).toContain('<img src="data:image/jpeg;base64,AA" alt="cat">');
    expect(html).toContain('<em class="named">[dog]</em>');
    expect(html).not.toContain("/api/");
  });
});

describe("inline", () => {
  const img = (alt: string) => e("img", { src: `/api/blobs/${SHA}/preview?size=2048`, alt });
  const jpeg = (n: number) => new Blob([new Uint8Array(n)], { type: "image/jpeg" });
  const read = async (b: Blob) => "x".repeat(b.size);

  it("asks for the 480 pixel preview", async () => {
    const asked: string[] = [];
    await inline(
      [img("a")],
      async (u) => {
        asked.push(u);
        return jpeg(1);
      },
      read,
    );
    expect(asked).toEqual([`/api/blobs/${SHA}/preview?size=480`]);
  });

  it("stops inlining at the cap, in page order, and names the rest", async () => {
    const [a, b, c] = [img("a"), img("b"), img("c")];
    const got = await inline([a, b, c], async () => jpeg(40), read, 100);
    expect([...got.values()].map((v) => v?.length ?? null)).toEqual([40, 40, null]);
  });

  it("names a photo it could not fetch, or that is not a JPEG", async () => {
    const [a, b] = [img("a"), img("b")];
    let n = 0;
    const got = await inline(
      [a, b],
      async () => (n++ ? new Blob(["x"], { type: "image/png" }) : null),
      read,
    );
    expect([...got.values()]).toEqual([null, null]);
  });
});

describe("photos and names", () => {
  it("finds this server's photos, not those in a control", () => {
    const own = e("img", { src: `/api/blobs/${SHA}/preview?size=2048` });
    const other = e("img", { src: "https://example.com/a.png" });
    const page = e("div", {}, own, other, e("button", {}, e("img", { src: `/api/blobs/${SHA}` })));
    expect(photos(page)).toEqual([own]);
  });

  it("names the file for the page", () => {
    expect(htmlName("Trip: Rome / 2026")).toBe("Trip-Rome-2026.html");
    expect(htmlName("???")).toBe("page.html");
  });
});

describe("the page's own parts", () => {
  it("shows a task box as its state, and leaves out prompts and where Claude is up to", () => {
    const page = e(
      "div",
      {},
      e("label", { class: "taskbox" }, e("input", { type: "checkbox", disabled: "", checked: "" })),
      e("label", { class: "taskbox" }, e("input", { type: "checkbox", disabled: "" })),
      e("span", { class: "state queued", role: "status" }, "Waiting for Claude"),
      e("p", { class: "did" }, "Claude can describe it"),
      e("small", { class: "hint" }, "Text couldn't be read"),
    );
    const html = pageHtml(page, "T", none);
    expect(html).toContain("[x] ");
    expect(html).toContain("[ ] ");
    expect(html).not.toMatch(/Waiting|can describe|couldn't/);
  });

  it("does not fetch a photo once the file is full", async () => {
    const mk = (alt: string) => e("img", { src: `/api/blobs/${SHA}/preview?size=2048`, alt });
    const asked: string[] = [];
    await inline(
      [mk("a"), mk("b")],
      async (u) => {
        asked.push(u);
        return new Blob(["x"], { type: "image/jpeg" });
      },
      async () => "x".repeat(10),
      10,
    );
    expect(asked).toHaveLength(1);
  });
});

describe("text that holds Markdown (#427)", () => {
  const card = e(
    "section",
    { class: "enrich claude" },
    e("p", { class: "summary" }, "A **bold** summary\n\n- one"),
    e("div", { class: "bar tools" }, e("p", { class: "summary" }, "in a control")),
  );

  it("finds the summary and a body shown as typed, not those in a control", () => {
    const raw = e("div", { class: "body raw" }, "# Hi");
    const page = e("article", {}, raw, card);
    expect(prose(page)).toHaveLength(2);
    expect(prose(page)[0]).toBe(raw);
    expect(prose(card).map((n) => textOf(n))).toEqual(["A **bold** summary\n\n- one"]);
  });

  it("reads a section's text with its line breaks", () => {
    expect(textOf(e("p", {}, "a", e("br"), "b"))).toBe("a\nb");
  });

  it("writes what a section's Markdown makes, with no raw marks and no paragraph in a paragraph", () => {
    const [summary] = prose(card);
    const made = e(
      "div",
      {},
      e("p", {}, "A ", e("strong", {}, "bold"), " summary"),
      e("ul", {}, e("li", {}, "one")),
    );
    const html = pageHtml(card, "T", none, new Map([[summary, made]]));
    expect(html).toContain(
      '<div class="summary"><p>A <strong>bold</strong> summary</p><ul><li>one</li></ul></div>',
    );
    expect(html).not.toMatch(/\*\*|<p[^>]*><p/);
  });
});

describe("the meta line", () => {
  it("spells out the separators the app draws with CSS, so the parts do not run together", () => {
    const page = e(
      "article",
      {},
      e(
        "p",
        { class: "meta" },
        e(
          "span",
          { class: "parts" },
          e("span", { class: "kind" }, e("svg", {}, "icon"), "Todo"),
          e("span", {}, "1 of 2"),
        ),
      ),
    );
    const html = pageHtml(page, "T", none);
    expect(html).toContain("</span> · <span>1 of 2");
    expect(html.replace(/<[^>]*>/g, "")).toContain("Todo · 1 of 2"); // as text or copied
  });
});

describe("articleHtml (Copy as rich text)", () => {
  it("is the title and the text alone, its photos named and nothing fetched", async () => {
    const page = e(
      "article",
      { class: "page" },
      e("h1", {}, "Title"),
      e("p", { class: "meta dates" }, "Note · Created today"),
      e("div", { class: "tags" }, e("a", { href: "/search?q=tag:x" }, "#x")),
      e(
        "div",
        { class: "body md" },
        e("p", {}, "Some ", e("strong", {}, "bold")),
        e("img", { src: `/api/blobs/${SHA}`, alt: "Beach" }),
      ),
      e("div", { class: "originals" }, e("figure", {}, "scan.pdf")),
      e("section", { class: "enrich claude" }, e("h3", {}, "About this page")),
      e("div", { class: "bar tools" }, e("button", {}, "Share")),
    );
    const html = await articleHtml(page);
    expect(html).toBe(
      '<h1>Title</h1><div class="body md"><p>Some <strong>bold</strong></p>' +
        '<em class="named">[Beach]</em></div>',
    );
    expect(html).not.toMatch(/data:|<style|<!doctype|\/api\//i);
  });
});
