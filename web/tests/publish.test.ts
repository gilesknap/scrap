// The publish mode (publish.ts) on fixture pages: the page's view as the app draws it (its
// text by the app's own renderer, its header, files and Claude card as page.ts and its chunks
// draw them), written as a public page. Each output is saved in tests/fixtures/published/ (run
// vitest with -u after a deliberate change), so scrap's own check can be run on the same files,
// and is held here to the contract's rules (publiccheck.ts).
import katex from "katex";
import { beforeAll, describe, expect, it } from "vitest";
import { KATEX } from "../src/katexopts";
import type { N, Swaps } from "../src/pagehtml";
import type { Context } from "../src/publish";
import { type El, first, parse } from "./htmlparse";
import { CSP, check } from "./publiccheck";

// scrap's own address, as the app sees it: a full address of a page here is the page's
(globalThis as { location?: { origin: string } }).location = { origin: "http://scrap.example" };
const { markdown: marked } = await import("../src/render");
const { bare, bareSlugs, hasMaths, idsOf, publishHtml, webLink } = await import("../src/publish");

const markdown = (s: string) => marked(s).replace(/ data-at="\d+,\d+"/g, "");
const SHA = (c: string) => c.repeat(64);
const ORIGINS = ["http://scrap.example"];
const LIVE = new Set(["design-notes", "whiteboard", "links-page", "maths-page", "a-todo"]);
const TITLES = {
  "design-notes": "Design notes",
  "weekly-sync": "Weekly controls sync",
};
const tex = (t: string, display: boolean) =>
  katex.renderToString(t, { ...KATEX, displayMode: display });

/** The page's header as pagehead.ts draws it: title, meta and dates lines, the chip row. */
function head(title: string, kind: string, tags: string[], pub = true) {
  const chips = tags.map(
    (t) =>
      `<a href="/search?q=${encodeURIComponent(`tag:${t}`)}" aria-label="Tag ${t}" title="Tag ${t}"><span class="tl" dir="auto">#${t}</span></a>`,
  );
  return `<h1 dir="auto">${title}</h1>
<p class="meta dates"><span class="parts"><span class="kind"><svg class="i"></svg>${kind}</span><a class="written" href="/search?q=is%3Aclaude">by Claude</a><span>Created 1 Nov, 10:00</span>${pub ? '<span class="pubdate">Published 1 Nov, 11:00</span>' : ""}</span></p>
${pub || tags.length ? `<p class="tags">${pub ? '<a class="pubchip" href="https://pages.example/p/x" target="_blank" rel="noopener" title="Published"><svg class="i"></svg>Public</a>' : ""}${chips.join("")}${tags.length > 1 ? '<button type="button" class="morechips">+1</button>' : ""}</p>` : ""}
<hr class="headend" aria-hidden="true">`;
}
const tools = '<div class="bar tools"><button>Edit</button><button>Share</button></div>';
const article = (...parts: string[]) =>
  `<article class="page" data-kind="note">${parts.join("\n")}</article>`;

/** The view as N, and the swaps of its plain-text Markdown (Claude's summary) as the app
 * renders them (pagehtml.ts swapsOf, with the renderer in place of DOMParser). */
function view(html: string): { root: N; swaps: Swaps } {
  const root = (parse(html).childNodes[0] as El) ?? null;
  const swaps: Swaps = new Map();
  const walk = (n: El) => {
    const cls = ` ${n.getAttribute?.("class") ?? ""} `;
    if (n.nodeName === "P" && cls.includes(" summary "))
      swaps.set(n, parse(markdown(n.childNodes.map((k) => k.data ?? "").join(""))));
    else for (const k of n.childNodes) if (k.nodeType === 1) walk(k as El);
  };
  walk(root);
  return { root, swaps };
}

const ctx = (o: Partial<Context>): Context => ({
  title: "T",
  tags: [],
  live: LIVE,
  titles: TITLES,
  origins: ORIGINS,
  site: "https://pages.example",
  tex,
  date: "1 Nov 2026",
  ...o,
});

