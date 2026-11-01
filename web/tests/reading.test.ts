// "Claude's reading" (#521): one closed fold under a photo or file (reading.ts), the file card
// built with it (filecard.ts), where the reading is up to outside the fold, and which images
// are Claude's own (claudemade.ts: nothing under them, and no reading in the Make public
// warning).
import { describe, expect, it, vi } from "vitest";
import type { Page } from "../src/api";
import { type FakeNode, fakeDocument } from "./fakedom";
import { pdf } from "./helpers";

vi.mock("../src/css/reading.css", () => ({}));
vi.mock("../src/css/publicpages.css", () => ({}));
vi.mock("../src/app", () => ({ rerender: () => {} }));
vi.mock("../src/icons", () => ({ icon: () => "" }));
vi.stubGlobal("document", fakeDocument());
const { READING, readingFold, readingState } = await import("../src/reading");
const { fileCard } = await import("../src/filecard");
const { claudeMade } = await import("../src/claudemade");
const { goesWith, readingsOn } = await import("../src/publicask");

const node = (x: unknown) => x as FakeNode;
const one = (n: FakeNode, name: string) => n.find(name)[0];
const noop = () => {};

describe("the reading fold", () => {
  it("is one closed details, labelled Claude's reading, with Regenerate inside at its end", () => {
    const f = node(
      readingFold({ body: ["what it read"], regen: { label: "Regenerate", onclick: noop } }),
    );
    expect(f.className).toBe("reading");
    const details = one(f, "DETAILS");
    expect(details.className).toBe("reading-fold");
    expect(details.open).toBe(false);
    expect(one(details, "SUMMARY").textContent).toBe(READING);
    expect(READING).toBe("Claude's reading");
    const card = details.childNodes[1];
    expect(card.className).toBe("claude");
    expect(card.textContent).toBe("what it readRegenerate");
    const button = one(card, "BUTTON");
    expect(button.className).toBe("link"); // quiet
    expect(card.childNodes.at(-1)?.className).toBe("regen-row");
  });

  it("makes Generate, the first time, a full button, and runs onOpen only when opened", () => {
    const opened = vi.fn();
    const f = node(
      readingFold({
        body: [null, false, "x"],
        regen: { label: "Generate", onclick: noop },
        onOpen: opened,
      }),
    );
    const details = one(f, "DETAILS");
    expect(one(details, "BUTTON").className).toBe("");
    details.fire("toggle");
    expect(opened).not.toHaveBeenCalled();
    details.open = true;
    details.fire("toggle");
    expect(opened).toHaveBeenCalledOnce();
  });

  it("puts where the reading is up to outside, as words with its action", () => {
    const s = node(readingState("Failed: overloaded", "failed", { label: "Retry", onclick: noop }));
    expect(s.className).toBe("reading-state");
    expect(one(s, "SPAN").className).toBe("state failed");
    expect(one(s, "SPAN").role).toBe("status");
    expect(one(s, "BUTTON").textContent).toBe("Retry");
    expect(s.find("DETAILS")).toEqual([]);
  });
});

describe("the file card", () => {
  const card = (ingest: ReturnType<typeof pdf> | null) =>
    node(
      fileCard({
        cid: "CAP1",
        blob: {
          sha256: "c".repeat(64),
          mime: "application/pdf",
          size: 9,
          filename: "spec.pdf",
          ingest,
        },
        row: document.createElement("div"),
        refresh: noop,
      }),
    );

  it("folds what was read, with the PDF's text marked for publishing", () => {
    const c = card(pdf({}));
    const details = one(c, "DETAILS");
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("12 pages · Searchable");
    const pre = one(details, "PRE");
    expect(pre.className).toBe("filetext");
    expect(pre.getAttribute("data-cid")).toBe("CAP1");
    expect(pre.getAttribute("data-sha")).toBe("c".repeat(64));
    expect(c.find("SPAN").filter((s) => s.className.startsWith("state"))).toEqual([]);
  });

  it("says a failure outside the fold, with Retry, and has no fold then", () => {
    const c = card(pdf({ state: "failed", error: "timeout" }));
    expect(c.find("DETAILS")).toEqual([]);
    expect(one(c, "BUTTON").textContent).toBe("Retry");
  });

  it("puts Generate in the fold for a file never read", () => {
    const c = card(null);
    expect(one(one(c, "DETAILS"), "BUTTON").textContent).toBe("Generate");
  });
});

const blob = (sha: string, ingest: unknown = null, mime = "image/svg+xml") => ({
  sha256: sha.repeat(64),
  mime,
  size: 1,
  filename: `${sha}.svg`,
  ingest,
});
const cap = (id: string, source: string, author: string, blobs: unknown[]) => ({
  id,
  url: null,
  source,
  author,
  blobs,
});
const read = {
  state: "done",
  failures: 0,
  error: null,
  text: "AC = 13",
  description: "A triangle",
  image_kind: "diagram",
  drawing: null,
};

describe("Claude's own images", () => {
  it("are those only Claude's MCP captures hold: one the owner's capture holds too is read", () => {
    const p = {
      captures: [
        cap("A", "mcp", "claude", [blob("a"), blob("b")]),
        cap("B", "pwa", "you", [blob("b")]),
        cap("C", "mcp", "you", [blob("c")]),
      ],
    } as unknown as Page;
    expect([...claudeMade(p)]).toEqual(["a".repeat(64)]);
  });

  it("leave the reading out of the Make public warning, even one read before #521", () => {
    const base = { tags: [], removed: [] } as unknown as Page;
    const claude = { ...base, captures: [cap("A", "mcp", "claude", [blob("a", read)])] } as Page;
    expect(readingsOn(claude)).toBe(false);
    expect(goesWith(claude)).not.toContain("Claude's reading of its photos and files");
    const owner = { ...base, captures: [cap("A", "pwa", "you", [blob("a", read)])] } as Page;
    expect(readingsOn(owner)).toBe(true);
    expect(goesWith(owner)).toContain("Claude's reading of its photos and files");
    const gone = { ...owner, removed: ["a".repeat(64)] } as Page;
    expect(readingsOn(gone)).toBe(false);
  });

  it("count a PDF read with text as a reading, not a text file or one with none", () => {
    const files = (ingest: unknown, mime = "application/pdf") =>
      ({
        tags: [],
        removed: [],
        captures: [cap("A", "pwa", "you", [blob("d", ingest, mime)])],
      }) as unknown as Page;
    expect(readingsOn(files(pdf({})))).toBe(true);
    expect(readingsOn(files(pdf({ searchable: false })))).toBe(false);
    expect(readingsOn(files(pdf({ kind: "text" }), "text/plain"))).toBe(false);
    expect(readingsOn(files(pdf({ state: "failed" })))).toBe(false);
    expect(readingsOn(files(null))).toBe(false);
  });
});
