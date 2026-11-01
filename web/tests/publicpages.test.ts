// Public pages' parts in the app (#497): the warning before a page goes public, Refresh all's
// question, the Public chip and the dates line, and the calls to scrap.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Page } from "../src/api";
import { type FakeNode, fakeDocument } from "./fakedom";
import { dropStorage, storage } from "./helpers";

vi.stubGlobal("document", fakeDocument());
const { ask, firstTime, goesWith, warning } = await import("../src/publicask");
const { publicChip, publishedLine, publishing } = await import("../src/pagehead");
const api = await import("../src/publicapi");
const { ApiError } = await import("../src/api");

const page = (o: Partial<Page> = {}): Page =>
  ({
    id: "P1",
    slug: "my-page",
    title: "My page",
    kind: "note",
    tags: ["work", "personal/family"],
    captures: [
      {
        id: "C1",
        url: null,
        source: "pwa",
        blobs: [
          { sha256: "a".repeat(64), mime: "image/jpeg", size: 1, filename: "IMG_1.jpg" },
          { sha256: "b".repeat(64), mime: "application/pdf", size: 1, filename: "spec.pdf" },
          { sha256: "c".repeat(64), mime: "text/markdown", size: 1, filename: "notes.md" },
        ],
      },
    ],
    public: true,
    published_at: null,
    ...o,
  }) as Page;

const textOf = (n: FakeNode) => n.textContent.replace(/\s+/g, " ").trim();

beforeEach(() => {
  vi.stubGlobal("document", fakeDocument());
  storage();
});
afterEach(() => dropStorage());

describe("the warning", () => {
  it("says what goes public with the page: its tags, Claude's text, its files by name", () => {
    expect(goesWith(page())).toEqual([
      "its tags: #work #personal/family",
      "Claude's write-up and summary",
      "its attached files: spec.pdf, notes.md",
    ]);
    expect(goesWith(page({ tags: [], captures: [] }))).toEqual(["Claude's write-up and summary"]);
    // A topic: its synthesis, drawn from its sources (S6)
    const topic = page({ tags: [], captures: [], topic: { key: "k", sources: [] } });
    expect(goesWith(topic)).toEqual([
      "Claude's write-up and summary",
      "Claude's synthesis, which draws on its source pages",
    ]);
    const one = page({
      captures: [{ ...page().captures[0], blobs: [page().captures[0].blobs[1]] }],
    });
    expect(goesWith(one).at(-1)).toBe("its attached file: spec.pdf");
  });

  it("lists the page's drawings, downloadable, only when its photos have any (#520)", () => {
    const drawn = (n: number) => {
      const blobs = page().captures[0].blobs.map((b, i) => ({
        ...b,
        ingest: i < n ? ({ drawing: { id: i + 1 } } as never) : null,
      }));
      return page({ captures: [{ ...page().captures[0], blobs }] });
    };
    expect(goesWith(drawn(0)).join("|")).not.toContain("drawing");
    expect(goesWith(drawn(1)).at(-1)).toBe("its 1 drawing, downloadable");
    expect(goesWith(drawn(2)).at(-1)).toBe("its 2 drawings, downloadable");
  });

  it("is a dialog with Cancel focused, the one amber button Make public", async () => {
    const asked = ask(warning(page(), "pages.example"));
    const d = (document as unknown as { body: FakeNode }).body.childNodes[0];
    expect(d.nodeName).toBe("DIALOG");
    expect(d.open).toBe(true);
    const text = textOf(d);
    expect(text).toContain("Make this page public?");
    expect(text).toContain("Anyone with the link can read it at pages.example.");
    expect(text).toContain("Links to private pages show their titles as plain text.");
    const [cancel, ok] = d.find("BUTTON");
    expect(textOf(cancel)).toBe("Cancel");
    expect(textOf(ok)).toBe("Make public");
    expect(ok.className).toBe("primary");
    expect(cancel.className).not.toBe("primary");
    expect((document as unknown as { activeElement: FakeNode }).activeElement).toBe(cancel);
    cancel.onclick?.();
    expect(await asked).toBe(false);
    expect(d.parentNode).toBeNull(); // gone
  });

  it("resolves true for Make public, false for Escape or a tap outside", async () => {
    let asked = ask(warning(page(), "x"));
    let d = (document as unknown as { body: FakeNode }).body.childNodes[0];
    d.find("BUTTON")[1].onclick?.();
    expect(await asked).toBe(true);
    asked = ask(warning(page(), "x"));
    d = (document as unknown as { body: FakeNode }).body.childNodes[0];
    expect(d.fire("cancel")).toBe(false); // Escape: not the browser's close, ours
    expect(await asked).toBe(false);
    asked = ask(warning(page(), "x"));
    d = (document as unknown as { body: FakeNode }).body.childNodes[0];
    d.fire("click", d); // the backdrop
    expect(await asked).toBe(false);
  });

  it("lists the pages Refresh all would publish for the first time", () => {
    const q = firstTime([
      { id: "1", slug: "a", title: "Alpha", published_at: null },
      { id: "2", slug: "b", title: "Beta", published_at: null },
    ]);
    expect(q.lines[0]).toEqual(["These pages will go public for the first time:"]);
    expect(q.list).toEqual(["Alpha", "Beta"]);
    expect(q.ok).toBe("OK");
  });
});

