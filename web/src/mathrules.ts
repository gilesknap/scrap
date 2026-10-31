// Maths in page text, as GitHub writes it: $...$ inline, $$...$$ (inline or on lines of its
// own) for display, and a top-level amsmath environment (\begin{align} ... \end{align}). Each
// becomes its TeX, escaped, in a <span class="math"> or <div class="math display"> for math.ts
// to draw (a ```math fence stays a code block, drawn the same way). The server parses with the
// same rules (src/scrap/maths.py; tests/maths_cases.json holds both to the same answers), so
// _, * and [[ in a formula are neither emphasis nor a link on either side.
// Money is not maths: an opening $ is not followed by a space, nor preceded by a digit; a
// closing $ is not preceded by a space, nor followed by a digit; so "$5 and $10" stays text.
import type { MarkdownIt, StateBlock, StateInline, Token } from "markdown-it";

const digit = (c: string | undefined) => c !== undefined && c >= "0" && c <= "9";

/** Whether the character at pos is escaped: an odd run of backslashes before it. */
function escaped(src: string, pos: number): boolean {
  let n = 0;
  while (pos - n - 1 >= 0 && src[pos - n - 1] === "\\") n++;
  return n % 2 === 1;
}

/** $tex$ and $$tex$$ in a line's text (maths.py _inline). */
function inline(state: StateInline, silent: boolean): boolean {
  const { src, pos, posMax } = state;
  if (src[pos] !== "$" || pos + 1 >= posMax || digit(src[pos - 1]) || escaped(src, pos))
    return false;
  const double = src[pos + 1] === "$";
  const ws = (i: number) => state.md.utils.isWhiteSpace(src.charCodeAt(i));
  if (!double && ws(pos + 1)) return false;
  const width = double ? 2 : 1;
  let from = pos + width;
  let end = -1; // where the closing $ or $$ starts
  for (;;) {
    end = src.indexOf("$", from);
    if (end < 0 || end + width > posMax) return false;
    if (escaped(src, end) || (double && src[end + 1] !== "$")) from = end + 1;
    else break;
  }
  const tex = src.slice(pos + width, end);
  if (!tex || (!double && ws(end - 1)) || digit(src[end + width])) return false;
  if (!silent) {
    const t = state.push(double ? "math_inline_double" : "math_inline", "math", 0);
    t.content = tex;
    t.markup = double ? "$$" : "$";
  }
  state.pos = end + width;
  return true;
}

/** Line i's text, from its first character (after its indent, and any quote marker). */
const lineOf = (state: StateBlock, i: number) =>
  state.src.slice(state.bMarks[i] + state.tShift[i], state.eMarks[i]);

/** $$ at a line's start, to a line that ends $$ (that one, if it is more than $$), with no
 * blank line between, nor a line out of the list item (maths.py _block). A line that starts
 * another $$ ends the search, so no line is read twice. */
function block(state: StateBlock, start: number, end: number, silent: boolean): boolean {
  if (state.sCount[start] - state.blkIndent >= 4) return false; // indented code
  const first = lineOf(state, start).trim();
  if (!first.startsWith("$$")) return false;
  let next = start;
  if (first.length <= 3 || !first.endsWith("$$")) {
    for (;;) {
      if (++next >= end) return false;
      const line = lineOf(state, next).trim();
      if (!line || state.sCount[next] < state.blkIndent) return false; // or out of a list
      if (line.startsWith("$$") && !line.endsWith("$$")) return false;
      if (line.endsWith("$$")) break;
    }
  }
  if (silent) return true;
  state.line = next + 1;
  const t = state.push("math_block", "math", 0);
  t.block = true;
  t.content = state.getLines(start, state.line, state.blkIndent, false).trim().slice(2, -2);
  t.markup = "$$";
  t.map = [start, state.line];
  return true;
}

// The top-level environments amsmath_plugin takes (mdit_py_plugins.amsmath ENVIRONMENTS)
const ENVS =
  "equation|multline|gather|align|alignat|flalign|matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|eqnarray";
const OPEN = new RegExp(`^\\\\begin\\{(${ENVS})(\\*?)\\}`);

/** \begin{env} at a line's start, to the line that ends \end{env}, not out of a list item
 * (maths.py _amsmath). A line that begins the same env again ends the search. */
function amsmath(state: StateBlock, start: number, end: number, silent: boolean): boolean {
  if (state.sCount[start] - state.blkIndent >= 4) return false;
  const m = OPEN.exec(lineOf(state, start));
  if (!m) return false;
  const closing = `\\end{${m[1]}${m[2]}}`;
  for (let next = start; next < end; next++) {
    const line = lineOf(state, next);
    if (line.trimEnd().endsWith(closing)) {
      if (silent) return true;
      state.line = next + 1;
      const t = state.push("amsmath", "math", 0);
      t.block = true;
      t.content = state.getLines(start, state.line, state.sCount[start], false);
      t.map = [start, state.line];
      return true;
    }
    if (next === start || !line.trim()) continue;
    if (state.sCount[next] < state.blkIndent || OPEN.exec(line)?.[0] === m[0]) return false;
  }
  return false;
}

/** The maths rules, and their HTML: the TeX as text, for math.ts to draw. */
export default function maths(md: MarkdownIt) {
  md.inline.ruler.before("escape", "math_inline", inline);
  md.block.ruler.before("fence", "math_block", block);
  md.block.ruler.before("blockquote", "amsmath", amsmath, {
    alt: ["paragraph", "reference", "blockquote", "list", "footnote_def"],
  });
  const esc = md.utils.escapeHtml;
  const span = (cls: string) => (tokens: Token[], i: number) =>
    `<span class="${cls}">${esc(tokens[i].content.trim())}</span>`;
  const div = (
    tokens: Token[],
    i: number,
    _o: unknown,
    _e: unknown,
    self: MarkdownIt["renderer"],
  ) =>
    `<div class="math display"${self.renderAttrs(tokens[i])}>${esc(tokens[i].content.trim())}</div>\n`;
  md.renderer.rules.math_inline = span("math");
  md.renderer.rules.math_inline_double = span("math display");
  md.renderer.rules.math_block = div;
  md.renderer.rules.amsmath = div;
}
