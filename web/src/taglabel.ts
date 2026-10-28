// A tag as a chip says it, everywhere tags show (a page's chip row, the tag picker, Search's
// Filters on chips): its full path, "#tech/epics/thoth", free to break after each "/" when the
// line is short, so a long one wraps inside its chip rather than running sideways. Plain DOM
// (no ui.ts), so the page chunk takes only this.

/** A tag in full ("#tech/epics/thoth"), free to break after each "/". */
export function tagLabel(t: string): HTMLElement {
  const el = document.createElement("span");
  el.className = "tl";
  el.dir = "auto";
  el.append("#");
  t.split("/").forEach((part, i) => {
    if (i) el.append("/", document.createElement("wbr"));
    el.append(part);
  });
  return el;
}
