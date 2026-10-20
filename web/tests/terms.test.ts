import { expect, it } from "vitest";
import { adding, has, removing, token, tree } from "../src/terms";

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
