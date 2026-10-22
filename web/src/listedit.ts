// Lists as you type, as GitHub's editor does them: Enter on a list item starts the next one
// (a bullet, the next number, or an unticked task box), Enter on an empty one ends the list,
// and the editor's keys turn lines into tasks, bullets or numbers (or back) and indent or
// outdent them. The rules are pure functions of the text and selection, so the unit tests
// run them; edit() applies one to a textarea the way typing would, so the keyboard's own undo
// still works. Part of the editor's chunk.

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

/** The Task key: the lines start..end touch become tasks (a bullet or a number keeps
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

/** A line's quotes (> ...), then its indent. */
const LEAD = /^((?:[ \t]*>)*)([ \t]*)/;

/** A line of the lines a key changes: its text, its lead's width (quotes and indent), and its
 * list item (ITEM's match), if it is one. */
interface Line {
  text: string;
  quote: string;
  width: number;
  m: RegExpExecArray | null;
}
const parse = (text: string): Line => {
  const lead = LEAD.exec(text) as RegExpExecArray;
  return { text, quote: lead[1], width: lead[0].length, m: ITEM.exec(text) };
};
/** Where an item's marker (with its space, not its task box) ends: its content's column, which
 * a nested item's marker starts at (2 under "- ", 3 under "1. "). */
const marked = (m: RegExpExecArray) => m[0].length - (m[6]?.length ?? 0);

/** One line's change: at its column at, cut chars go and add takes their place; null: none. */
type Splice = [at: number, cut: number, add: string] | null;

/** A key's change to the lines start..end touch (a selection ending at a line's start leaves
 * that line out). plan sees them all, then says each one's splice, given the lines before it
 * (the text above and the lines already changed) and its own index. On one line the caret and
 * selection move with the text around them, and one inside what was cut lands after what was
 * added (after a marker added to an empty line); several lines end up selected whole. */
function lines(
  text: string,
  start: number,
  end: number,
  plan: (ls: Line[]) => (l: Line, before: string[], i: number) => Splice,
): Change {
  const from = lineStart(text, start);
  const to = lineEnd(text, Math.max(start, end - (end > start && text[end - 1] === "\n" ? 1 : 0)));
  const ls = text.slice(from, to).split("\n").map(parse);
  const each = plan(ls);
  const before = from ? text.slice(0, from - 1).split("\n") : [];
  const moves: [number, number, number][] = []; // [where, cut, added] in the old text
  let at = from;
  ls.forEach((l, i) => {
    const s = each(l, before, i);
    if (s) moves.push([at + s[0], s[1], s[2].length]);
    before.push(s ? l.text.slice(0, s[0]) + s[2] + l.text.slice(s[0] + s[1]) : l.text);
    at += l.text.length + 1;
  });
  const map = (p: number) => {
    let d = 0;
    for (const [x, cut, add] of moves) {
      if (p < x) break;
      if (p < x + cut || (cut === 0 && p === x)) return x + d + add;
      d += add - cut;
    }
    return p + d;
  };
  const insert = before.slice(before.length - ls.length).join("\n");
  // Several lines: all of them selected, as Task does
  if (ls.length > 1) return { from, to, insert, start: from, end: from + insert.length };
  return { from, to, insert, start: map(start), end: map(end) };
}

/** A numbered item's number at lead width w, after the lines before, and its delimiter: one
 * past the nearest number at w above it (in the same list: past items nested deeper, or blank
 * lines), with that one's . or ) (another starts a new list), else 1 and own (its own, or .). */
function number(before: string[], w: number, own = "."): string {
  for (let i = before.length - 1; i >= 0; i--) {
    if (!before[i].trim()) continue;
    const l = parse(before[i]);
    if (l.width > w) continue;
    return l.width === w && l.m?.[3] ? `${Number(l.m[3]) + 1}${l.m[4]}` : `1${own}`;
  }
  return `1${own}`;
}

/** The nearest line above that isn't blank and isn't nested deeper than w. */
function above(before: string[], w: number): Line | null {
  for (let i = before.length - 1; i >= 0; i--) {
    if (!before[i].trim()) continue;
    const l = parse(before[i]);
    if (l.width <= w) return l;
  }
  return null;
}

