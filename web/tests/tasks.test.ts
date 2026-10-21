import { expect, it } from "vitest";
import { markdown } from "../src/render";
import { flip } from "../src/tasks";

/** The data-line of each box, as rendered: the line flip() changes. */
const lines = (text: string) =>
  [...markdown(text).matchAll(/data-line="(\d+)"/g)].map((m) => +m[1]);

it("flips the box on its own line, however many items say the same", () => {
  const text = "Shopping\n\n- [ ] milk\n- [ ] milk\n- [x] eggs";
  expect(lines(text)).toEqual([2, 3, 4]);
  expect(flip(text, 3, true)).toBe("Shopping\n\n- [ ] milk\n- [x] milk\n- [x] eggs");
  expect(flip(text, 4, false)).toBe("Shopping\n\n- [ ] milk\n- [ ] milk\n- [ ] eggs");
});

it("skips code: a box in a fence or an indented block is no box", () => {
  const text = "```\n- [ ] in code\n```\n\n    - [ ] indented code\n\n- [ ] real";
  expect(lines(text)).toEqual([6]);
  expect(flip(text, 6, true)).toBe(text.replace("- [ ] real", "- [x] real"));
});

it("finds boxes in numbered, nested and quoted lists, keeping their marks", () => {
  const text = "1. [ ] one\n   * [X] nested\n> - [ ] quoted\n2) [ ] two";
  expect(lines(text)).toEqual([0, 1, 2, 3]);
  expect(flip(text, 1, false)).toBe("1. [ ] one\n   * [ ] nested\n> - [ ] quoted\n2) [ ] two");
  expect(flip(text, 2, true)).toContain("> - [x] quoted");
  expect(flip(text, 3, true)).toContain("2) [x] two");
});

it("refuses a line that changed since it was drawn", () => {
  const text = "- [x] done";
  expect(flip(text, 0, true)).toBeNull(); // already ticked
  expect(flip(text, 5, true)).toBeNull(); // no such line
  expect(flip("- plain", 0, true)).toBeNull();
});
