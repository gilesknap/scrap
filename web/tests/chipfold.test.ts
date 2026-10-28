import { expect, it, vi } from "vitest";

// The tests run in node: a fake of the few DOM parts the fold touches. Each chip has a top
// (its row); the +N chip, when attached, sits on tops[tops.length - 1] + 40.
class Chip {
  hidden = false;
  textContent = "";
  ariaLabel = "";
  onclick: (() => void) | null = null;
  parentElement: Box | null = null;
  constructor(public top = 0) {}
  getBoundingClientRect() {
    return { top: this.top, width: 100, height: 32 };
  }
  remove() {
    this.parentElement?.kids.splice(this.parentElement.kids.indexOf(this), 1);
    this.parentElement = null;
  }
  focus() {}
  append() {}
}
class Box {
  kids: Chip[] = [];
  clientWidth = 300;
  isConnected = true;
  constructor(public parent?: Box) {}
  append(c: Chip) {
    c.parentElement = this;
    this.kids.push(c);
  }
  all(): Chip[] {
    return this.kids;
  }
}

vi.stubGlobal("document", { createElement: () => new Chip(), activeElement: null });
// (the observer's first call is the fold)
vi.stubGlobal(
  "ResizeObserver",
  class {
    constructor(private cb: () => void) {}
    observe() {
      this.cb();
    }
    disconnect() {}
  },
);
const { foldChips } = await import("../src/chipfold");

/** A row of the given chips (tags in the row itself); the +N chip lands after the last shown
 * one, on a row of its own if wraps. */
function build(tops: number[], wraps = false) {
  const row = new Box();
  const tags = tops.map((t) => new Chip(t));
  for (const t of tags) row.append(t);
  const asRow = row as unknown as { querySelectorAll: () => Chip[] };
  asRow.querySelectorAll = () => {
    const shown = row.kids.filter((c) => !c.textContent && !c.hidden).map((c) => c.top);
    for (const c of row.kids) if (c.textContent) c.top = Math.max(...shown) + (wraps ? 40 : 0);
    return row.kids;
  };
  return { row: asRow as unknown as HTMLElement, tags, box: row };
}

it("hides the tags that do not fit and counts them in the +N chip", () => {
  // Three rows of tags: the last row's tag folds away, +N sits in the second row
  const { row, tags, box } = build([0, 0, 40, 80]);
  foldChips(row, tags as unknown as HTMLElement[], "p1");
  const more = box.kids.at(-1) as Chip;
  expect(tags.filter((t) => t.hidden)).toHaveLength(1);
  expect(more.textContent).toBe("+1");
  expect(more.ariaLabel).toBe("Show 1 more tag");
});

it("shows no +1 when a single tag is over two rows: nothing is hidden", () => {
  // The due chip, the one tag and another chip need three rows; hiding the tag would not help
  // (the first always shows), so there is nothing to fold
  const { row, tags, box } = build([0, 40, 80], true);
  foldChips(row, [tags[1]] as unknown as HTMLElement[], "p2");
  expect(tags.some((t) => t.hidden)).toBe(false);
  expect(box.kids.some((c) => c.textContent)).toBe(false);
});