/** Whether every line of ls that isn't blank is one (and there is one). */
const all = (ls: Line[], is: (l: Line) => boolean) => {
  const filled = ls.filter((l) => l.text.trim());
  return filled.length > 0 && filled.every(is);
};

/** The Bullet key: the lines become bullets ("- " after their indent; a task or a number
 * gives way to it), or, if every one is a bullet already, plain lines again. A blank line
 * between is left alone; on an empty line, a new bullet. */
export function bullet(text: string, start: number, end: number): Change {
  const is = (l: Line) => !!l.m && !l.m[3] && !l.m[6];
  return lines(text, start, end, (ls) => {
    const off = all(ls, is);
    return (l) => {
      const at = l.width;
      if (off) return l.m ? [at, l.m[0].length - at, ""] : null;
      if ((ls.length > 1 && !l.text.trim()) || is(l)) return null;
      return [at, l.m ? l.m[0].length - at : 0, "- "];
    };
  });
}

/** The Numbered key: the lines become numbered items, 1. 2. 3. in order at each indent (on
 * from a number just above), a bullet's marker giving way to the number (a task keeps its
 * box); or, if every one is numbered already, plain lines again (a task stays one, as a
 * bullet). */
export function numbered(text: string, start: number, end: number): Change {
  const is = (l: Line) => !!l.m?.[3];
  return lines(text, start, end, (ls) => {
    const off = all(ls, is);
    return (l, before) => {
      const at = l.width;
      if (off) return l.m ? [at, marked(l.m) - at, l.m[6] ? "- " : ""] : null;
      if (ls.length > 1 && !l.text.trim()) return null;
      const n = `${number(before, at, l.m?.[4])} `;
      return [at, l.m ? marked(l.m) - at : 0, n];
    };
  });
}

/** The Indent key: each line (not a blank one between) one level deeper. A level is what
 * nests an item under the one above it at the same indent: its content's column, so 2 spaces
 * under "- ", 3 under "1. " (CommonMark nests by that column); with no such item above, the
 * line's own marker's width, or 2. A numbered item takes the number its new place gives it.
 * In a code block, 2 spaces, nothing else. */
export function indent(text: string, start: number, end: number): Change {
  const code = inCode(text, start);
  return lines(text, start, end, (ls) => {
    const old = ls.map((l) => l.text);
    return (l, before, i) => {
      if (ls.length > 1 && !l.text.trim()) return null;
      const w = l.width;
      if (code) return [w, 0, "  "];
      const up = above([...before.slice(0, before.length - i), ...old.slice(0, i)], w);
      const step = up?.m && up.width === w ? marked(up.m) - w : l.m ? marked(l.m) - w : 2;
      const pad = " ".repeat(step);
      if (!l.m?.[3]) return [w, 0, pad];
      return [w, l.m[3].length + 1, `${pad}${number(before, w + step, l.m[4])}`];
    };
  });
}

/** The Outdent key: each line a level out, as far as Indent took it in: to the indent of
 * the item it is nested under, or (with none above) by its marker's width, or 2, and never
 * past its line's start. A numbered item takes the number its new place gives it. In a code
 * block, 2 spaces. */
export function outdent(text: string, start: number, end: number): Change {
  const code = inCode(text, start);
  return lines(text, start, end, (ls) => {
    const old = ls.map((l) => l.text);
    return (l, before, i) => {
      const w = l.width;
      // The indent's own width: not the quotes', nor the one space after a quote's ">" (the
      // quote's own, as CommonMark reads it: taking it, "> a" became ">a")
      const sep = l.quote && /^[ \t]/.test(l.text.slice(l.quote.length)) ? 1 : 0;
      const room = w - l.quote.length - sep;
      if (!room) return null;
      let to = w - Math.min(room, 2);
      if (!code) {
        const up = above([...before.slice(0, before.length - i), ...old.slice(0, i)], w - 1);
        if (up && up.width >= l.quote.length + sep) to = up.width;
        else to = w - Math.min(room, l.m ? marked(l.m) - w : 2);
      }
      if (code || !l.m?.[3]) return [to, w - to, ""];
      return [to, w - to + l.m[3].length + 1, number(before, to, l.m[4])];
    };
  });
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
