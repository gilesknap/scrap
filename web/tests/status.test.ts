import { expect, it } from "vitest";
import { chipOf, dueOf, pageChip, partly, snoozed, statusOf, ticks, today } from "../src/status";

it("gives todos and Laters a status, open if they have none, and nothing else one", () => {
  expect(statusOf("todo", { status: "in_progress" })).toBe("in_progress");
  expect(statusOf("consume", { subtype: "read", status: "done" })).toBe("done");
  expect(statusOf("todo", {})).toBe("open");
  expect(statusOf("note", { status: "done" })).toBeNull(); // kept from a todo it was
  expect(statusOf("whiteboard", undefined)).toBeNull();
});

it("offers Mark done while open or in progress, only Reopen once done or cancelled", () => {
  expect(ticks("open")).toEqual([["Mark done", "done"]]);
  expect(ticks("in_progress")).toEqual([["Mark done", "done"]]);
  expect(ticks("done")).toEqual([["Reopen", "open"]]);
  expect(ticks("cancelled")).toEqual([["Reopen", "open"]]);
  expect(ticks(null)).toEqual([]);
});

it("chips a row only with a status that ends it (its icon says its kind)", () => {
  expect(chipOf("todo", { status: "open" })).toBe("");
  expect(chipOf("todo", { status: "in_progress" })).toBe("");
  expect(chipOf("todo", { status: "done" })).toBe("done");
  expect(chipOf("todo", { status: "cancelled" })).toBe("cancelled");
  expect(chipOf("consume", { status: "cancelled" })).toBe("cancelled");
  expect(chipOf("consume", {})).toBe("");
  expect(chipOf("note", { status: "done" })).toBe(""); // kept from a todo it was
  expect(chipOf("whiteboard", undefined)).toBe("");
});

it("chips a page with its kind, and its status if it has one", () => {
  expect(pageChip("Todo", "todo", { status: "open" })).toBe("Todo · open");
  expect(pageChip("Todo", "todo", {})).toBe("Todo · open");
  expect(pageChip("Todo", "todo", { status: "in_progress" })).toBe("Todo · in progress");
  expect(pageChip("Later", "consume", { status: "done" })).toBe("Later · done");
  expect(pageChip("Todo", "todo", { status: "cancelled" })).toBe("Todo · cancelled");
  expect(pageChip("Note", "note", { status: "done" })).toBe("Note");
  expect(pageChip("Board", "whiteboard", undefined)).toBe("Board");
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
  expect(dueOf(todo(null, "high"), now)).toEqual(["high", "due"]);
  expect(dueOf(todo("2026-10-21", "low"), now)).toEqual(["low · due today", "due"]);
  const [late, overdue] = dueOf(todo("2026-10-20"), now) ?? [];
  expect([late?.startsWith("overdue "), overdue]).toEqual([true, "due late"]);
  expect(late).toMatch(/20/);
  // Done or cancelled: greyed, its date kept and said as a date, never today or overdue
  expect(dueOf(todo("2026-10-20", null, "done"), now)?.[1]).toBe("due closed");
  expect(dueOf(todo("2026-10-20", null, "cancelled"), now)?.[0]).toMatch(/^due \D*\d/);
  expect(dueOf(todo("2026-10-21", "high", "done"), now)).toEqual([
    `high · due ${new Date("2026-10-21T12:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}`,
    "due closed",
  ]);
  expect(dueOf(todo("2027-01-02"), now)?.[0]).toMatch(/2027/); // another year: said
  // Snoozed: said after the rest, until its day (and not once done)
  const nap = { ...todo("2026-10-30", "low"), snoozed_until: "2026-10-25" };
  expect(dueOf(nap, now)?.[0]).toMatch(/^low · due \S+.* · snoozed till \S/);
  expect(dueOf({ ...todo(null), snoozed_until: "2026-10-25" }, now)?.[0]).toMatch(/^snoozed till /);
  expect(dueOf({ ...nap, snoozed_until: now }, now)?.[0]).not.toMatch(/snoozed/);
  expect(snoozed({ ...nap, fields: { status: "done" } }, now)).toBe(false);
  // Task boxes: "2 of 5" while some (not all) are ticked; not once it is done
  const boxes = (done: number, total: number, status = "open") => ({
    ...todo(null, null, status),
    tasks: { done, total },
  });
  expect(dueOf(boxes(2, 5), now)?.[0]).toBe("2 of 5");
  expect(partly(boxes(0, 5))).toBe(false);
  expect(partly(boxes(5, 5))).toBe(false);
  expect(dueOf(boxes(2, 5, "done"), now)).toBeNull();
  expect(dueOf({ ...boxes(1, 2), priority: "high" }, now)?.[0]).toBe("high · 1 of 2");
  expect(dueOf(todo("2026-11-02"), now)?.[0]).not.toMatch(/2026/);
});
