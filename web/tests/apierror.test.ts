import { expect, it } from "vitest";
import { ApiError } from "../src/api";

it("shows a validation error's first message, not [object Object]", () => {
  const detail = [{ type: "x", loc: ["body", "due"], msg: "Input should be a date" }];
  expect(new ApiError(422, { detail }).message).toBe("due: Input should be a date");
  expect(new ApiError(422, { detail: [{ msg: "bad" }] }).message).toBe("bad");
});

it("keeps a string detail and falls back for other shapes", () => {
  expect(new ApiError(409, { detail: "Changed elsewhere" }).message).toBe("Changed elsewhere");
  expect(new ApiError(500, { detail: [] }).message).toBe("HTTP 500");
  expect(new ApiError(500, { detail: [7] }).message).toBe("HTTP 500");
  expect(new ApiError(500, {}).message).toBe("HTTP 500");
});