const FIXTURES: Record<string, () => { html: string; c: Context }> = {
  links: () => {
    const body =
      markdown(`Links to [[design-notes]], [the notes](/p/design-notes), [[weekly-sync]], [[gone-page]], [[weekly-sync|the *sync*]], and http://scrap.example/p/design-notes written out.

Elsewhere: <https://example.com/a?b=1&c=2>, [mail](mailto:me@example.com), [own](https://scrap.example/health), [api](https://elsewhere.example/api/x), [user](https://bob@example.com/), [search](/search?q=tag:work).

## Café notes

See [the notes](#café-notes) and the footnote.[^1] Again.[^1]

[^1]: A footnote.

- [ ] to do
- [x] done

| a | b |
|---|---|
| 1 | 2 |

\`\`\`js
code();
\`\`\`

\`\`\`mermaid
graph TD; A-->B
\`\`\`

Text naming scrap-blob:abc and scrap-tag:x.

Private addresses: scrap.example:8000/health, \`curl https://scrap.example/api/blobs/aaa\`, and /api/pages/x; not scrap.example.org.`);
    const drawn =
      '<div class="diagram" role="img" data-source="graph LR; X--&gt;Y"><svg><g><text>X</text></g></svg></div>';
    const tags = ["work", "personal/family", "café talk", "it's (done)"];
    const html = article(
      head("Links &amp; more", "Note", tags),
      `<div class="body md" dir="auto">${body}${drawn}</div>`,
      '<div class="originals"></div>',
      tools,
    );
    return { html, c: ctx({ title: "Links & more", tags }) };
  },
  maths: () => {
    const body = markdown(`Inline $e^{i\\pi} + 1 = 0$ and $$\\frac{1}{2}$$ inline display.

$$
\\int_0^1 x^2\\,dx = \\tfrac13
$$

\`\`\`math
\\overrightarrow{AB} \\color{red}{x}
\`\`\`

\\begin{align}
a &= b \\\\
c &= d
\\end{align}

Broken: $\\frac{1}{$ stays TeX.`);
    const drawn =
      '<p>Drawn: <span class="math" data-tex="x^2"><span class="katex"><span class="katex-html">x2</span></span></span></p>';
    const html = article(
      head("Maths", "Note", ["maths"]),
      `<div class="body md" dir="auto">${body}${drawn}</div>`,
      tools,
    );
    return { html, c: ctx({ title: "Maths", tags: ["maths"] }) };
  },
  "photo-board": () => {
    const writeup = markdown(
      "The flow, as in [[design-notes]]; agreed at the [[weekly-sync]].\n\n- a list with [[weekly-sync|the sync]]",
    );
    const html = article(
      head("Architecture whiteboard", "Board", ["work"]),
      `<div class="body md" dir="auto"><section class="photo-panel"><div class="tabs" role="tablist"><button role="tab">Photo</button><button role="tab">Drawing</button></div><div class="pair show-drawing"><figure class="orig"><a href="/api/blobs/${SHA("a")}"><img src="/api/blobs/${SHA("a")}/preview?size=2048" alt="IMG_2041.jpg" loading="lazy"></a></figure><figure class="orig drawing"><button class="drawing-card"><svg><path d="M0 0"/></svg></button></figure></div><div class="claude"><div class="ingest"><h3 class="ctitle">What's in the photo</h3><button class="link">Regenerate</button></div><details class="claude-text"><summary>Description</summary><p>SECRET description</p></details><details class="claude-text"><summary>Text in the photo</summary><pre>SECRET read text</pre></details></div></section>
<p>Drawn after the <a href="/p/weekly-sync">weekly-sync</a>; see <a href="/p/design-notes">design-notes</a>. A sketch: <img src="/api/blobs/${SHA("b")}/preview?size=2048" alt="sketch.png" data-sha="${SHA("b")}" loading="lazy">, the <a href="/api/blobs/${SHA("c")}" target="_blank" rel="noopener" data-sha="${SHA("c")}">spec</a>, and an image from elsewhere: <img src="https://example.com/x.png" alt="theirs"></p></div>`,
      `<div class="originals"><section class="file-panel"><div class="orig filerow"><a href="/api/blobs/${SHA("c")}" target="_blank" class="file"><svg class="i"></svg><span class="words"><span>spec.pdf</span><small>12 pages</small></span></a></div><div class="claude"><div class="ingest"><h3 class="ctitle">What's in the file</h3></div><p class="did">SECRET reading</p><details class="claude-text"><summary>Text</summary><p>SECRET file text</p></details></div></section><div class="orig filerow"><a href="/api/blobs/${SHA("d")}" target="_blank" class="file"><svg class="i"></svg><span class="words"><span>notes.md</span></span></a><p class="hint">Text couldn't be read; not searchable</p></div></div>`,
      `<section class="enrich claude" aria-label="About this page"><div class="ingest"><h3 class="ctitle">About this page</h3><span class="state done" role="status">x</span><button class="link">Regenerate</button></div><details class="claude-text"><summary>Summary</summary><p class="summary" dir="auto">A **whiteboard** of the [[design-notes]] flow, from the [[weekly-sync]].</p></details><details class="claude-text writeup"><summary>In detail</summary><div class="card"><p class="by" title="claude-opus-5-5">Claude · 1 Nov, 10:04</p><div class="body md" dir="auto">${writeup}</div><details class="claude-text sub"><summary>Guidance for Claude</summary><p class="by">Used by the next write-up.</p><textarea>SECRET guidance</textarea><div class="row"><button class="primary">Save</button></div></details></div></details><details class="claude-text related topics"><summary>Topics</summary><ul><li><a href="/p/private-topic" dir="auto"><svg class="i"></svg>A private topic</a></li></ul></details><details class="claude-text related"><summary>Related</summary><ul><li><a href="/p/design-notes" dir="auto"><svg class="i"></svg>Design notes</a><small> · links here</small></li><li><a href="/p/weekly-sync" dir="auto"><svg class="i"></svg>Weekly controls sync</a><small> · in a write-up</small></li></ul></details></section>`,
      tools,
    );
    return { html, c: ctx({ title: "Architecture whiteboard", tags: ["work"] }) };
  },
  plain: () => {
    const html = article(
      head("A todo", "Todo", [], true),
      `<div class="body md" dir="auto">${markdown("- [ ] buy milk\n- [x] call\n\nSee [[whiteboard]].")}</div>`,
      '<p class="notes">Your notes on this topic go here</p>',
      tools,
    );
    return { html, c: ctx({ title: "A todo", site: null, tex: null }) };
  },
};

