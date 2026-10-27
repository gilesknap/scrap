import { expect, it } from "vitest";
import { edited, metaParts } from "../src/pagemeta";
import { dueChip } from "../src/status";
import { tagNames } from "../src/tagname";

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
const d = (day: string) =>
  new Date(`${day}T12:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

it("says a Later's kind, medium and what it is for, and a status only when not open", () => {
  const later = page("consume", { fields: { media_type: "tv", subtype: "watch", status: "open" } });
  expect(metaParts(later, "Later", now)).toEqual(["Later", "TV", "to watch"]);
  const done = page("consume", { fields: { media_type: "book", subtype: "read", status: "done" } });
  expect(metaParts(done, "Later", now)).toEqual(["Later", "Book", "read"]); // not "to read · done"
  expect(metaParts(page("note"), "Note", now)).toEqual(["Note"]);
  expect(metaParts(page("topic"), undefined, now)).toEqual([]);
});

it("leaves a todo's due day and priority to its chip, keeping its snooze and tasks", () => {
  const late = page("todo", { due: "2026-10-24", priority: "high", fields: { status: "open" } });
  expect(metaParts(late, "Todo", now)).toEqual(["Todo"]);
  const busy = page("todo", {
    due: "2026-10-30",
    snoozed_until: "2026-10-28",
    tasks: { done: 1, total: 3 },
    fields: { status: "in_progress" },
  });
  expect(metaParts(busy, "Todo", now)).toEqual([
    "Todo",
    "in progress",
    `snoozed till ${d("2026-10-28")}`,
    "1 of 3",
  ]);
});

it("counts a page as edited only a minute or more after it was made", () => {
  expect(edited(page("note"))).toBe(false);
  expect(edited(page("note", { updated_at: "2026-10-26T12:00:40" }))).toBe(false);
  expect(edited(page("note", { updated_at: "2026-10-26T12:05:00" }))).toBe(true);
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

it("names a page's tags by their last part, with enough path to tell them apart", () => {
  const names = tagNames(["kind/project-management", "tools/developer-portal", "tech/epics/thoth"]);
  expect([...names.values()]).toEqual(["project-management", "developer-portal", "thoth"]);
  const same = tagNames(["tech/epics/thoth", "other/thoth", "garden"]);
  expect([...same.values()]).toEqual(["epics/thoth", "other/thoth", "garden"]);
  expect(tagNames(["a/b/c", "x/b/c"]).get("x/b/c")).toBe("x/b/c");
  // A tag with no slash beside a slashed one that ends the same: only the slashed one grows
  expect([...tagNames(["a/b", "b"]).values()]).toEqual(["a/b", "b"]);
  expect([...tagNames(["café/crème", "bar/crème", "日本/語"]).values()]).toEqual([
    "café/crème",
    "bar/crème",
    "語",
  ]);
});
