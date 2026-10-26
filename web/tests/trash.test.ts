import { expect, it } from "vitest";
import { day, fate, stay, type Trashed } from "../src/trash";

const NOW = new Date("2026-10-26T12:00:00Z");
const page = (over: Partial<Trashed>): Trashed => ({
  id: "1",
  slug: "s",
  title: "T",
  kind: "note",
  deleted_at: "2026-10-20T09:00:00.000Z",
  topic: false,
  purge_at: "2026-11-19T09:00:00.000Z",
  ...over,
});

it("says when a page in the trash was deleted and when it goes for good", () => {
  const purge = day("2026-11-19T09:00:00.000Z", NOW);
  expect(fate(page({}), NOW)).toBe(
    `Deleted ${day("2026-10-20T09:00:00.000Z", NOW)} · deleted for good after ${purge}`,
  );
  expect(purge).not.toMatch(/2026/); // this year's dates have no year
  expect(day("2025-11-19T09:00:00.000Z", NOW)).toMatch(/2025/);
});

it("says a page past its date goes tonight, and a kept topic stays", () => {
  expect(fate(page({ purge_at: "2026-10-25T09:00:00.000Z" }), NOW)).toMatch(
    / · deleted for good tonight$/,
  );
  expect(fate(page({ topic: true, purge_at: null }), NOW)).toMatch(
    / · kept: Claude won't make this topic again$/,
  );
  expect(fate(page({ purge_at: null }), NOW)).toMatch(/^Deleted [^·]+$/); // purging off
});

it("says how long a page stays, or that it stays with purging off", () => {
  expect(stay(30)).toMatch(/^Deleted pages stay here for 30 days, then scrap deletes them/);
  expect(stay(null)).toBe("Deleted pages stay here until you restore them.");
});
