// A page's chip row folded to two rows (pagehead.ts): when its chips need more, the tags that
// don't fit are hidden and a "+N" chip shows how many, a tap showing them all in place. The
// due chip always shows, and + (change tags) stays right after +N, in one box with it. Measured, not guessed: again
// whenever the row's width changes (a turned phone, a larger text size).
import { h } from "./ui";

const ROWS = 2;
let opened = ""; // the page whose chips were shown in full, kept while it is redrawn

/** The rows the row's chips take now: the distinct tops of what shows (+N and + share the
 * last tag's box, end). */
const rows = (row: HTMLElement) =>
  new Set(
    [...row.children]
      .filter((c) => !(c as HTMLElement).hidden)
      .map((c) => Math.round(c.getBoundingClientRect().top)),
  ).size;

/** Fold row (its tag links, tags; the box holding the last tag and +, end) to two rows. */
export function foldChips(row: HTMLElement, tags: HTMLElement[], end: Element, id: string) {
  const more = h("button", { type: "button", className: "morechips" });
  const fold = () => {
    for (const t of tags) t.hidden = false;
    more.remove();
    if (opened === id || rows(row) <= ROWS) return;
    // (end is the box of the last tag and +: +N goes in it, before +)
    (end.lastElementChild ?? end).before(more); // +N and + together: + never alone on a line
    // Hide from the end until the shown tags, +N and + fit in two rows (all of them, if even
    // one long tag beside the due chip, +N and + would take three)
    for (let n = 1; n <= tags.length; n++) {
      tags[tags.length - n].hidden = true;
      more.textContent = `+${n}`;
      more.ariaLabel = `Show ${n} more ${n === 1 ? "tag" : "tags"}`;
      if (rows(row) <= ROWS) return;
    }
  };
  more.onclick = () => {
    opened = id;
    const first = tags.find((t) => t.hidden);
    fold();
    first?.focus();
  };
  // Again when the row's width changes, or its first tag's size (the text size changed): never
  // on the row's height, which folding itself changes
  let size = "";
  const watch = new ResizeObserver(() => {
    const first = tags[0].getBoundingClientRect();
    const now = `${row.clientWidth} ${first.width} ${first.height}`;
    if (!row.isConnected || now === size) return;
    size = now;
    fold();
  });
  watch.observe(row);
  watch.observe(tags[0]);
}
