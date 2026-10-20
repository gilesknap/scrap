import { expect, it } from "vitest";
import { placeIn, swipeStep } from "../src/gesture";

it("reads a quick sideways flick as next (left) or previous (right)", () => {
  expect(swipeStep(-80, 10, 200, 400)).toBe(1);
  expect(swipeStep(80, -10, 200, 400)).toBe(-1);
});

it("reads a slow drag a third of the way across as a swipe", () => {
  expect(swipeStep(-140, 0, 1500, 400)).toBe(1);
  expect(swipeStep(-120, 0, 1500, 400)).toBe(0); // not far enough to count when slow
});

it("ignores taps, scrolls, diagonals and short drags", () => {
  expect(swipeStep(5, 3, 100, 400)).toBe(0); // a tap
  expect(swipeStep(-60, 0, 200, 400)).toBe(0); // too short
  expect(swipeStep(-20, -300, 300, 400)).toBe(0); // a scroll
  expect(swipeStep(-150, 80, 200, 400)).toBe(0); // more diagonal than sideways
});

it("finds a page's neighbours in its trail", () => {
  const t = { label: "Recent", slugs: ["a", "b", "c"] };
  expect(placeIn(t, "b")).toEqual({ i: 1, n: 3, prev: "a", next: "c" });
  expect(placeIn(t, "a")).toMatchObject({ prev: undefined, next: "b" });
  expect(placeIn(t, "c")).toMatchObject({ prev: "b", next: undefined });
  expect(placeIn(t, "z")).toBeNull();
  expect(placeIn(null, "a")).toBeNull();
});
