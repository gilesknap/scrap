import { expect, it } from "vitest";
import { textPart } from "../src/textpart";

it("sends no base_rev or body for a change that is not to the text", () => {
  expect(textPart(false, 3, "text")).toEqual({});
});

it("sends base_rev and body when the title or text changed", () => {
  expect(textPart(true, 3, "text")).toEqual({ base_rev: 3, body: "text" });
});
