import { expect, it } from "vitest";
import { inDays, todoStart } from "../src/todoedit";

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

it("counts days on the phone's calendar, across a month's end and a clock change", () => {
  const at = new Date(2026, 9, 21, 23, 30); // late in the evening
  expect(inDays(0, at)).toBe("2026-10-21");
  expect(inDays(1, at)).toBe("2026-10-22");
  expect(inDays(7, at)).toBe("2026-10-28");
  expect(inDays(7, new Date(2026, 9, 28, 0, 15))).toBe("2026-11-04"); // over the clocks going back
});