const out: Record<string, string> = {};
beforeAll(() => {
  for (const [name, make] of Object.entries(FIXTURES)) {
    const { html, c } = make();
    const { root, swaps } = view(html);
    out[name] = publishHtml(root, c, swaps);
  }
});

describe("the publish mode's fixtures", () => {
  for (const name of Object.keys(FIXTURES)) {
    it(`${name}: passes the contract's check, as saved`, async () => {
      expect(check(out[name], LIVE, ["scrap.example"])).toEqual([]);
      await expect(out[name]).toMatchFileSnapshot(`./fixtures/published/${name}.html`);
    });
  }
});

describe("what a public page holds", () => {
  it("has the fixed head: charset, viewport, the CSP, page.css, and no <style>", () => {
    const h = out.plain;
    expect(h.startsWith("<!DOCTYPE html>\n")).toBe(true);
    expect(h).toContain(`<meta http-equiv="Content-Security-Policy" content="${CSP}">`);
    expect(h).toContain('<link rel="stylesheet" href="/assets/page.css">');
    expect(h).not.toContain("katex.css");
    expect(h).not.toMatch(/<style|<script|\/api\//);
    expect(out.maths).toContain('<link rel="stylesheet" href="/assets/katex.css">');
  });

  it("links public pages by their title when bare, private ones as their words", () => {
    const h = out.links;
    expect(h).toContain('<a href="/p/design-notes">Design notes</a>'); // bare: its title
    expect(h).toContain('<a href="/p/design-notes">the notes</a>'); // labelled: as typed
    expect(h).toContain("<span>Weekly controls sync</span>"); // private, bare: its title
    expect(h).toContain("<span>a private page</span>"); // private, gone
    expect(h).toContain("<span>the <em>sync</em></span>"); // private, labelled
    expect(h).not.toMatch(/weekly-sync|gone-page/); // never the slug
    // A full address of a page here is the page's (render.ts), so its title
    expect(h).not.toMatch(/scrap\.example(?!\.org)/);
  });

  it("keeps the web's links, not scrap's own, /api/ ones, a user's, or the app's screens", () => {
    const h = out.links;
    expect(h).toContain('<a href="https://example.com/a?b=1&amp;c=2">');
    expect(h).toContain('<a href="mailto:me@example.com">mail</a>');
    for (const gone of ["/health", "elsewhere.example", "bob@", "/search"])
      expect(h).not.toContain(gone);
    expect(h).toMatch(/>own<|own,/);
  });

  it("makes heading and footnote ids safe, and #links follow them", () => {
    const h = out.links;
    expect(h).toContain('<h2 id="h-cafe-notes">');
    expect(h).toContain('<a href="#h-cafe-notes">the notes</a>');
    expect(h).toContain('id="fnref1"');
    expect(h).toContain('id="fnref1-1"');
    expect(h).toContain('<li id="fn1" class="footnote-item">');
  });

  it("writes tags as scrap-tag chips, in order, and not the Public chip", () => {
    expect(out.links).toContain(
      '<p class="tags"><a href="scrap-tag:work">#work</a><a href="scrap-tag:personal%2Ffamily">#personal/family</a><a href="scrap-tag:caf%C3%A9%20talk">#café talk</a><a href="scrap-tag:it%27s%20%28done%29">#it\'s (done)</a></p>',
    );
    for (const h of Object.values(out))
      expect(h).not.toMatch(/Public<|pubchip|morechips|Published 1 Nov, 11/);
  });

  it("writes Mermaid as its source, drawn or not", () => {
    expect(out.links).toContain(
      '<pre><code class="language-mermaid">graph TD; A--&gt;B\n</code></pre>',
    );
    expect(out.links).toContain(
      '<pre><code class="language-mermaid">graph LR; X--&gt;Y</code></pre>',
    );
    expect(out.links).not.toContain("<svg");
  });

  it("writes maths as KaTeX's markup, and a formula it can't draw as its TeX", () => {
    const h = out.maths;
    expect(h).toContain('<span class="math"><span class="katex">');
    expect(h).toContain('<div class="math display"><span class="katex-display">');
    expect(h).toContain('<annotation encoding="application/x-tex">x^2</annotation>'); // drawn: data-tex
    expect(h).toContain('<code class="math">$\\frac{1}{$</code>');
  });

  it("publishes the photo alone, its alt as the app has it, and files as placeholders", () => {
    const h = out["photo-board"];
    expect(h).toContain(
      `<a href="scrap-blob:${SHA("a")}"><img src="scrap-blob:${SHA("a")}" alt="IMG_2041.jpg"></a>`,
    );
    expect(h).toContain(`<img src="scrap-blob:${SHA("b")}" alt="sketch.png">`);
    expect(h).toContain(`<a href="scrap-blob:${SHA("c")}">spec</a>`);
    expect(h).toContain(`<a href="scrap-blob:${SHA("d")}">`);
    expect(h).toContain('<em class="named">[theirs]</em>');
    expect(h).not.toMatch(/SECRET|drawing|Regenerate|Guidance|textarea|Photo<|What's in/);
  });

  it("keeps Claude's summary and write-up, and only the public pages it lists", () => {
    const h = out["photo-board"];
    expect(h).toContain("<strong>whiteboard</strong>"); // the summary, as Markdown
    expect(h).toContain("Claude · 1 Nov, 10:04");
    expect(h).toContain('<a href="/p/design-notes">Design notes</a><small> · links here</small>');
    expect(h).not.toMatch(/private-topic|A private topic|Topics|in a write-up/);
    expect(h).toContain("<span>Weekly controls sync</span>"); // in the write-up's text: its words
  });

  it("names the site in its header (Pages when not known), both linking to its home", () => {
    expect(out.links).toContain('<div class="site top"><a href="/">pages.example</a></div>');
    const foot =
      '<div class="site foot">Published 1 Nov 2026 from scrap · <a href="/">All pages</a></div>';
    expect(out.links).toContain(foot);
    expect(out.plain).toContain('<div class="site top"><a href="/">Pages</a></div>');
    expect(out.plain).toContain(foot);
  });

  it("says a private link for an address of scrap's own, or of its API, in any text (S3)", () => {
    const h = out.links;
    expect(h).toContain(
      "Private addresses: a private link, <code>curl a private link</code>, and a private link; not scrap.example.org.",
    );
    expect(h).not.toMatch(/scrap\.example[:/]|\/api\//);
  });

  it("finds scrap's host hidden by zero-width characters or full-width dots, and in alt", () => {
    const html = article(
      head("T", "Note", [], false),
      '<div class="body md"><p>at scrap\u200b.example/p/x and scrap\u3002example now</p><p><img src="/api/blobs/' +
        "a".repeat(64) +
        '/preview?size=2048" alt="from http://scrap.example/p/x"></p></div>',
    );
    const { root, swaps } = view(html);
    const h = publishHtml(root, ctx({}), swaps);
    expect(h).toContain("<p>at a private link and a private link now</p>");
    expect(h).toContain('alt="from a private link"');
    expect(check(h, LIVE, ["scrap.example"])).toEqual([]);
  });

  it("escapes a tag's every special character in its placeholder", () => {
    expect(out.links).toContain('<a href="scrap-tag:it%27s%20%28done%29">#it\'s (done)</a>');
  });

  it("names the site Pages when it is on scrap's own host", () => {
    const { root, swaps } = view(article(markdown("x")));
    const h = publishHtml(root, ctx({ site: "http://scrap.example:9000" }), swaps);
    expect(h).toContain('<div class="site top"><a href="/">Pages</a></div>');
  });

  it("leaves a placeholder in the text unable to be read as one", () => {
    expect(out.links).toContain("scrap-⁠blob:abc and scrap-⁠tag:x");
  });

  it("drops a Claude card left with nothing public", () => {
    const html = article(
      head("T", "Note", [], false),
      '<section class="enrich claude"><div class="ingest"><h3 class="ctitle">About this page</h3></div><details class="claude-text related"><summary>Related</summary><ul><li><a href="/p/private">Private</a></li></ul></details></section>',
    );
    const { root, swaps } = view(html);
    expect(publishHtml(root, ctx({}), swaps)).not.toContain("About this page");
  });
});

describe("its parts", () => {
  it("tells a bare link from a labelled one", () => {
    expect(bare("my-page", "my-page")).toBe(true);
    expect(bare("my-page#plan", "my-page")).toBe(true);
    expect(bare("https://scrap.example/p/my-page", "my-page")).toBe(true);
    expect(bare("/p/my-page", "my-page")).toBe(true);
    expect(bare("My page", "my-page")).toBe(false);
    expect(bare("my-page-2", "my-page")).toBe(false);
  });

  it("links only the web's addresses that are not scrap's", () => {
    expect(webLink("https://example.com/x", ORIGINS)).toBe(true);
    expect(webLink("http://example.com", ORIGINS)).toBe(true);
    expect(webLink("https://SCRAP.example./x", ORIGINS)).toBe(false);
    expect(webLink("https://example.com/api/x", ORIGINS)).toBe(false);
    expect(webLink("https://u:p@example.com/", ORIGINS)).toBe(false);
    expect(webLink("javascript:alert(1)", ORIGINS)).toBe(false);
    expect(webLink("//example.com", ORIGINS)).toBe(false);
  });

  it("makes ids safe and unique", () => {
    const { root } = view(
      '<div><h2 id="h-ok">a</h2><h2 id="h-Ünï">b</h2><h2 id="h-ok-1">c</h2><a id="fnref1:1">x</a><h3 id="h-…">d</h3></div>',
    );
    const ids = idsOf(root, new Map());
    expect([...ids.values()]).toEqual(["h-ok", "h-uni", "h-ok-1", "fnref1-1", "h"]);
  });

  it("finds maths, and the bare links whose titles it needs", () => {
    expect(hasMaths(view(article(markdown("$x$"))).root)).toBe(true);
    expect(hasMaths(view(article(markdown("x"))).root)).toBe(false);
    const { root } = view(
      article(markdown("[[a-b]] [See c](/p/c) [[d|D]] http://scrap.example/p/e")),
    );
    expect(bareSlugs(root)).toEqual(["a-b", "e"]);
  });

  it("uses the shared root's first element", () => {
    expect(first(parse("<p><b>x</b></p>"), "b")?.nodeName).toBe("B");
  });
});
