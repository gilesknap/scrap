import { describe, expect, it } from "vitest";
import { sections } from "../src/groups";
import { groupBy, served, ungrouped, withGroup } from "../src/terms";

const T = "2026-10-21";
const at = "2026-10-01T00:00:00Z";
const page = (
  title: string,
  kind: string,
  fields: Record<string, string> = {},
  tags: string[] = [],
) => ({
  title,
  kind,
  fields,
  tags,
  due: null,
  priority: null,
  snoozed_until: null,
  updated_at: at,
});
const said = (s: { label: string; items: { title: string }[] }[]) =>
  s.map((x) => `${x.label}: ${x.items.map((i) => i.title).join(", ")}`);

describe("group: in the query", () => {
  it("reads the grouping asked for, where it applies", () => {
    expect(groupBy("tag:person group:letter")).toBe("letter");
    expect(groupBy("tag:person group:tag")).toBe("tag");
    expect(groupBy("person group:tag")).toBeNull(); // no tag filter
    expect(groupBy("kind:later group:type")).toBe("type");
    expect(groupBy("kind:later kind:note group:type")).toBeNull();
    expect(groupBy("kind:later group:none")).toBeNull();
  });
  it("defaults Later alone to Type and Todos alone to Now", () => {
    expect(groupBy("kind:later")).toBe("type");
    expect(groupBy("kind:todo is:open")).toBe("now");
    expect(groupBy("kind:later kind:note")).toBeNull();
    expect(groupBy("tag:person")).toBeNull();
  });
  it("writes a grouping, the list's own as no word", () => {
    expect(withGroup("kind:later", "none")).toBe("kind:later group:none");
    expect(withGroup("kind:later group:none", "type")).toBe("kind:later");
    expect(withGroup("tag:person group:tag", "letter")).toBe("tag:person group:letter");
    expect(withGroup("tag:person group:letter", "none")).toBe("tag:person");
  });
  it("never sends group: to the server, and sorts A–Z groups A–Z", () => {
    expect(ungrouped("tag:person group:tag x")).toBe("tag:person x");
    expect(served("tag:person group:letter")).toBe("tag:person sort:title");
    expect(served("tag:person group:letter sort:created")).toBe("tag:person sort:created");
    expect(served("kind:later")).toBe("kind:later");
  });
});

describe("sections", () => {
  it("by letter: alphabetical, others under # at the end, each in the list's order", () => {
    const list = [
      page("bob", "note"),
      page("Ana", "note"),
      page("Émile", "note"),
      page("4x4", "note"),
      page("Abe", "note"),
    ];
    expect(said(sections("letter", list))).toEqual(["A: Ana, Abe", "B: bob", "E: Émile", "#: 4x4"]);
  });
  it("by tag: a section per sub-tag, alphabetically, Other last", () => {
    const list = [
      page("Ann", "note", {}, ["person/work"]),
      page("Bo", "note", {}, ["person"]),
      page("Cy", "note", {}, ["person/family/kids", "person/work"]),
      page("Di", "note", {}, ["person/family"]),
    ];
    expect(said(sections("tag", list, { tag: "person" }))).toEqual([
      "family: Cy, Di",
      "work: Ann",
      "Other: Bo",
    ]);
  });
  it("by type: read, watch, listen, play, then Done folded", () => {
    const list = [
      page("Film", "consume", { subtype: "watch" }),
      page("Game", "consume", { subtype: "play" }),
      page("Book", "consume", { subtype: "read" }),
      page("Old", "consume", { subtype: "read", status: "done" }),
      page("Pod", "consume", { subtype: "listen" }),
    ];
    const s = sections("type", list);
    expect(said(s)).toEqual([
      "To read: Book",
      "To watch: Film",
      "To listen: Pod",
      "To play: Game",
      "Done: Old",
    ]);
    expect(s.at(-1)).toMatchObject({ fold: true, open: false });
    // all done: the fold is open, not one closed line
    expect(sections("type", [list[3]])[0]).toMatchObject({ fold: true, open: true });
  });
  it("by Now: the Todos screen's sections, snoozed, then Done", () => {
    const todo = (title: string, extra: object) => ({
      ...page(title, "todo", { status: "open" }),
      ...extra,
    });
    const list = [
      todo("late", { due: "2026-10-01" }),
      todo("rest", {}),
      todo("asleep", { snoozed_until: "2026-11-01" }),
      { ...todo("did", {}), fields: { status: "done" } },
    ];
    expect(said(sections("now", list, { today: T }))).toEqual([
      "Overdue: late",
      "Open: rest",
      "Snoozed: asleep",
      "Done: did",
    ]);
  });
});
