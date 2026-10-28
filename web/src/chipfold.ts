// A page's chip row folded to two rows (pagehead.ts): when its chips need more, the tags that
// don't fit are hidden and a "+N" chip after the last one shown ("+3", "Show 3 more tags")
// shows them all in place, where a "−" chip at the end ("Show fewer tags") folds them to two
// rows again. Plain pills, as the tags are: nothing like an add button.
// The due chip always shows. All fitting in two rows: neither. Shown in full, a page stays so
// while it is open (redrawn too), not on another page. Measured, not guessed: again whenever
// the row's width changes (a turned phone, a larger text size).
import { h } from "./ui";

const ROWS = 2;
let opened = ""; // the page whose chips are shown in full, kept while it is redrawn

/** The rows the row's chips take now: the distinct tops of the chips that show (the due chip,
 * tags and the + or −; the tags sit inside the .tagset box beside a due chip). */
const rows = (row: HTMLElement) =>
  new Set(
    [...row.querySelectorAll<HTMLElement>("a, button")]
      .filter((c) => !c.hidden)
      .map((c) => Math.round(c.getBoundingClientRect().top)),
  ).size;

/** Fold row (its tag links, tags) to two rows; id: the page's. */
export function foldChips(row: HTMLElement, tags: HTMLElement[], id: string) {
  if (opened !== id) opened = ""; // another page: folded again
  const more = h("button", { type: "button", className: "morechips" });
  const end = tags[0].parentElement as HTMLElement; // the row, or the .tagset beside a due chip
  const fold = () => {
    // Hiding the focused tag (or taking +N out to measure) would drop focus to the page: +N
    // takes it if its tag is folded away
    const had = document.activeElement;
    for (const t of tags) t.hidden = false;
    more.remove();
    if (rows(row) <= ROWS) return; // all fit: no +N or −
    end.append(more);
    if (opened === id) {
      more.textContent = "−";
      more.ariaLabel = "Show fewer tags";
      if (had === more) more.focus();
      return;
    }
    // Hide from the end until the shown tags and +N fit in two rows (the first always shows: a
    // long one wraps inside its chip)
    const say = (n: number) => {
      more.textContent = `+${n}`;
      more.ariaLabel = `Show ${n} more ${n === 1 ? "tag" : "tags"}`;
    };
    say(1);
    for (let n = 1; n < tags.length && rows(row) > ROWS; n++) {
      tags[tags.length - n].hidden = true;
      say(n);
    }
    if (had === more || (tags.includes(had as HTMLElement) && (had as HTMLElement).hidden))
      more.focus();
  };
  more.onclick = () => {
    opened = opened === id ? "" : id;
    fold();
    more.focus(); // (it stays, as − or +N)
  };
  // Again when the row's width changes, or its first tag's size (the text size changed): never
  // on the row's height, which folding itself changes
  let size = "";
  const watch = new ResizeObserver(() => {
    const first = tags[0].getBoundingClientRect();
    const now = `${row.clientWidth} ${first.width} ${first.height}`;
    if (!row.isConnected) return watch.disconnect();
    if (now === size) return;
    size = now;
    fold();
  });
  watch.observe(row);
  watch.observe(tags[0]);
}