describe("the Public chip and the dates line", () => {
  it("says when it was published, Publishing… meanwhile, or not yet", () => {
    expect(publishedLine(page())).toBe("Public · not published yet");
    expect(publishedLine(page({ published_at: "2026-11-01T14:02:00Z" }))).toMatch(/^Published /);
    publishing.add("P1");
    expect(publishedLine(page({ published_at: "2026-11-01T14:02:00Z" }))).toBe("Publishing…");
    publishing.delete("P1");
  });

  it("is a globe and Public, linking to the page on the public site", () => {
    const chip = publicChip(
      page({ published_at: "2026-11-01T14:02:00Z", public_url: "https://pages.example/p/my-page" }),
    );
    expect(chip.nodeName).toBe("A");
    expect(chip.className).toBe("pubchip");
    const c = chip as unknown as FakeNode;
    expect(c.href).toBe("https://pages.example/p/my-page");
    expect(c.target).toBe("_blank");
    expect(textOf(c)).toBe("Public");
    expect(c.childNodes[0].nodeName).toBe("SVG");
    expect(chip.getAttribute("aria-label")).toMatch(
      /^Public\. Published .*: pages\.example\/p\/my-page$/,
    );
  });

  it("is plain when scrap gives no address (no SCRAP_PUBLISH_SITE)", () => {
    const plain = publicChip(page());
    expect(plain.nodeName).toBe("SPAN");
    expect(plain.getAttribute("aria-label")).toBe(
      "Public. Public · not published yet: the public site",
    );
  });
});

describe("the calls to scrap", () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const reply = (status: number, data: unknown) =>
    new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal("dispatchEvent", () => true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        if (url.endsWith("/published"))
          return reply(200, {
            url: "https://pages.example/p/my-page",
            published_at: "t",
            files: 2,
          });
        if (url.startsWith("/api/public/rebuild")) return reply(200, { units: ["home"] });
        if (url.startsWith("/api/public")) return reply(200, []);
        return reply(200, page());
      }),
    );
  });

  it("publishes with the html, base_rev and defer", async () => {
    const r = await api.publishPage("P1", "<!DOCTYPE html>", 7, true);
    expect(r.files).toBe(2);
    expect(calls[0].url).toBe("/api/pages/P1/published");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      html: "<!DOCTYPE html>",
      base_rev: 7,
      defer: true,
    });
    expect(api.siteName({ site: "https://pages.example" })).toBe("pages.example");
    expect(api.siteName({ site: null })).toBe("the public site");
  });

  it("lists the public pages, or those linking to one; sets the flag; rebuilds", async () => {
    await api.publicPages();
    await api.publicPages("a b");
    await api.setPublic("P1", false);
    await api.rebuild();
    expect(calls.map((c) => `${c.init?.method ?? "GET"} ${c.url}`)).toEqual([
      "GET /api/public",
      "GET /api/public?links_to=a%20b",
      "PATCH /api/pages/P1",
      "POST /api/public/rebuild",
    ]);
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({ public: false });
  });

  it("draws again for a stale revision or tags, and says why a publish failed", () => {
    const e = (status: number, error?: string, detail = "why") =>
      new ApiError(status, { error, detail });
    expect(api.redraw(e(409, "stale"))).toBe(true);
    expect(api.redraw(e(422, "stale_tags"))).toBe(true);
    expect(api.redraw(e(409, "not_public"))).toBe(false);
    expect(api.redraw(e(422, "bad_href"))).toBe(false);
    expect(api.whyNot(e(409, "not_public"))).toBe("the page isn't public any more");
    expect(api.whyNot(e(422, "bad_href", "an href to /api/x is not allowed"))).toBe(
      "an href to /api/x is not allowed",
    );
    expect(api.whyNot(e(502, "publish_failed", "over_quota"))).toBe(
      "the public site refused it (over_quota)",
    );
    expect(api.whyNot(e(503, "not_configured"))).toBe("publishing is off on this server");
    expect(api.whyNot(new TypeError("Failed to fetch"), false)).toBe("you're offline");
    expect(api.unreached(new TypeError("x"))).toBe(true);
  });
});
