import { readFileSync } from "node:fs";
import { afterEach, expect, it } from "vitest";
import { COLUMN_KEY, COLUMNS, columnWidth } from "../src/column";

/** A localStorage holding one column width, as a computer's would. */
function keep(v?: string) {
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => (k === COLUMN_KEY && v !== undefined ? v : null),
  } as Storage;
}
afterEach(() => {
  delete (globalThis as { localStorage?: Storage }).localStorage;
});

it("is 800 (the default) when nothing or junk is kept", () => {
  keep();
  expect(columnWidth()).toBe("800");
  for (const junk of ["", "abc", "0", "719", "721", "961", "-1", "800px"]) {
    keep(junk);
    expect(columnWidth(), junk).toBe("800");
  }
});

it("reads every width Settings offers", () => {
  for (const [v] of COLUMNS) {
    keep(v);
    expect(columnWidth()).toBe(v);
  }
});

it("theme-init.js validates every non-default width Settings offers, before the first paint", () => {
  const widths = COLUMNS.filter(([k]) => k !== "800").map(([k]) => k);
  expect(widths).toEqual(["720", "880", "960"]);
  const text = readFileSync("public/theme-init.js", "utf8");
  for (const w of widths) expect(text, `theme-init.js misses ${w}`).toContain(w);
});

it("main.ts reapplies the kept width too, at the start and when the app comes back", () => {
  const text = readFileSync("src/main.ts", "utf8");
  expect(text).toContain(COLUMN_KEY);
  expect(text).toContain("--column");
});
