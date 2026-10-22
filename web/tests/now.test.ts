import { expect, it } from "vitest";
import { after, now, upcoming } from "../src/now";

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
      "Open",
      ["rest high later", "in progress", "rest medium no date", "rest low soon", "rest none"],
    ],
  ]);
});

it("leaves out empty groups", () => {
  expect(titles(now([todo("only", null, null)], T))).toEqual([["Open", ["only"]]]);
  expect(now([todo("done", T, "high", "done")], T)).toEqual([]);
});

it("lists open todos due from tomorrow to a week away, soonest first", () => {
  const week = [
    ...list,
    todo("in a week", "2026-10-28", null),
    todo("in 8 days", "2026-10-29", null),
  ];
  expect(upcoming(week, T).map((t) => t.title)).toEqual([
    "in progress",
    "rest low soon",
    "in a week",
  ]); // not "rest high later" (30 Nov), nor 8 days on
});

it("leaves snoozed todos out of Now and Upcoming until their day", () => {
  const snoozing = [
    { ...todo("asleep late", "2026-10-01", "high"), snoozed_until: "2026-10-25" },
    { ...todo("asleep soon", "2026-10-23", null), snoozed_until: "2026-10-22" },
    { ...todo("woken", "2026-10-02", null), snoozed_until: T }, // its day: back
  ];
  expect(titles(now(snoozing, T))).toEqual([["Overdue", ["woken"]]]);
  expect(upcoming(snoozing, T)).toEqual([]);
  expect(upcoming(snoozing, "2026-10-22").map((t) => t.title)).toEqual(["asleep soon"]);
});

it("counts days on the calendar, across months, years and clock changes", () => {
  expect(after("2026-10-21", 7)).toBe("2026-10-28");
  expect(after("2026-10-28", 7)).toBe("2026-11-04"); // the clocks go back on 25 Oct
  expect(after("2026-12-29", 7)).toBe("2027-01-05");
  expect(after("2028-02-28", 1)).toBe("2028-02-29");
});
