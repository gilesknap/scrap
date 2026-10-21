import { describe, expect, it } from "vitest";
import {
  adding,
  day,
  has,
  kindsIn,
  listing,
  removing,
  sortsIn,
  token,
  tree,
  withKind,
} from "../src/terms";

it("writes a filter, quoting a value with spaces", () => {
  expect(token("tag", "tech/epics")).toBe("tag:tech/epics");
  expect(token("tag", 'two "odd" words')).toBe('tag:"two odd words"');
});

it("adds a token once, at the end", () => {
  expect(adding("garden ", "kind:todo")).toBe("garden kind:todo");
  expect(adding("", "tag:x")).toBe("tag:x");
  expect(adding("tag:x garden", "tag:x")).toBe("tag:x garden");
  expect(adding("tag:xy", "tag:x")).toBe("tag:xy tag:x"); // only a whole token counts
});

it("removes a whole token and tidies the spaces", () => {
  expect(removing("garden  tag:x  shed", "tag:x")).toBe("garden shed");
  expect(removing("tag:xy tag:x", "tag:x")).toBe("tag:xy");
  expect(removing("-tag:x tag:x", "tag:x")).toBe("-tag:x");
  expect(removing("garden", "tag:x")).toBe("garden");
  expect(removing("a", "")).toBe("a");
  expect(has('a tag:"b c"', 'tag:"b c"')).toBe(true);
});

it("finds the orders a query has, to replace them all", () => {
  expect(sortsIn("zephyr kind:todo -sort:created")).toEqual(["-sort:created"]);
  expect(sortsIn("sort:due a -sort:title")).toEqual(["sort:due", "-sort:title"]);
  expect(sortsIn("resort:x mysort:y")).toEqual([]);
  const q = "zephyr -sort:created kind:todo sort:due";
  expect(sortsIn(q).reduce(removing, q)).toBe("zephyr kind:todo");
});

it("makes a tree of tags, parents first", () => {
  const t = tree([
    ["home", 3],
    ["home-x", 1],
    ["home/garden", 2],
    ["home/garden/diy", 1],
    ["work", 1],
  ]);
  expect(t.map((n) => n.path)).toEqual(["home", "home-x", "work"]);
  expect(t[0].kids.map((n) => [n.name, n.n])).toEqual([["garden", 2]]);
  expect(t[0].kids[0].kids[0].path).toBe("home/garden/diy");
});

it("clamps a picked date to what after: and before: take", () => {
  expect(day("2026-03-01")).toBe("2026-03-01");
  expect(day("0001-01-01")).toBe("0001-01-01");
  expect(day("10000-01-01")).toBe("9999-12-31");
  expect(day("+275760-09-13")).toBe("9999-12-31");
  expect(day("")).toBe("");
  expect(day("junk")).toBe("");
});

describe("the kind row", () => {
  it("sets a kind with one tap, and clears it with another", () => {
    expect(withKind("", "todo")).toBe("kind:todo");
    expect(withKind("kind:todo", "todo")).toBe("");
    expect(withKind("milk kind:todo", "read")).toBe("milk kind:read");
    expect(withKind("kind:consume tag:x", "read")).toBe("tag:x"); // what the server takes too
  });
  it("All clears every kind but a not one", () => {
    expect(withKind("kind:todo kind:note -kind:doc x", "")).toBe("-kind:doc x");
    expect(kindsIn("-kind:todo")).toEqual([]);
  });
  it("lists newest first for nothing or a kind alone, else searches", () => {
    expect(listing("")).toBe("");
    expect(listing("kind:board")).toBe("kind=whiteboard");
    expect(listing("kind:read")).toBe("kind=consume");
    expect(listing("kind:todo kind:read")).toBeNull();
    expect(listing("kind:todo milk")).toBeNull();
    expect(listing("tag:x")).toBeNull();
  });
});

it("knows the kind row's kinds in any case, as the server does", () => {
  expect(kindsIn("kind:Todo garden").map(([, v]) => v)).toEqual(["todo"]);
  expect(kindsIn("KIND:CONSUME").map(([, v]) => v)).toEqual(["read"]);
  expect(withKind("garden kind:Todo", "note")).toBe("garden kind:note");
  expect(withKind("kind:TODO", "todo")).toBe(""); // tapping the one that is on clears it
  expect(listing("Kind:Todo")).toBe("kind=todo");
});
