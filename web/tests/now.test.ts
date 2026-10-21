import { expect, it } from "vitest";
import { now, upcoming } from "../src/now";

const T = "2026-10-21";
let n = 0;
const todo = (title: string, due: string | null, priority: string | null, status = "open") => ({
  title,
  kind: "todo",
  fields: { status },
  due,
  priority,
  updated_at: new Date(Date.UTC(2026, 9, 1, 0, ++n)).toISOString(), // later ones edited last
});

const list = [
  todo("rest low soon", "2026-10-25", "low"),
  todo("late newer due", "2026-10-20", null),
  todo("late oldest due", "2026-10-01", "low"),
  todo("today low", T, "low"),
  todo("today high", T, "high"),
  todo("high no date, older", null, "high"),
  todo("high no date, newer", null, "high"),
  todo("rest high later", "2026-11-30", "high"),
  todo("rest none", null, null),
  todo("rest medium no date", null, "medium"),
  todo("done late", "2026-10-02", "high", "done"),
  todo("cancelled", T, "high", "cancelled"),
  todo("in progress", "2026-10-22", "medium", "in_progress"),
];
const titles = (g: [string, { title: string }[]][]) =>
  g.map(([k, ts]) => [k, ts.map((t) => t.title)]);

it("ranks open todos: overdue oldest first, today, high with no date, then the rest", () => {
  expect(titles(now(list, T))).toEqual([
    ["Overdue", ["late oldest due", "late newer due"]],
    ["Today", ["today high", "today low"]],
    ["High priority", ["high no date, newer", "high no date, older"]],
    [
      "Later",
      ["rest high later", "in progress", "rest medium no date", "rest low soon", "rest none"],
    ],
  ]);
});

it("leaves out empty groups", () => {
  expect(titles(now([todo("only", null, null)], T))).toEqual([["Later", ["only"]]]);
  expect(now([todo("done", T, "high", "done")], T)).toEqual([]);
});

it("lists open todos due after today, soonest first", () => {
  expect(upcoming(list, T).map((t) => t.title)).toEqual([
    "in progress",
    "rest low soon",
    "rest high later",
  ]);
});
