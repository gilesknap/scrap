import { describe, expect, it } from "vitest";
import {
  bullet,
  type Change,
  checkbox,
  enter,
  inCode,
  indent,
  numbered,
  outdent,
} from "../src/listedit";

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
/** A key over the selection «..» (or at |) in text. */
function key(f: typeof checkbox, s: string) {
  const a = s.indexOf("«");
  if (a >= 0) {
    const b = s.indexOf("»") - 1;
    const text = s.replace("«", "").replace("»", "");
    return after(text, f(text, a, b));
  }
  const at = s.indexOf("|");
  const text = s.replace("|", "");
  return after(text, f(text, at, at));
}
const tick = (s: string) => key(checkbox, s);

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

describe("the Bullet key", () => {
  it("makes a line a bullet, a number or a task giving way to it", () => {
    expect(key(bullet, "milk|")).toBe("- milk|");
    expect(key(bullet, "|")).toBe("- |"); // an empty line: a new bullet
    expect(key(bullet, "1. one|")).toBe("- one|");
    expect(key(bullet, "- [ ] tent|")).toBe("- tent|");
    expect(key(bullet, "  nested|")).toBe("  - nested|"); // after its indent
    expect(key(bullet, "> quoted|")).toBe("> - quoted|");
  });
  it("makes a bullet a plain line again", () => {
    expect(key(bullet, "- milk|")).toBe("milk|");
  });
  it("does every line selected, a blank one between left alone, and back", () => {
    expect(key(bullet, "«a\n\nb»")).toBe("«- a\n\n- b»");
    expect(key(bullet, "«- a\n- b»")).toBe("«a\nb»");
    expect(key(bullet, "«- a\nb»")).toBe("«- a\n- b»"); // not all bullets: all become one
  });
});

describe("the Numbered key", () => {
  it("numbers a line, on from a number just above", () => {
    expect(key(numbered, "step|")).toBe("1. step|");
    expect(key(numbered, "|")).toBe("1. |");
    expect(key(numbered, "1. a\n|b")).toBe("1. a\n2. |b");
    expect(key(numbered, "- x|")).toBe("1. x|"); // a bullet's marker gives way
    expect(key(numbered, "- [ ] t|")).toBe("1. [ ] t|"); // a task keeps its box
  });
  it("numbers lines 1, 2, 3 in order at each indent", () => {
    expect(key(numbered, "«a\nb\nc»")).toBe("«1. a\n2. b\n3. c»");
    expect(key(numbered, "«a\n  b\n  c\nd»")).toBe("«1. a\n  1. b\n  2. c\n2. d»");
  });
  it("makes numbered lines plain again, a task a bulleted task", () => {
    expect(key(numbered, "«1. a\n2. b»")).toBe("«a\nb»");
    expect(key(numbered, "«1. [ ] t\n2. u»")).toBe("«- [ ] t\nu»");
  });
});

describe("the Indent and Outdent keys", () => {
  it("nest an item at its parent's text column: 2 under a bullet, 3 under a number", () => {
    expect(key(indent, "- a\n- b|")).toBe("- a\n  - b|");
    expect(key(indent, "- a\n- [ ] b|")).toBe("- a\n  - [ ] b|");
    expect(key(indent, "1. a\n2. b|")).toBe("1. a\n   1. b|"); // renumbered in its new list
    expect(key(indent, "1. [ ] a\n2. [ ] b|")).toBe("1. [ ] a\n   1. [ ] b|"); // not the box's
    expect(key(indent, "1. a\n   1. b\n2. c|")).toBe("1. a\n   1. b\n   2. c|");
    expect(key(indent, "- a\n\n  more\n- b|")).toBe("- a\n\n  more\n  - b|");
  });
  it("with no item above, indent by the line's own marker, or 2", () => {
    expect(key(indent, "- a|")).toBe("  - a|");
    expect(key(indent, "1. a|")).toBe("   1. a|");
    expect(key(indent, "plain|")).toBe("  plain|");
    expect(key(indent, "|")).toBe("  |");
  });
  it("indent every line selected, numbering each in its new place", () => {
    expect(key(indent, "«- a\n- b»")).toBe("«  - a\n  - b»");
    expect(key(indent, "1. a\n«2. b\n3. c»")).toBe("1. a\n«   1. b\n   2. c»");
  });
  it("outdent to the parent's indent, renumbered on from the list it rejoins", () => {
    expect(key(outdent, "- a\n  - b|")).toBe("- a\n- b|");
    expect(key(outdent, "1. a\n   1. b|")).toBe("1. a\n2. b|");
    expect(key(outdent, "1. a\n2. b\n   1. c|")).toBe("1. a\n2. b\n3. c|");
    expect(key(outdent, "1. a\n   1. b\n   2. c|")).toBe("1. a\n   1. b\n2. c|");
    expect(key(outdent, "«- a\n  - b\n  - c»")).toBe("«- a\n- b\n- c»");
    expect(key(outdent, "1. a\n«   1. b\n   2. c»")).toBe("1. a\n«2. b\n3. c»");
  });
  it("outdent never past a line's start, nor into a quote's marker", () => {
    expect(key(outdent, "- a|")).toBe("- a|");
    expect(key(outdent, "  a|")).toBe("a|");
    expect(key(outdent, " a|")).toBe("a|");
    expect(key(outdent, "|")).toBe("|");
    expect(key(outdent, "> - a|")).toBe("> - a|");
    expect(key(outdent, "> > - a|")).toBe("> > - a|");
    expect(key(outdent, "> - a\n>   - b|")).toBe("> - a\n> - b|");
  });
  it("round-trip: Outdent undoes Indent", () => {
    for (const s of [
      "- a\n- b|",
      "1. a\n2. b|",
      "1. a\n2. b\n3. c|",
      "1. [ ] a\n2. [ ] b|",
      "- a|",
      "1. a|",
      "plain|",
      "> - a\n> - b|",
      "> a|",
    ]) {
      const once = key(indent, s) as string;
      expect(key(outdent, once)).toBe(s);
    }
  });
  it("in a code block, move 2 spaces and nothing else", () => {
    expect(key(indent, "```\nx|")).toBe("```\n  x|");
    expect(key(indent, "```\n1. a\n2. b|")).toBe("```\n1. a\n  2. b|"); // no renumbering
    expect(key(outdent, "```\n    x|")).toBe("```\n  x|");
    expect(key(outdent, "```\n - x|")).toBe("```\n- x|");
    expect(key(outdent, "```\n   1. b|")).toBe("```\n 1. b|");
    // After the block's end, lists again
    expect(key(indent, "```\ncode\n```\n- a\n- b|")).toBe("```\ncode\n```\n- a\n  - b|");
  });
});
