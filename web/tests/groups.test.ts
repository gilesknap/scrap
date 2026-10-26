import { describe, expect, it } from "vitest";
import { dueBound, dueMeets, duesIn } from "../src/dues";
import { byArea, sections } from "../src/groups";
import { withGroup } from "../src/termedit";
import { groupBy, groupDefault, served, ungrouped } from "../src/terms";

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
  it("sends the server the group in force, once", () => {
    expect(ungrouped("tag:person group:tag x")).toBe("tag:person x");
    expect(served("tag:person group:letter")).toBe("tag:person group:letter");
    expect(served("tag:person group:letter sort:created")).toBe(
      "tag:person sort:created group:letter",
    );
    expect(served("kind:later")).toBe("kind:later group:type");
    expect(served("kind:later group:none")).toBe("kind:later");
    expect(served("group:tag x")).toBe("x");
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
    // each type says its later: value, for its heading's search
    expect(s.map((x) => x.key)).toEqual(["read", "watch", "listen", "play", undefined]);
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

describe("group:due", () => {
  const todo = (title: string, due: string | null, status = "open") => ({
    ...page(title, "todo", { status }),
    due,
  });
  it("applies to Todos alone, beside Now (still their own)", () => {
    expect(groupBy("kind:todo group:due")).toBe("due");
    expect(groupBy("kind:todo")).toBe("now");
    expect(groupBy("kind:later group:due")).toBeNull();
    expect(groupBy("tag:home group:due")).toBeNull();
    expect(withGroup("kind:todo", "due")).toBe("kind:todo group:due");
  });
  it("sections by when due, soonest first in each, then Done folded", () => {
    const list = [
      todo("no date", null),
      todo("in 2 weeks", "2026-11-04"),
      todo("in 5 days", "2026-10-26"),
      todo("in 3 days", "2026-10-24"),
      todo("tomorrow", "2026-10-22"),
      todo("today", T),
      todo("late", "2026-10-20"),
      todo("later late", "2026-10-01"),
      todo("did", "2026-10-22", "done"),
      todo("week's end", "2026-10-28"),
    ];
    const s = sections("due", list, { today: T });
    expect(said(s)).toEqual([
      "Overdue: later late, late",
      "Today: today",
      "Tomorrow: tomorrow",
      "This week: in 3 days, in 5 days, week's end",
      "Later: in 2 weeks",
      "No date: no date",
      "Done: did",
    ]);
    expect(s.at(-1)).toMatchObject({ fold: true, open: false });
  });
});

describe("due: from today", () => {
  it("reads days, weeks and months from today, as after: takes them", () => {
    expect(dueBound("<=7d", T)).toEqual(["<=", "2026-10-28"]);
    expect(dueBound("<1w", T)).toEqual(["<", "2026-10-28"]);
    expect(dueBound(">=2w", T)).toEqual([">=", "2026-11-04"]);
    expect(dueBound("<=m", T)).toEqual(["<=", "2026-11-20"]);
    expect(dueBound(">today", T)).toEqual([">", T]);
    expect(dueBound("tomorrow", T)).toEqual(["=", "2026-10-22"]);
    expect(dueBound("2026-12-01", T)).toEqual(["=", "2026-12-01"]);
    expect(dueBound("none", T)).toBe("none");
    for (const bad of ["<=0d", "<=101d", "<=1000d", "soon", "<none", "<=7x"])
      expect(dueBound(bad, T)).toBeNull();
  });
  it("matches a due day, or none", () => {
    expect(dueMeets("<=7d", "2026-10-28", T)).toBe(true);
    expect(dueMeets("<=7d", "2026-10-29", T)).toBe(false);
    expect(dueMeets(">today", T, T)).toBe(false);
    expect(dueMeets("none", null, T)).toBe(true);
    expect(dueMeets("<=7d", null, T)).toBe(false);
    expect(duesIn("kind:todo due:>today -due:none due:<=7d")).toEqual([">today", "<=7d"]);
  });
});

it("groups topics by area, the biggest first and Other last, by default for is:topic", () => {
  expect(groupDefault("is:topic")).toBe("area");
  expect(groupDefault("is:topic garden")).toBe("area");
  expect(groupDefault("-is:topic")).toBe(null);
  expect(groupDefault("is:topic kind:note")).toBe(null);
  expect(groupBy("is:topic group:area")).toBe("area");
  expect(groupBy("kind:note group:area")).toBe(null);
  expect(groupBy("is:topic group:none")).toBe(null);
  const t = (title: string, area: string | null) => ({ title, area });
  const secs = byArea([t("a", null), t("b", "home"), t("c", "scrap"), t("d", "scrap")]);
  expect(secs.map((s) => [s.label, s.items.map((x) => x.title)])).toEqual([
    ["scrap", ["c", "d"]],
    ["home", ["b"]],
    ["Other", ["a"]],
  ]);
});
