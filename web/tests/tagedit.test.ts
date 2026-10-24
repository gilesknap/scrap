import { expect, it } from "vitest";
import { clean, MAX_TAG, MAX_TAGS, same, tagProblem } from "../src/tagedit";

it("cleans a tag as the server does", () => {
  expect(clean("  #Garden   Tools ")).toBe("garden tools");
  expect(clean("##a/B")).toBe("a/b");
  expect(clean(" # ")).toBe("");
});

it("compares tags in any order", () => {
  expect(same(["a", "b"], ["b", "a"])).toBe(true);
  expect(same(["a"], ["a", "b"])).toBe(false);
  expect(same([], [])).toBe(true);
});

it("finds tags the server would refuse, before the composer queues them", () => {
  expect(tagProblem([])).toBeUndefined();
  expect(tagProblem(["a".repeat(MAX_TAG), "b"])).toBeUndefined();
  expect(tagProblem(["ok", "a".repeat(MAX_TAG + 1)])).toMatch(/at most 64 characters/);
  // characters as the server counts them: code points, not UTF-16 units
  expect(tagProblem(["\u{1F600}".repeat(MAX_TAG)])).toBeUndefined();
  const many = Array.from({ length: MAX_TAGS }, (_, i) => `t${i}`);
  expect(tagProblem(many)).toBeUndefined();
  expect(tagProblem([...many, "one more"])).toMatch(/At most 64 tags/);
});

it("merges a draft's tag changes onto the page's tags now", async () => {
  const { mergeTags } = await import("../src/tagedit");
  // set elsewhere: kept; the draft's add and removal applied
  expect(mergeTags(["a", "b", "claude"], ["a", "b"], ["a", "new"])).toEqual(["a", "claude", "new"]);
  expect(mergeTags(["a"], ["a"], ["a"])).toEqual(["a"]);
  expect(mergeTags(["a", "new"], ["a"], ["a", "new"])).toEqual(["a", "new"]);
});
