import { expect, it } from "vitest";
import { untitled } from "../src/page";

it("blanks a first line that only says the title again, keeping the line", () => {
  expect(untitled("Buy milk", "Buy milk")).toBe("");
  expect(untitled("Buy milk\n- [ ] oat", "Buy milk")).toBe("\n- [ ] oat"); // lines keep numbers
  expect(untitled("# Trip notes\nday one", "Trip notes")).toBe("\nday one"); // a heading's #s
  expect(untitled("   ### Trip notes  \nday one", "Trip notes")).toBe("\nday one");
});

it("keeps a first line that says more, or something else", () => {
  expect(untitled("Buy milk and eggs\nx", "Buy milk")).toBe("Buy milk and eggs\nx");
  expect(untitled("#hashtag line\nx", "hashtag line")).toBe("#hashtag line\nx"); // no heading
  expect(untitled("    # code\nx", "code")).toBe("    # code\nx"); // indented 4: code
  expect(untitled("#\nx", "#")).toBe("#\nx"); // an empty heading says nothing
  expect(untitled("", "Untitled")).toBe("");
});
