import { expect, it } from "vitest";
import { chipOf, statusOf, ticks } from "../src/status";

it("gives todos and Reads a status, open if they have none, and nothing else one", () => {
  expect(statusOf("todo", { status: "in_progress" })).toBe("in_progress");
  expect(statusOf("consume", { subtype: "read", status: "done" })).toBe("done");
  expect(statusOf("todo", {})).toBe("open");
  expect(statusOf("note", { status: "done" })).toBeNull(); // kept from a todo it was
  expect(statusOf("whiteboard", undefined)).toBeNull();
});

it("offers Done from any status but done, Reopen from done or cancelled", () => {
  expect(ticks("open")).toEqual([["Done", "done"]]);
  expect(ticks("in_progress")).toEqual([["Done", "done"]]);
  expect(ticks("done")).toEqual([["Reopen", "open"]]);
  expect(ticks("cancelled")).toEqual([
    ["Done", "done"],
    ["Reopen", "open"],
  ]);
  expect(ticks(null)).toEqual([]);
});

it("chips a row with a status that ends it, else its kind", () => {
  expect(chipOf("todo", { status: "open" })).toBe("todo");
  expect(chipOf("todo", { status: "in_progress" })).toBe("todo");
  expect(chipOf("todo", { status: "done" })).toBe("done");
  expect(chipOf("consume", { status: "cancelled" })).toBe("cancelled");
  expect(chipOf("consume", {})).toBe("read");
  expect(chipOf("note", { status: "done" })).toBe("");
});
