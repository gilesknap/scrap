// Edit opens the text where the page was being read: the block at the top of the view, under
// the top bar, as a line of the text (render.ts marks each block with its lines, data-at), and
// the editor's box scrolled to put that line at its top, the caret at its start. Part of the
// editor's chunk (pageedit.ts).

/** The line of the page's text (lines long) at the top of the view: 0 when the view is not
 * scrolled past the start of the text (its title and tags are in sight); null when there is no
 * view. Shown as typed (no renderer offline): as far down as the view is. */
export function reading(lines: number): number | null {
  const body = document.querySelector<HTMLElement>("article.page > .body");
  const top = document.querySelector("body > header")?.getBoundingClientRect().bottom ?? 0;
  const box = body?.getBoundingClientRect();
  if (!body || !box?.height) return null;
  if (box.top >= top) return 0;
  let line = Math.floor((lines * (top - box.top)) / box.height);
  // The last block (in the text's order, so the innermost) that starts above that top
  for (const el of body.querySelectorAll<HTMLElement>("[data-at]")) {
    const r = el.getBoundingClientRect();
    if (r.top > top) break;
    const [start, end] = (el.dataset.at ?? "").split(",").map(Number);
    // Down a block of several lines (a paragraph's, a code block's), as far as it is read;
    // read to its end (the gap before the next block): the line after it
    const read = r.height ? (top - r.top) / r.height : 1;
    line = read < 1 ? start + Math.floor((end - start) * read) : end;
  }
  return line;
}

/** The text box (it scrolls inside itself, editor.ts) scrolled to put line n at its top, the
 * caret at that line's start (line 0: the top, not the end the focused box would show). The
 * lines above it are measured in a hidden copy of the box. */
export function toLine(text: HTMLTextAreaElement, n: number) {
  const lines = text.value.split("\n");
  const above = lines.slice(0, Math.min(n, lines.length - 1)).join("\n");
  if (n < 1 || !above) {
    text.setSelectionRange(0, 0);
    text.scrollTop = 0;
    return;
  }
  const copy = text.cloneNode() as HTMLTextAreaElement;
  copy.removeAttribute("aria-label"); // one Body field, even for a moment
  copy.removeAttribute("id");
  copy.value = above;
  Object.assign(copy.style, {
    position: "absolute",
    visibility: "hidden",
    height: "0",
    minHeight: "0",
    width: `${text.offsetWidth}px`,
  });
  text.after(copy);
  const s = getComputedStyle(copy);
  const y =
    copy.scrollHeight - Number.parseFloat(s.paddingTop) - Number.parseFloat(s.paddingBottom);
  copy.remove();
  text.setSelectionRange(above.length + 1, above.length + 1);
  text.scrollTop = y;
}
