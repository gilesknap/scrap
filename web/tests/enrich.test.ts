import { expect, it } from "vitest";
import type { Page } from "../src/api";
import { did, type Enrich, reading, relatedOf, stateText } from "../src/enrich";

const e = (over: Partial<Enrich>): Enrich => ({
  on: true,
  state: null,
  error: null,
  summary: null,
  ...over,
});
const page = (over: Partial<Page>) => ({ id: "P", related: [], ...over }) as unknown as Page;

it("says what Claude is doing, and nothing once done", () => {
  expect(stateText(e({ state: "queued" }))).toBe("Waiting for Claude");
  expect(stateText(e({ state: "queued", on: false }))).toBe("Waiting: Claude is off");
  expect(stateText(e({ state: "processing" }))).toBe("Claude is reading it…");
  expect(stateText(e({ state: "failed", error: "content: the model refused" }))).toBe(
    "Claude couldn't read it: the model refused",
  );
  expect(stateText(e({ state: "paused", reason: "budget" }))).toBe(
    "Paused (budget): nothing is lost",
  );
  expect(stateText(e({ state: "paused" }))).toBe("Paused: nothing is lost");
  expect(stateText(e({ state: "done" }))).toBeNull();
  expect(stateText(e({}))).toBeNull();
});

it("says in a line what Claude did, so Regenerate says what it would redo", () => {
  const link = { id: "L", slug: "l", title: "L", kind: "note", via: "link" };
  const picked = { ...link, id: "C", via: "claude" };
  expect(did(page({}), false)).toBe(
    "Claude can summarise it, suggest tags and find related pages.",
  );
  expect(did(page({ enrich: e({ summary: "S" }) }), true)).toBe("Claude wrote the summary.");
  expect(did(page({ enrich: e({ summary: "S" }), related: [picked] }), true)).toBe(
    "Claude wrote the summary and found the related pages.",
  );
  expect(
    did(page({ enrich: e({ summary: "S" }), model_tags: ["a"], related: [picked] }), true),
  ).toBe("Claude wrote the summary, added the dashed tags and found the related pages.");
  // A page linking here is not Claude's find
  expect(did(page({ enrich: e({ state: "done" }), related: [link] }), true)).toBe(
    "Claude found nothing to add.",
  );
});

it("polls only while Claude has the page and is on", () => {
  expect(reading(page({ enrich: e({ state: "queued" }) }))).toBe(true);
  expect(reading(page({ enrich: e({ state: "processing" }) }))).toBe(true);
  expect(reading(page({ enrich: e({ state: "paused" }) }))).toBe(true);
  expect(reading(page({ enrich: e({ state: "done" }) }))).toBe(false);
  expect(reading(page({ enrich: e({ state: "queued", on: false }) }))).toBe(false);
  expect(reading(page({ enrich: null }))).toBe(false);
});

it("lists at most eight related pages", () => {
  const r = Array.from({ length: 10 }, (_, i) => ({
    id: `${i}`,
    slug: `s${i}`,
    title: `T${i}`,
    kind: "note",
    via: "claude",
  }));
  expect(relatedOf(page({ related: r }))).toHaveLength(8);
  expect(relatedOf(page({ related: undefined }))).toEqual([]);
});
