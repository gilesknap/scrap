import { expect, it } from "vitest";
import { metaParts } from "../src/pagemeta";
import { dueChip } from "../src/status";

const now = "2026-10-26";
const at = "2026-10-26T12:00:00";
const page = (kind: string, more: object = {}) => ({
  kind,
  fields: {},
  created_at: at,
  updated_at: at,
  ...more,
});
/** A day as this machine's locale says it ("26 Oct" in en-GB, "Oct 26" in en-US). */
const d = (day: string, year = false) =>
  new Date(`${day}T12:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(year && { year: "numeric" }),
  });
const said = (parts: [string, boolean][]) => parts.map(([s]) => s).join(" · ");

it("says a Later's kind, medium and what it is for, then its day", () => {
  const later = page("consume", { fields: { media_type: "tv", subtype: "watch", status: "open" } });
  expect(said(metaParts(later, "Later", now))).toBe(`Later · TV · to watch · ${d(now)}`);
  const done = page("consume", { fields: { media_type: "book", subtype: "read", status: "done" } });
  expect(said(metaParts(done, "Later", now))).toBe(`Later · Book · to read · done · ${d(now)}`);
});

it("says a todo's priority and due day, only the overdue part marked", () => {
  const late = page("todo", { due: "2026-10-24", priority: "high", fields: { status: "open" } });
  const parts = metaParts(late, "Todo", now);
  expect(said(parts)).toBe(`Todo · high · overdue ${d("2026-10-24")} · ${d(now)}`);
  expect(parts.filter(([, l]) => l)).toEqual([[`overdue ${d("2026-10-24")}`, true]]);
  const soon = page("todo", { due: "2026-10-30", fields: { status: "in_progress" } });
  expect(said(metaParts(soon, "Todo", now))).toBe(
    `Todo · due ${d("2026-10-30")} · in progress · ${d(now)}`,
  );
});

it("gives both dates only when they fall on different days, with no times", () => {
  const edited = page("note", {
    created_at: "2026-10-12T09:00:00",
    updated_at: "2026-10-26T18:00:00",
  });
  expect(said(metaParts(edited, "Note", now))).toBe(
    `Note · added ${d("2026-10-12")} · edited ${d(now)}`,
  );
  const old = page("note", {
    created_at: "2025-03-02T09:00:00",
    updated_at: "2025-03-02T10:00:00",
  });
  expect(said(metaParts(old, "Note", now))).toBe(`Note · ${d("2025-03-02", true)}`);
  expect(said(metaParts(page("topic"), undefined, now))).toBe(d(now));
});

it("chips a todo's due day and priority, with whether it is overdue", () => {
  expect(dueChip({ kind: "todo", due: "2026-10-30", priority: "high" }, now)).toEqual([
    `${d("2026-10-30")} · high`,
    false,
  ]);
  expect(dueChip({ kind: "todo", due: "2026-10-24" }, now)).toEqual([d("2026-10-24"), true]);
  expect(dueChip({ kind: "todo", due: now }, now)).toEqual(["today", false]);
  expect(dueChip({ kind: "todo" }, now)).toBeNull();
});
