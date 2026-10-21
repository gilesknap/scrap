import { expect, it } from "vitest";
import { suggested as withBoxes } from "../src/boxes";
import { KINDS, suggested, toSend } from "../src/kinds";

it("suggests Read for a link on its own, else Note", () => {
  expect(suggested("https://example.com/a")).toBe("consume");
  expect(suggested("  http://e.com/x?y=1 \n")).toBe("consume");
  expect(suggested("read https://example.com/a")).toBe("note");
  expect(suggested("https://a.com https://b.com")).toBe("note");
  expect(suggested("ftp://e.com")).toBe("note");
  expect(suggested("")).toBe("note");
});

it("sends a kind the user picked, Note too, so it is kept", () => {
  expect(toSend("note", true, "note")).toBe("note"); // chosen over a suggested Read
  expect(toSend("todo", true, "todo")).toBe("todo");
});

it("sends an unpicked kind only when it changes the page", () => {
  expect(toSend("note", false, "note")).toBeUndefined(); // the untouched default: unfixed
  expect(toSend("consume", false, "note")).toBe("consume"); // a suggested Read
  expect(toSend("todo", false, "todo")).toBeUndefined(); // an edit that left it alone
});

it("offers five kinds with short labels and full names", () => {
  expect(KINDS.map(([k, label, name]) => [k, label, name])).toEqual([
    ["note", "Note", "Note"],
    ["todo", "Todo", "Todo"],
    ["consume", "Read", "Read"],
    ["whiteboard", "Board", "Whiteboard"],
    ["document", "Doc", "Document"],
  ]);
});

it("suggests Todo for text with task boxes, as saving would file it", () => {
  expect(withBoxes("Packing\n\n- [ ] socks")).toBe("todo");
  expect(withBoxes("> 1. [x] done")).toBe("todo");
  expect(withBoxes("[ ] not a list item")).toBe("note");
  expect(withBoxes("- \\[ ] escaped")).toBe("note");
  expect(withBoxes("https://example.com")).toBe("consume");
});
