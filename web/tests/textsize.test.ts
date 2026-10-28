import { readFileSync } from "node:fs";
import { afterEach, expect, it } from "vitest";
import { SIZES, TEXT_KEY, textSize } from "../src/textsize";

/** A localStorage holding one text size, as a phone's would. */
function keep(v?: string) {
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => (k === TEXT_KEY && v !== undefined ? v : null),
  } as Storage;
}
afterEach(() => {
  delete (globalThis as { localStorage?: Storage }).localStorage;
});

it("is 100% (the default) when nothing or junk is kept", () => {
  keep();
  expect(textSize()).toBe("1");
  for (const junk of ["", "abc", "NaN", "0", "0.79", "1.31", "2", "-1", "0x1", "1e0", " 1"]) {
    keep(junk);
    expect(textSize(), junk).toBe("1");
  }
});

it("reads Phone and the percentages as kept", () => {
  for (const [v] of SIZES) {
    keep(v);
    expect(textSize()).toBe(v);
  }
});

it("main.ts and theme-init.js apply every percentage Settings offers", () => {
  const range = /n >= 0\.8 && n <= 1\.3/;
  for (const file of ["public/theme-init.js", "src/main.ts"])
    expect(readFileSync(file, "utf8"), file).toMatch(range);
  const pcts = SIZES.filter(([k]) => k !== "phone").map(([k]) => Number(k));
  expect(Math.min(...pcts)).toBe(0.8);
  expect(Math.max(...pcts)).toBe(1.3);
});
