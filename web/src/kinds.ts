// The kinds a user can choose, and the rules for suggesting and sending one. No DOM here (the
// unit tests run it); the control itself is kindPicker() in editor.ts.
import type { Icon } from "./icons";
import type { Kind } from "./queue";

/** The kinds offered, in the order shown (memory and reference are not offered yet):
 * [kind, short label (five fit one row on a 320 px phone), full name, icon]. */
export const KINDS: [Kind, string, string, Icon][] = [
  ["note", "Note", "Note", "note"],
  ["todo", "Todo", "Todo", "todo"],
  ["consume", "Later", "Later", "later"],
  ["whiteboard", "Board", "Whiteboard", "board"],
  ["document", "Doc", "Document", "file"],
];

const BARE_URL = /^https?:\/\/\S+$/;

/** The kind text suggests: a link on its own is to read, anything else a note. */
export const suggested = (text: string): Kind => (BARE_URL.test(text.trim()) ? "consume" : "note");

/** The kind to send, if any: one the user picked (Note too: a choice is kept), or a
 * suggestion that differs from what the page is now ("note" for a new capture). */
export const toSend = (value: string, picked: boolean, current: string): Kind | undefined =>
  picked || value !== current ? (value as Kind) : undefined;

/** A capture's text as it is sent: blank lines before it and white space after it dropped, but
 * the first line's own indent kept (four spaces make it code, so "    # x" is no heading).
 * The server tidies the same way (store/helpers.py's _text). */
export const tidy = (text: string) => text.replace(/^(?:[ \t]*\r?\n)+/, "").trimEnd();
