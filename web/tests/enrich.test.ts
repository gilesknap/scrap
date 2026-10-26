import { expect, it } from "vitest";
import type { Page } from "../src/api";
import { type Enrich, reading, relatedOf, stateText } from "../src/enrich";

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

it("leaves a topic's sources out of its Related: its Sources fold lists them", () => {
  const ref = (id: string, via = "topic") => ({ id, slug: id, title: id, kind: "note", via });
  const source = (id: string, excluded = 0) => ({
    ...ref(id),
    added_by: "claude",
    added_at: "2026-10-25T00:00:00Z",
    excluded,
  });
  const topic = page({
    related: [ref("a"), ref("b"), ref("c", "claude")],
    topic: { key: "ibek", sources: [source("a"), source("b", 1)] },
  });
  expect(relatedOf(topic).map((r) => r.id)).toEqual(["c"]);
  // A source page keeps the topic citing it
  expect(relatedOf(page({ related: [ref("t")] })).map((r) => r.id)).toEqual(["t"]);
});
