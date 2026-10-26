// A list in sections (groups.ts), drawn the one way for the search screen's groups and the
// Todos screen's Now: an h2.label "To watch · 4" over each section's rows, a folded section
// (Done) a .donefold at the end. The rows are one pager trail, in the order shown (a section
// with a trail of its own aside), and each gets its swipes and tick.
import type { Section } from "./groups";
import { type RowPage, swipeRows, trail } from "./swipe";
import { h } from "./ui";

/** The sections as elements (a section with no label is its list alone). label: what a page
 * opened from them says it is in; id: the headings' ids start with it. */
export function drawSections<T extends RowPage>(
  secs: Section<T>[],
  row: (t: T) => Element,
  label: string,
  id: string,
): HTMLElement[] {
  const slugs = secs.filter((s) => !s.trail).flatMap((s) => s.items.map((t) => t.slug));
  return secs.map((s) => {
    const ul = trail(
      h("ul", { className: "list" }, ...s.items.map((t) => row(t))),
      s.trail ?? label,
      s.trail ? s.items.map((t) => t.slug) : slugs,
    );
    swipeRows(s.items.map((t, i) => [ul.children[i], t]));
    const said = `${s.label} · ${s.items.length}`;
    if (s.fold)
      return h("details", { className: "donefold", open: !!s.open }, h("summary", {}, said), ul);
    if (!s.label) return ul;
    const hid = `${id}-${s.label.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-")}`;
    return h(
      "section",
      { "aria-labelledby": hid },
      h("h2", { className: "label", id: hid }, s.href ? h("a", { href: s.href }, said) : said),
      ul,
    );
  });
}
