import { describe, expect, it } from "vitest";
import { type Change, checkbox, enter, inCode } from "../src/listedit";

/** The text after a change, with | at the caret (or «..» around a selection). */
function after(text: string, c: Change | null) {
  if (!c) return null;
  const t = text.slice(0, c.from) + c.insert + text.slice(c.to);
  return c.start === c.end
    ? `${t.slice(0, c.start)}|${t.slice(c.start)}`
    : `${t.slice(0, c.start)}«${t.slice(c.start, c.end)}»${t.slice(c.end)}`;
}
/** Enter at the | in text. */
const press = (s: string) => {
  const at = s.indexOf("|");
  const text = s.replace("|", "");
  return after(text, enter(text, at, at));
};
/** Checkbox over the selection «..» (or at |) in text. */
function tick(s: string) {
  const a = s.indexOf("«");
  if (a >= 0) {
    const b = s.indexOf("»") - 1;
    const text = s.replace("«", "").replace("»", "");
    return after(text, checkbox(text, a, b));
  }
  const at = s.indexOf("|");
  const text = s.replace("|", "");
  return after(text, checkbox(text, at, at));
}

describe("Enter on a list", () => {
  it("continues bullets, numbers and task boxes, with their indent", () => {
    expect(press("- milk|")).toBe("- milk\n- |");
    expect(press("* milk|")).toBe("* milk\n* |");
    expect(press("  + nested|")).toBe("  + nested\n  + |");
    expect(press("1. one|")).toBe("1. one\n2. |");
    expect(press("9) nine|")).toBe("9) nine\n10) |");
    expect(press("- [ ] tent|")).toBe("- [ ] tent\n- [ ] |");
    expect(press("- [x] tent|")).toBe("- [x] tent\n- [ ] |"); // a new one is never ticked
    expect(press("3. [X] done|")).toBe("3. [X] done\n4. [ ] |");
    expect(press("> - quoted|")).toBe("> - quoted\n> - |");
  });
  it("splits an item at the caret", () => {
    expect(press("- milk| and eggs")).toBe("- milk\n- | and eggs");
  });
  it("ends the list on an empty item: its marker goes", () => {
    expect(press("- milk\n- |")).toBe("- milk\n|");
    expect(press("- [ ] tent\n- [ ] |")).toBe("- [ ] tent\n|");
    expect(press("1. one\n2. |")).toBe("1. one\n|");
    // In a quote: the quote stays, the caret after it, not before the >
    expect(press("> - milk\n> - |")).toBe("> - milk\n> |");
    expect(press("> > 1. one\n> > 2. |")).toBe("> > 1. one\n> > |");
  });
  it("leaves plain text, code and a caret before the marker alone", () => {
    expect(press("just text|")).toBeNull();
    expect(press("-not a bullet|")).toBeNull();
    expect(press("|- milk")).toBeNull();
    expect(press("```\n- in code|")).toBeNull();
    expect(press("```\ncode\n```\n- after|")).toBe("```\ncode\n```\n- after\n- |");
  });
  it("knows a fenced block's end by its own fence", () => {
    expect(inCode("~~~\n```\n- x", 10)).toBe(true);
    expect(inCode("````\n```\n````\n- x", 15)).toBe(false);
    // A closing fence has nothing after it: ```js inside a block is its text
    expect(inCode("```\n```js\n- x", 11)).toBe(true);
    expect(inCode("```\ncode\n```  \n- x", 15)).toBe(false);
    // Indented fences count (a fence in a list item)
    expect(inCode("- a\n  ```\n  - x", 13)).toBe(true);
  });
});

describe("the Checkbox button", () => {
  it("makes a line a task, keeping a bullet's or a number's marker", () => {
    expect(tick("buy milk|")).toBe("- [ ] buy milk|");
    expect(tick("- buy milk|")).toBe("- [ ] buy milk|");
    expect(tick("2. step|")).toBe("2. [ ] step|");
    expect(tick("  indented|")).toBe("  - [ ] indented|");
    expect(tick("|")).toBe("- [ ] |"); // an empty line: a new box
  });
  it("takes the box off a task again", () => {
    expect(tick("- [ ] buy milk|")).toBe("- buy milk|");
    expect(tick("- [x] done|")).toBe("- done|");
  });
  it("does every line selected, and back", () => {
    expect(tick("x\n«a\n\nb»\ny")).toBe("x\n«- [ ] a\n\n- [ ] b»\ny");
    expect(tick("«- [ ] a\n- [x] b»")).toBe("«- a\n- b»");
    expect(tick("«- [ ] a\nb»")).toBe("«- [ ] a\n- [ ] b»"); // not all tasks: all become one
  });
});
