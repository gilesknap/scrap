import { describe, expect, it } from "vitest";
import { opened, picked, unpicked } from "../src/linkkey";
import type { Change } from "../src/listedit";

/** The text after a change, with | at the caret (or «..» around a selection). */
function after(text: string, c: Change) {
  const t = text.slice(0, c.from) + c.insert + text.slice(c.to);
  return c.start === c.end
    ? `${t.slice(0, c.start)}|${t.slice(c.start)}`
    : `${t.slice(0, c.start)}«${t.slice(c.start, c.end)}»${t.slice(c.end)}`;
}

/** Link pressed at | (or over «..») in s, then slug picked (null: cancelled): the text after,
 * the caret marked as above. */
function press(s: string, slug: string | null) {
  const a = s.indexOf("«");
  const text = s.replace(/[|«»]/g, "");
  const [start, end] = a >= 0 ? [a, s.indexOf("»") - 1] : [s.indexOf("|"), s.indexOf("|")];
  const { change, spot } = opened(text, start, end);
  const now = change ? text.slice(0, change.from) + change.insert + text.slice(change.to) : text;
  if (slug === null) {
    const [from, to] = unpicked(spot);
    return after(now, { from: 0, to: 0, insert: "", start: from, end: to });
  }
  const c = picked(now, spot, slug);
  return c ? after(now, c) : null;
}

describe("the Link key", () => {
  it("puts [[]] at the caret, the caret between the brackets", () => {
    const { change } = opened("see ", 4, 4);
    expect(change && after("see ", change)).toBe("see [[|]]");
  });

  it("a page picked goes between the brackets, the caret after ]]", () => {
    expect(press("see | now", "garden-plan")).toBe("see [[garden-plan]]| now");
    expect(press("|", "a")).toBe("[[a]]|");
  });

  it("cancelled, the brackets stay with the caret inside", () => {
    expect(press("see | now", null)).toBe("see [[|]] now");
  });

  it("a selection becomes the link's words, and nothing changes until a page is picked", () => {
    expect(opened("my garden plan", 3, 14).change).toBeNull();
    expect(press("my «garden plan»!", "garden-plan")).toBe("my [[garden-plan|garden plan]]|!");
    // cancelled: the selection as it was
    expect(press("my «garden plan»!", null)).toBe("my «garden plan»!");
  });

  it("keeps white space at the selection's ends outside the link, and its words on one line", () => {
    expect(press("a« two\nlines »b", "x")).toBe("a [[x|two lines]]| b");
    // brackets would end the link early
    expect(press("«[odd] words»", "x")).toBe("[[x|odd words]]|");
  });

  it("a selection of white space alone is no label: [[]] in its place", () => {
    expect(press("a«  »b", "x")).toBe("a[[x]]|b");
  });

  it("puts nothing in if the text moved on from the spot", () => {
    const { spot } = opened("ab", 1, 1);
    expect(picked("ab", spot, "x")).toBeNull(); // the brackets gone
    const sel = opened("one two", 0, 3).spot;
    expect(picked("six two", sel, "x")).toBeNull(); // the words changed
  });
});
