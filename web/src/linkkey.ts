// The editor's Link key (#511): a link to another page, [[slug]], without typing the brackets
// (hard to reach on a phone's keyboard) or knowing the slug. Pressed, it puts [[]] at the caret
// and opens a page picker (linkpick.ts, a chunk of its own, loaded on the first press); a page
// picked goes between the brackets, and a selection becomes the link's words, [[slug|words]].
// The changes go through edit() (listedit.ts), as the other keys' do, so Undo takes them back.
// The rules are pure functions of the text and selection, so the unit tests run them. Part of
// the editor's chunk.
import { type Change, edit, inCode } from "./listedit";

/** Where a link goes once a page is picked: the brackets put in at start (no selection), or
 * the selection from..to, whose words become its label. */
export type Spot = { at: number } | { from: number; to: number; raw: string; words: string };

/** The Link key at start..end: with nothing selected, [[]] put in with the caret between the
 * brackets; with a selection, nothing changes yet (it stays selected while the picker is
 * open). A selection of white space alone is no label: [[]] in its place. With the caret
 * already in an empty [[]] (a picker closed with none, pressed again), those brackets. */
export function opened(
  text: string,
  start: number,
  end: number,
): { change: Change | null; spot: Spot } {
  const words = label(text.slice(start, end));
  if (start === end && text.slice(start - 2, start + 2) === "[[]]")
    return { change: null, spot: { at: start - 2 } };
  if (start !== end && words)
    return { change: null, spot: { from: start, to: end, raw: text.slice(start, end), words } };
  return {
    change: { from: start, to: end, insert: "[[]]", start: start + 2, end: start + 2 },
    spot: { at: start },
  };
}

/** A selection as a link's words, on one line, with no bracket (they would end the link). */
const label = (s: string) => s.replace(/[[\]]/g, "").replace(/\s+/g, " ").trim();

/** Where needle is in text: at at, or else the nearest place within a line's length of it
 * (the text before it shifted a little: a phone's keyboard committing a word as focus left
 * the box), or -1. */
function near(text: string, needle: string, at: number): number {
  if (text.startsWith(needle, at)) return at;
  let best = -1;
  for (let i = text.indexOf(needle, Math.max(0, at - 80)); i >= 0 && i <= at + 80; ) {
    if (best < 0 || Math.abs(i - at) < Math.abs(best - at)) best = i;
    i = text.indexOf(needle, i + 1);
  }
  return best;
}

/** Whether the text from..to (to be the link) is on a table's row, where a bare | would end
 * the cell: a | elsewhere on its line (a row needn't start with one). */
function inTable(text: string, from: number, to: number) {
  const start = from > 0 ? text.lastIndexOf("\n", from - 1) + 1 : 0;
  const n = text.indexOf("\n", to);
  const end = n < 0 ? text.length : n;
  return (text.slice(start, from) + text.slice(to, end)).includes("|");
}

/** A page picked: its slug between the brackets, [[slug]], or the selection as the link's
 * words, [[slug|words]] (white space at either end of the selection kept outside it; in a
 * table's cell, [[slug\|words]]); the caret after the closing ]]. null if the text has moved
 * on from the spot (the brackets or the words gone), so nothing is put in the wrong place. */
export function picked(text: string, spot: Spot, slug: string): Change | null {
  if ("at" in spot) {
    const found = near(text, "[[]]", spot.at);
    if (found < 0) return null;
    const at = found + 2;
    const caret = at + slug.length + 2;
    return { from: at, to: at, insert: slug, start: caret, end: caret };
  }
  const from = near(text, spot.raw, spot.from);
  if (from < 0) return null;
  const was = spot.raw;
  const lead = /^\s*/.exec(was)?.[0] ?? "";
  const trail = /\s*$/.exec(was)?.[0] ?? "";
  const core = from + lead.length;
  // In a cell, every bar escaped: the label's own too
  const cell = inTable(text, core, from + was.length - trail.length);
  const link = cell
    ? `[[${slug}\\|${spot.words.replace(/\\?\|/g, "\\|")}]]`
    : `[[${slug}|${spot.words}]]`;
  const caret = core + link.length;
  return {
    from,
    to: from + was.length,
    insert: lead + link + trail,
    start: caret,
    end: caret,
  };
}

/** Cancelled: the caret back between the brackets, or the selection as it was (where they
 * are now, should the text before them have shifted). */
export function unpicked(text: string, spot: Spot): [number, number] {
  if ("at" in spot) {
    const at = near(text, "[[]]", spot.at);
    return at < 0 ? [spot.at + 2, spot.at + 2] : [at + 2, at + 2];
  }
  const from = near(text, spot.raw, spot.from);
  return from < 0 ? [spot.from, spot.to] : [from, from + spot.raw.length];
}

let busy = false; // a press's picker loading or open: a second press (a double tap) does nothing

/** The Link key's press in the text box t: [[]] in (or the selection held), then the picker;
 * focus is back in the box when it closes, the caret placed. Not in a code block, where
 * [[...]] is only text: there it does nothing, as the list keys. */
export async function link(t: HTMLTextAreaElement) {
  if (busy) return;
  t.focus();
  if (inCode(t.value, t.selectionStart)) return;
  busy = true;
  try {
    const { change, spot } = opened(t.value, t.selectionStart, t.selectionEnd);
    if (change) edit(t, change);
    let slug: string | null = null;
    try {
      const { pick } = await import("./linkpick");
      // The editor closed while it loaded (Back): nothing to link in
      if (t.isConnected) slug = await pick();
    } catch {
      // The picker couldn't load (offline, before it was ever kept): the brackets stay
    }
    if (t.isConnected) placed(t, spot, slug);
  } finally {
    busy = false;
  }
}

/** The picker closed: the slug put in (if one was picked and its spot is still there), else
 * the caret back between the brackets or the selection as it was. */
function placed(t: HTMLTextAreaElement, spot: Spot, slug: string | null) {
  t.focus();
  const c = slug ? picked(t.value, spot, slug) : null;
  if (c) edit(t, c);
  else t.setSelectionRange(...unpicked(t.value, spot));
}
