import { afterEach, expect, it } from "vitest";
import { TEXT_KEY, textSize } from "../src/textsize";

/** A localStorage holding one text size, as a phone's would. */
function keep(v?: string) {
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => (k === TEXT_KEY && v !== undefined ? v : null),
  } as Storage;
}
afterEach(() => {
  delete (globalThis as { localStorage?: Storage }).localStorage;
});

it("is the phone's (null) when nothing, junk or an out-of-range size is kept", () => {
  keep();
  expect(textSize()).toBeNull();
  for (const junk of ["", "abc", "NaN", "0", "0.79", "1.31", "2", "-1"]) {
    keep(junk);
    expect(textSize(), junk).toBeNull();
  }
});

it("reads the five percentages, and 1 is 100%, and 1 is 100%, not the phone's", () => {
  for (const v of [0.8, 0.9, 1, 1.15, 1.3]) {
    keep(String(v));
    expect(textSize()).toBe(v);
  }
});
