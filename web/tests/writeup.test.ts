import { expect, it } from "vitest";
import type { Page, Writeup, WriteupVersion } from "../src/api";
import { byline, stateText, writing } from "../src/writeup";

const w = (over: Partial<Writeup>): Writeup => ({
  board: true,
  on: true,
  guidance: null,
  state: null,
  error: null,
  versions: 0,
  current: null,
  ...over,
});

it("says what Claude is doing with the write-up, and nothing once done", () => {
  expect(stateText(w({ state: "queued" }))).toBe("Waiting for Claude");
  expect(stateText(w({ state: "queued", on: false }))).toBe("Waiting: Claude is off");
  expect(stateText(w({ state: "processing" }))).toBe("Claude is writing it…");
  expect(stateText(w({ state: "failed", error: "invalid: the write-up is empty" }))).toBe(
    "Claude couldn't write it: the write-up is empty",
  );
  expect(stateText(w({ state: "done" }))).toBeNull();
});

it("looks again only while one is on its way", () => {
  const page = (writeup: Writeup | null) => ({ id: "P", writeup }) as unknown as Page;
  expect(writing(page(w({ state: "queued" })))).toBe(true);
  expect(writing(page(w({ state: "queued", on: false })))).toBe(false);
  expect(writing(page(w({ state: "done" })))).toBe(false);
  expect(writing(page(null))).toBe(false);
});

it("says who wrote a version, when, and what it was restored from", () => {
  const v: WriteupVersion = {
    version: 3,
    producer: "claude-opus-5-5",
    created_at: "2026-10-25T10:04:00.000Z",
    prompt_version: "writeup@abc",
    summary: "s",
    text: "t",
    guidance: null,
    restored_from: 1,
  };
  expect(byline(v)).toMatch(/^claude-opus-5-5 · .+ · version 3 · restored from version 1$/);
  expect(byline({ ...v, restored_from: null })).toMatch(/ · version 3$/);
});
