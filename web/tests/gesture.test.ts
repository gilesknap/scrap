import { expect, it } from "vitest";
import { placeIn, swipeStep } from "../src/gesture";

it("reads a quick sideways swipe as next (left) or previous (right)", () => {
  expect(swipeStep(-120, 10, 200)).toBe(1);
  expect(swipeStep(120, -10, 200)).toBe(-1);
});

it("ignores taps, scrolls, diagonals and slow drags", () => {
  expect(swipeStep(5, 3, 100)).toBe(0); // a tap
  expect(swipeStep(-60, 0, 200)).toBe(0); // too short
  expect(swipeStep(-20, -300, 300)).toBe(0); // a scroll
  expect(swipeStep(-120, 80, 200)).toBe(0); // more diagonal than sideways
  expect(swipeStep(-200, 0, 1500)).toBe(0); // slow: reading, selecting, dragging
});

it("finds a page's neighbours in its trail", () => {
  const t = { label: "Recent", slugs: ["a", "b", "c"] };
  expect(placeIn(t, "b")).toEqual({ i: 1, n: 3, prev: "a", next: "c" });
  expect(placeIn(t, "a")).toMatchObject({ prev: undefined, next: "b" });
  expect(placeIn(t, "c")).toMatchObject({ prev: "b", next: undefined });
  expect(placeIn(t, "z")).toBeNull();
  expect(placeIn(null, "a")).toBeNull();
});
