// Lists as you type, as GitHub's editor does them: Enter on a list item starts the next one
// (a bullet, the next number, or an unticked task box), Enter on an empty one ends the list,
// and the Checkbox button turns lines into tasks (or back). The rules are pure functions of
// the text and selection, so the unit tests run them; edit() applies one to a textarea the
// way typing would, so the keyboard's own undo still works. Part of the editor's chunk.

/** A list item's start: quotes and indent, the marker (- * + or 1. 1)), its space, and a task
 * box if it has one. Not escaped (\[ ]), as the renderer and the server read them. */
const ITEM = /^((?:[ \t]*>)*[ \t]*)([-*+]|(\d{1,9})([.)]))([ \t]+)(\[[ xX]\][ \t]+)?/;

/** A change: replace from..to with insert, then select start..end. */
export interface Change {
  from: number;
  to: number;
  insert: string;
  start: number;
  end: number;
}

const lineStart = (text: string, at: number) => text.lastIndexOf("\n", at - 1) + 1;
const lineEnd = (text: string, at: number) => {
  const n = text.indexOf("\n", at);
  return n < 0 ? text.length : n;
};

/** Whether position at is inside a fenced code block (``` or ~~~), where lists don't apply. */
export function inCode(text: string, at: number): boolean {
  let fence: string | null = null;
  for (const line of text.slice(0, lineStart(text, at)).split("\n")) {
    const m = /^[ \t]*(`{3,}|~{3,})(.*)$/.exec(line);
    if (!m) continue;
    if (!fence) fence = m[1];
    // A closing fence: as long at least, of the same mark, and nothing after it (```js inside
    // a block is text). Indented too: fences in list items are
    else if (m[1][0] === fence[0] && m[1].length >= fence.length && !m[2].trim()) fence = null;
  }
  return fence !== null;
}

/** Enter at the caret (start..end): on a list item, the next item, or (on an empty one) the
 * list's end; null to let the newline be typed as usual. */
export function enter(text: string, start: number, end: number): Change | null {
  if (start !== end || inCode(text, start)) return null;
  const from = lineStart(text, start);
  const line = text.slice(from, lineEnd(text, start));
  const m = ITEM.exec(line);
  if (!m || start < from + m[0].length) return null; // the caret before the marker: plain
  const [all, quote, marker, num, delim, gap, box] = m;
  if (!line.slice(all.length).trim()) {
    // An empty item: the list ends, and its marker goes (the line is left empty, or in a
    // quote, the quote's "> " with the caret after it)
    const kept = quote.trimEnd();
    const insert = kept ? `${kept} ` : "";
    const at = from + insert.length;
    return { from, to: from + line.length, insert, start: at, end: at };
  }
  const next = num ? `${Number(num) + 1}${delim}` : marker;
  const insert = `\n${quote}${next}${gap}${box ? "[ ] " : ""}`;
  return { from: start, to: end, insert, start: start + insert.length, end: start + insert.length };
}

/** The Checkbox button: the lines start..end touch become tasks (a bullet or a number keeps
 * its marker; a plain line becomes "- [ ] "), or, if every one is a task already, plain items
 * again. On an empty line, a new task box. */
export function checkbox(text: string, start: number, end: number): Change {
  const from = lineStart(text, start);
  const to = lineEnd(text, Math.max(start, end - (end > start && text[end - 1] === "\n" ? 1 : 0)));
  const lines = text.slice(from, to).split("\n");
  const items = lines.map((l) => ITEM.exec(l));
  const filled = lines.map((l, i) => [l, items[i]] as const).filter(([l]) => l.trim());
  const off = filled.length > 0 && filled.every(([, m]) => m?.[6]);
  const out = lines.map((l, i) => {
    const m = items[i];
    if (off) return m?.[6] ? l.slice(0, m[0].length - m[6].length) + l.slice(m[0].length) : l;
    if (!l.trim() && lines.length > 1) return l; // a blank line between: left alone
    if (m?.[6]) return l;
    if (m) return `${m[0]}[ ] ${l.slice(m[0].length)}`;
    const indent = /^[ \t]*/.exec(l)?.[0] ?? "";
    return `${indent}- [ ] ${l.slice(indent.length)}`;
  });
  const insert = out.join("\n");
  if (lines.length === 1) {
    // One line: the caret moves with what was added or taken before it
    const shift = insert.length - lines[0].length;
    const at = (p: number) => Math.max(from, p + shift);
    return { from, to, insert, start: at(start), end: at(end) };
  }
  return { from, to, insert, start: from, end: from + insert.length };
}

/** Make a change in a textarea as typing would: the browser's own undo keeps it, and an input
 * event says so (the editor keeps its draft). */
export function edit(ta: HTMLTextAreaElement, c: Change) {
  ta.setSelectionRange(c.from, c.to);
  const typed = c.insert
    ? document.execCommand?.("insertText", false, c.insert)
    : c.from === c.to || document.execCommand?.("delete");
  if (!typed) {
    ta.setRangeText(c.insert, c.from, c.to, "end");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  ta.setSelectionRange(c.start, c.end);
  reveal(ta);
}

/** Scroll ta so its caret's line is in view, as typing does (a change made for the keyboard,
 * Enter on a list, doesn't: the new item would sit below the screen's edge). Measured on a
 * hidden copy of the text up to the caret, laid out as the box lays it out. */
function reveal(ta: HTMLTextAreaElement) {
  const cs = getComputedStyle(ta);
  const copy = document.createElement("div");
  for (const k of [
    "font",
    "letterSpacing",
    "lineHeight",
    "padding",
    "border",
    "boxSizing",
    "wordSpacing",
    "tabSize",
  ] as const)
    copy.style[k] = cs[k];
  Object.assign(copy.style, {
    position: "absolute",
    visibility: "hidden",
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
    // As wide as the box (its border too, as box-sizing counts it): its lines wrap where the
    // box's do. Narrower, every wrap came early, and the caret was found lines too low.
    width: `${ta.getBoundingClientRect().width}px`,
  });
  const mark = document.createElement("span");
  mark.textContent = "\u200b";
  copy.append(ta.value.slice(0, ta.selectionEnd), mark);
  document.body.append(copy);
  const bottom = mark.offsetTop + mark.offsetHeight; // the caret line's foot, in the box
  copy.remove();
  const pad = Number.parseFloat(cs.paddingBottom) || 0;
  const line = Number.parseFloat(cs.lineHeight) || 24;
  // Only as far as it takes to show the caret's line: never further
  if (bottom > ta.scrollTop + ta.clientHeight - pad) ta.scrollTop = bottom - ta.clientHeight + pad;
  else if (bottom - line < ta.scrollTop) ta.scrollTop = Math.max(0, bottom - line);
  // And the box itself in the fields' view (it may be taller than what the keyboard leaves)
  const fields = ta.closest(".fields");
  if (fields) {
    const caret = ta.getBoundingClientRect().top + bottom - ta.scrollTop;
    const over = caret - fields.getBoundingClientRect().bottom;
    if (over > 0) fields.scrollTop += over + pad;
  }
}

/** Enter continues lists in ta. Android's keyboards send Enter as an input (keyCode 229, no
 * key), so it is read from beforeinput, not keydown. */
export function lists(ta: HTMLTextAreaElement) {
  ta.addEventListener("beforeinput", (e) => {
    if (e.inputType !== "insertLineBreak" && e.inputType !== "insertParagraph") return;
    const c = enter(ta.value, ta.selectionStart, ta.selectionEnd);
    if (!c) return;
    e.preventDefault();
    edit(ta, c);
  });
}
