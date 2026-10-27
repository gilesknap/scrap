// A tag as a chip says it, everywhere tags show (a page's chip row, the tag picker, Search's
// Filters on chips). Shortened to its short name (tagname.ts), "…/" before the name marks the
// path left out ("#…/thoth", "#…/epics/ioc"), in --ink-2 and hidden from a screen reader: the
// chip's accessible name and tooltip say the full tag. A top-level tag ("#home") is as it is.
// Plain DOM (no ui.ts), so the page chunk takes only this.

const span = (className: string, ...kids: (Node | string)[]) => {
  const el = document.createElement("span");
  el.className = className;
  el.append(...kids);
  return el;
};

/** A tag t by name, its short name (tagNames): "#" and the name, "…/" before it if shortened. */
export function tagLabel(t: string, name = t): HTMLElement {
  const el = span("tl", "#");
  el.dir = "auto";
  if (name !== t) {
    const more = span("more", "…/");
    more.ariaHidden = "true";
    el.append(more);
  }
  el.append(name);
  return el;
}

/** A tag in full ("#tech/epics/thoth"), free to break after each "/" when the line is short. */
export function fullLabel(t: string): HTMLElement {
  const el = span("tl full", "#");
  el.dir = "auto";
  t.split("/").forEach((part, i) => {
    if (i) el.append("/", document.createElement("wbr"));
    el.append(part);
  });
  return el;
}
