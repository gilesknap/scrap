// The kind the editor and composer suggest for text, task lists too. Only they load it (the
// app shell carries kinds.ts, so this is kept out of it). No DOM here (the unit tests run it).
import { suggested as fromText } from "./kinds";
import type { Kind } from "./queue";

// A list item whose first line starts with a task box (- [ ] or - [x]), as render.ts ITEM; a
// box in code is not told apart here, though the server does not count it
const BOX = /^(?:[ \t]*>)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\[[ xX]\](?: |$)/m;

/** The kind text suggests: one with task boxes is a todo, as saving would file it (an
 * unfiled note with boxes becomes one); else a link on its own is to read, anything else a
 * note. */
export const suggested = (text: string): Kind => (BOX.test(text) ? "todo" : fromText(text));
