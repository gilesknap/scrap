import { expect, it } from "vitest";
import { todoStart } from "../src/todoedit";

const page = { due: "2026-11-01", priority: "high" };

it("restores a draft's cleared due date and priority, not the page's", () => {
  expect(todoStart({ todo: { due: null, priority: null } }, page)).toEqual({
    due: null,
    priority: null,
  });
  expect(todoStart({ todo: { due: null, priority: "low" } }, page)).toEqual({
    due: null,
    priority: "low",
  });
});

it("starts from the page's when the draft kept none", () => {
  expect(todoStart(undefined, page)).toEqual(page);
  expect(todoStart({}, page)).toEqual(page);
  expect(todoStart(undefined, {})).toEqual({ due: null, priority: null });
});
