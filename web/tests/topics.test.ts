import { afterEach, expect, it } from "vitest";
import type { Source, TopicRow } from "../src/api";
import { kindWord, ordered } from "../src/topic";
import { changed, groups, look, matches, said, seen } from "../src/topics";

/** A localStorage that keeps what is set, as a phone's would. */
function storage() {
  const m = new Map<string, string>();
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, String(v)),
    removeItem: (k: string) => void m.delete(k),
  } as Storage;
  return m;
}
afterEach(() => {
  delete (globalThis as { localStorage?: Storage }).localStorage;
});

const row = (id: string, over: Partial<TopicRow> = {}): TopicRow => ({
  id,
  slug: id,
  title: id,
  summary: "",
  sources: 3,
  updated_at: "2026-10-25T10:00:00Z",
  area: "epics",
  ...over,
});

it("groups topics by area in the server's order, no area as Other, last", () => {
  const rows = [
    row("a", { area: "epics" }),
    row("b", { area: "home" }),
    row("c", { area: "epics" }),
    row("d", { area: null }),
  ];
  expect(groups(rows).map(([area, rs]) => [area, rs.map((r) => r.id)])).toEqual([
    ["epics", ["a", "c"]],
    ["home", ["b"]],
    ["Other", ["d"]],
  ]);
  expect(groups([])).toEqual([]);
});

it("filters by every word typed, in the title, summary or area, case aside", () => {
  const r = row("x", { title: "RTEMS IOCs", summary: "Booting over the network", area: "work" });
  expect(matches(r, "")).toBe(true);
  expect(matches(r, "rtems")).toBe(true);
  expect(matches(r, "ioc NETWORK")).toBe(true);
  expect(matches(r, "work")).toBe(true);
  expect(matches(r, "rtems linux")).toBe(false);
});

it("says how many sources and when", () => {
  expect(said(row("x", { sources: 1 }))).toMatch(/^1 source · /);
  expect(said(row("x", { sources: 4 }))).toMatch(/^4 sources · /);
});

it("dots the topics new or changed since this device last looked, none the first time", () => {
  const m = storage();
  const before = [row("a"), row("b")];
  expect(seen()).toBeNull();
  expect(changed(before, seen())).toEqual(new Set()); // never looked: no wall of dots
  look(before);
  expect(JSON.parse(m.get("scrap.topics.seen") ?? "")).toEqual({
    a: "2026-10-25T10:00:00Z",
    b: "2026-10-25T10:00:00Z",
  });
  const after = [row("a", { updated_at: "2026-10-26T10:00:00Z" }), row("b"), row("c")];
  expect(changed(after, seen())).toEqual(new Set(["a", "c"]));
  m.set("scrap.topics.seen", "[1]"); // something else kept there: as never looked
  expect(seen()).toBeNull();
  m.set("scrap.topics.seen", "{"); // not JSON
  expect(seen()).toBeNull();
});

it("keeps nothing and never throws without storage", () => {
  expect(seen()).toBeNull();
  expect(() => look([row("a")])).not.toThrow();
});

it("lists a topic's sources in, then those taken out, each kind in a word", () => {
  const s = (id: string, excluded: number, kind = "note"): Source => ({
    id,
    slug: id,
    title: id,
    kind,
    added_by: "claude",
    added_at: "",
    excluded,
  });
  expect(ordered([s("a", 1), s("b", 0), s("c", 0)]).map((x) => x.id)).toEqual(["b", "c", "a"]);
  expect(kindWord("note")).toBe("Note");
  expect(kindWord("consume")).toBe("Later");
  expect(kindWord("whiteboard")).toBe("Board");
  expect(kindWord("reference")).toBe("Reference");
});
