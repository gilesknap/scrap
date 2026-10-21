import { expect, it } from "vitest";
import { clean, same } from "../src/tagedit";

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
