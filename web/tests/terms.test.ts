import { describe, expect, it } from "vitest";
import { day, sortsIn, unsorted } from "../src/filters";
import { removing } from "../src/termedit";
import { adding, has, kindsIn, listing, token, unkinded, withKind } from "../src/terms";

it("writes a filter, quoting a value with spaces", () => {
  expect(token("tag", "tech/epics")).toBe("tag:tech/epics");
  expect(token("tag", "two odd words")).toBe('tag:"two odd words"');
  // the query has no escape for a quote: a tag with one is asked for by what the parser keeps
  expect(token("tag", 'a/b"c')).toBe("tag:a");
  expect(token("tag", 'a/b/c"d/e')).toBe("tag:a/b");
  expect(token("tag", 'say "hi" now')).toBe("say hi now");
  expect(token("tag", '"')).toBe("");
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
  expect(unsorted("zephyr -sort:created kind:todo sort:due")).toBe("zephyr kind:todo");
});

it("reads orders the way the server does: any case, - or !, quotes are text", () => {
  expect(sortsIn("zephyr Sort:due")).toEqual(["Sort:due"]);
  expect(sortsIn("a -SORT:x !sort:title")).toEqual(["-SORT:x", "!sort:title"]);
  expect(unsorted("zephyr Sort:due kind:todo")).toBe("zephyr kind:todo");
  expect(unsorted("-SORT:x")).toBe("");
  // a phrase is text, sort: and all
  expect(sortsIn('"fix sort:due bug"')).toEqual([]);
  expect(unsorted('"fix  sort:due bug" sort:title')).toBe('"fix  sort:due bug"');
  expect(sortsIn('"foo sort:due"')).toEqual([]);
  expect(sortsIn('-"foo sort:due" x')).toEqual([]);
  // an unbalanced quote runs to the end
  expect(sortsIn('a "foo sort:due')).toEqual([]);
  expect(sortsIn('sort:due a "b sort:title')).toEqual(["sort:due"]);
  // a word ends at a quote; a quoted value is part of the order
  expect(sortsIn('sort:due"x sort:y"')).toEqual(["sort:due"]);
  expect(unsorted('a sort:"due" b')).toBe("a b");
  expect(sortsIn("--sort:x sort tsort:x")).toEqual([]);
  expect(sortsIn("a\x01sort:due b")).toEqual(["sort:due"]); // a control character: a space
});

it("clamps a picked date to what after: and before: take", () => {
  expect(day("2026-03-01")).toBe("2026-03-01");
  expect(day("0001-01-01")).toBe("0001-01-01");
  expect(day("10000-01-01")).toBe("9999-12-31");
  expect(day("+275760-09-13")).toBe("9999-12-31");
  expect(day("")).toBe("");
  expect(day("junk")).toBe("");
  // a 10-character date that is no day passes through (the server answers nothing for it)
  expect(day("2026-02-30")).toBe("2026-02-30");
  expect(day("2026-13-45")).toBe("2026-13-45");
});

describe("the kind row", () => {
  it("leaves kind: inside a quoted phrase alone", () => {
    expect(unkinded('"see kind:todo here" kind:todo')).toBe('"see kind:todo here"');
    expect(unkinded('kind:"x y" kind:note')).toBe('kind:"x y"');
    expect(kindsIn('"a kind:todo b"')).toEqual([]);
    expect(listing('"a kind:todo b"')).toBeNull();
    expect(withKind('"a kind:todo b" kind:note', "later")).toBe('"a kind:todo b" kind:later');
  });

  it("sets a kind with one tap, and clears it with another", () => {
    expect(withKind("", "todo")).toBe("kind:todo");
    expect(withKind("kind:todo", "todo")).toBe("");
    expect(withKind("milk kind:todo", "later")).toBe("milk kind:later");
    expect(withKind("kind:consume tag:x", "later")).toBe("tag:x"); // what the server takes too
    expect(withKind("kind:read tag:x", "later")).toBe("tag:x"); // the old name too
  });
  it("All clears every kind but a not one", () => {
    expect(withKind("kind:todo kind:note -kind:doc x", "")).toBe("-kind:doc x");
    expect(kindsIn("-kind:todo")).toEqual([]);
  });
  it("lists newest first for nothing or a kind alone, else searches", () => {
    expect(listing("")).toBe("");
    expect(listing("kind:board")).toBe("kind=whiteboard");
    expect(listing("kind:later")).toBe("kind=consume");
    expect(listing("kind:read")).toBe("kind=consume");
    expect(listing("kind:todo kind:read")).toBeNull();
    expect(listing("kind:todo milk")).toBeNull();
    expect(listing("tag:x")).toBeNull();
  });
});

it("knows the kind row's kinds in any case, as the server does", () => {
  expect(kindsIn("kind:Todo garden").map(([, v]) => v)).toEqual(["todo"]);
  expect(kindsIn("KIND:CONSUME").map(([, v]) => v)).toEqual(["later"]);
  expect(kindsIn("kind:Read").map(([, v]) => v)).toEqual(["later"]);
  expect(withKind("garden kind:Todo", "note")).toBe("garden kind:note");
  expect(withKind("kind:TODO", "todo")).toBe(""); // tapping the one that is on clears it
  expect(listing("Kind:Todo")).toBe("kind=todo");
});
