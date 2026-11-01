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
export type Spot = { at: number } | { from: number; to: number; words: string };

/** The Link key at start..end: with nothing selected, [[]] put in with the caret between the
 * brackets; with a selection, nothing changes yet (it stays selected while the picker is
 * open). A selection of white space alone is no label: [[]] in its place. */
export function opened(
  text: string,
  start: number,
  end: number,
): { change: Change | null; spot: Spot } {
  const words = label(text.slice(start, end));
  if (start !== end && words) return { change: null, spot: { from: start, to: end, words } };
  return {
    change: { from: start, to: end, insert: "[[]]", start: start + 2, end: start + 2 },
    spot: { at: start },
  };
}

/** A selection as a link's words, on one line, with no bracket (they would end the link). */
const label = (s: string) => s.replace(/[[\]]/g, "").replace(/\s+/g, " ").trim();

/** A page picked: its slug between the brackets, [[slug]], or the selection as the link's
 * words, [[slug|words]] (white space at either end of the selection kept outside it); the
 * caret after the closing ]]. null if the text has moved on from the spot (the brackets
 * gone), so nothing is put in the wrong place. */
export function picked(text: string, spot: Spot, slug: string): Change | null {
  if ("at" in spot) {
    if (text.slice(spot.at, spot.at + 4) !== "[[]]") return null;
    const at = spot.at + 2;
    const caret = at + slug.length + 2;
    return { from: at, to: at, insert: slug, start: caret, end: caret };
  }
  const was = text.slice(spot.from, spot.to);
  if (label(was) !== spot.words) return null;
  const lead = /^\s*/.exec(was)?.[0] ?? "";
  const trail = /\s*$/.exec(was)?.[0] ?? "";
  const link = `[[${slug}|${spot.words}]]`;
  const caret = spot.from + lead.length + link.length;
  return {
    from: spot.from,
    to: spot.to,
    insert: lead + link + trail,
    start: caret,
    end: caret,
  };
}

/** Cancelled: the caret back where the picker left it, between the brackets, or the
 * selection as it was. */
export const unpicked = (spot: Spot): [number, number] =>
  "at" in spot ? [spot.at + 2, spot.at + 2] : [spot.from, spot.to];

/** The Link key's press in the text box t: [[]] in (or the selection held), then the picker;
 * focus is back in the box when it closes, the caret placed. Not in a code block, where
 * [[...]] is only text: there it does nothing, as the list keys. */
export async function link(t: HTMLTextAreaElement) {
  t.focus();
  if (inCode(t.value, t.selectionStart)) return;
  const { change, spot } = opened(t.value, t.selectionStart, t.selectionEnd);
  if (change) edit(t, change);
  let slug: string | null = null;
  try {
    slug = await (await import("./linkpick")).pick();
  } catch {
    // The picker couldn't load (offline, before it was ever kept): the brackets stay, for a slug
  }
  t.focus();
  const c = slug ? picked(t.value, spot, slug) : null;
  if (c) edit(t, c);
  else t.setSelectionRange(...unpicked(spot));
}
