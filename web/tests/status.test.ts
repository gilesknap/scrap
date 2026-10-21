import { expect, it } from "vitest";
import { chipOf, dueOf, statusOf, ticks, today } from "../src/status";

it("gives todos and Reads a status, open if they have none, and nothing else one", () => {
  expect(statusOf("todo", { status: "in_progress" })).toBe("in_progress");
  expect(statusOf("consume", { subtype: "read", status: "done" })).toBe("done");
  expect(statusOf("todo", {})).toBe("open");
  expect(statusOf("note", { status: "done" })).toBeNull(); // kept from a todo it was
  expect(statusOf("whiteboard", undefined)).toBeNull();
});

it("offers Done from any status but done, Reopen from done or cancelled", () => {
  expect(ticks("open")).toEqual([["Done", "done"]]);
  expect(ticks("in_progress")).toEqual([["Done", "done"]]);
  expect(ticks("done")).toEqual([["Reopen", "open"]]);
  expect(ticks("cancelled")).toEqual([
    ["Done", "done"],
    ["Reopen", "open"],
  ]);
  expect(ticks(null)).toEqual([]);
});

it("chips a row with a status that ends it, else its kind", () => {
  expect(chipOf("todo", { status: "open" })).toBe("todo");
  expect(chipOf("todo", { status: "in_progress" })).toBe("todo");
  expect(chipOf("todo", { status: "done" })).toBe("done");
  expect(chipOf("consume", { status: "cancelled" })).toBe("cancelled");
  expect(chipOf("consume", {})).toBe("read");
  expect(chipOf("note", { status: "done" })).toBe("");
});

it("writes today as a due date is, on the device's calendar", () => {
  expect(today(new Date(2026, 9, 21, 23, 59))).toBe("2026-10-21");
  expect(today(new Date(2026, 0, 1, 0, 0))).toBe("2026-01-01");
});

it("says a todo's priority and due date, overdue only while it is not done", () => {
  const now = "2026-10-21";
  const todo = (due: string | null, priority: string | null = null, status = "open") => ({
    kind: "todo",
    fields: { status },
    due,
    priority,
  });
  expect(dueOf(todo(null), now)).toBeNull();
  expect(dueOf({ ...todo("2026-10-01"), kind: "note" }, now)).toBeNull();
  expect(dueOf(todo(null, "high"), now)).toEqual(["high", false]);
  expect(dueOf(todo("2026-10-21", "low"), now)).toEqual(["low · due today", false]);
  const [late, overdue] = dueOf(todo("2026-10-20"), now) ?? [];
  expect([late?.startsWith("overdue "), overdue]).toEqual([true, true]);
  expect(late).toMatch(/20/);
  expect(dueOf(todo("2026-10-20", null, "done"), now)?.[1]).toBe(false);
  expect(dueOf(todo("2026-10-20", null, "cancelled"), now)?.[0]).toMatch(/^due /);
  expect(dueOf(todo("2027-01-02"), now)?.[0]).toMatch(/2027/); // another year: said
  expect(dueOf(todo("2026-11-02"), now)?.[0]).not.toMatch(/2026/);
});
