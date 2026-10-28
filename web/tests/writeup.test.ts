import { expect, it } from "vitest";
import type { CurrentWriteup, Page, Writeup } from "../src/api";
import { byline, OUTDATED, outdatedLine, stateText, writing } from "../src/writeup";

const w = (over: Partial<Writeup>): Writeup => ({
  board: true,
  on: true,
  guidance: null,
  state: null,
  error: null,
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

it("says who wrote a write-up and when", () => {
  const v: CurrentWriteup = {
    producer: "claude-opus-5-5",
    created_at: "2026-10-25T10:04:00.000Z",
    prompt_version: "writeup@abc",
    summary: "s",
    text: "t",
    guidance: null,
  };
  expect(byline(v)).toMatch(/^Claude · [^·]+$/);
  expect(byline({ ...v, producer: "local-model" })).toMatch(/^local-model · /);
});

it("says a current write-up is outdated, only when it is and nothing is under way", () => {
  const up = { summary: "s" } as CurrentWriteup;
  expect(outdatedLine(w({ outdated: true, current: up }))).toBe(OUTDATED);
  expect(outdatedLine(w({ outdated: false, current: up }))).toBeNull();
  expect(outdatedLine(w({ outdated: true, current: null }))).toBeNull();
  expect(outdatedLine(w({ outdated: true, current: up, state: "queued" }))).toBeNull();
  expect(outdatedLine(w({ current: up }))).toBeNull(); // an older server: no flag
});
