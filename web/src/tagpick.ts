// The tag picker: one implementation for the tag editor (tagedit.ts: a page's + and the
// composer's Tags fold) and Search's Filters → Tags (refine.ts). Chosen tags are filled chips
// with a ✕; offered tags are outlined chips under the box, one tap each, that wrap to at most
// two rows (measured: those that would start a third are left out, no "+N": typing narrows
// them). Each says its short name (tagname.ts, as on a page's chip row: the last part, more of
// the path only where two shown would clash, "…/" marking what is left out: taglabel.ts); the
// full tag is in its tooltip and accessible name. Claude's are marked ✦, as on the page. Not
// the whole path, however faint: at a large text size (130%) such a chip took a row of its own.
import { icon } from "./icons";
import { tagLabel } from "./taglabel";
import { tagNames } from "./tagname";
import { h } from "./ui";

const ROWS = 2;
const DOUBLE = 400; // ms: a second tap on the offers sooner than this is a double tap, ignored

/** The chosen tags as filled chips, each with a ✕ (remove): Claude's (in claude) marked ✦.
 * also: the tags offered beside them, whose names they are told apart from. */
export function chosenChips(
  tags: string[],
  remove: (t: string, e: Event) => void,
  claude: string[] = [],
  also: string[] = [],
): HTMLElement[] {
  const names = tagNames([...new Set([...tags, ...also])]);
  return tags.map((t) => {
    const ai = claude.includes(t);
    const said = `#${t}${ai ? ", added by Claude" : ""}`;
    return h(
      "button",
      {
        type: "button",
        className: ai ? "facet on ai" : "facet on",
        "aria-label": `Remove ${said}`,
        title: said,
        onclick: (e: Event) => remove(t, e),
      },
      tagLabel(t, names.get(t)),
      icon("close"),
    );
  });
}

export interface Offers {
  el: HTMLElement;
  /** Offer these ([tag, count], the count shown when given), verb naming each ("Add",
   * "Filter by"); pick is called on a tap. note: a line before them (why there are none).
   * focus: the chip to focus once drawn (the one now in its place, else the last, else back).
   * also: the chosen tags shown beside them, whose names they are told apart from. */
  show(
    list: [string, number?][],
    verb: string,
    pick: (t: string, e: Event) => void,
    o?: { note?: string; focus?: number; back?: HTMLElement; also?: string[] },
  ): void;
}

/** A row of offered tags, a group named label. lead: what starts the first row (Search's box,
 * so the box and its offers take two rows in all). */
export function offerRow(label: string, lead?: HTMLElement): Offers {
  const el = h("div", { className: "offers", role: "group", "aria-label": label });
  let all: HTMLElement[] = []; // every chip drawn, before fitting to two rows
  let tapped = -Infinity; // when an offer was last tapped
  /** Show the chips that fit in two rows: those that would start a third are left out. */
  const fold = () => {
    // (never moving the box: moved, it would lose focus and the keyboard with it)
    for (const c of [...el.children]) if (c !== lead) c.remove();
    if (lead && lead.parentElement !== el) el.prepend(lead);
    el.append(...all);
    if (!el.clientWidth) return; // not shown: fitted when it is (the observer)
    const tops = lead ? [Math.round(lead.getBoundingClientRect().top)] : [];
    const cut = all.findIndex((c) => {
      const top = Math.round(c.getBoundingClientRect().top);
      if (!tops.includes(top)) tops.push(top);
      return tops.length > ROWS;
    });
    if (cut >= 0) for (const c of all.slice(cut)) c.remove();
  };
  // Again when its width changes, or a chip's height (the text size): never on its own height,
  // which fitting changes
  let size = "";
  new ResizeObserver(() => {
    const now = `${el.clientWidth} ${all[0]?.getBoundingClientRect().height}`;
    if (now === size) return;
    size = now;
    fold();
  }).observe(el);
  return {
    el,
    show(list, verb, pick, o = {}) {
      const names = tagNames([...new Set([...list.map(([t]) => t), ...(o.also ?? [])])]);
      all = list.map(([t, n]) =>
        h(
          "button",
          {
            type: "button",
            className: "facet",
            "aria-label": `${verb} #${t}`,
            title: `#${t}`,
            "data-k": `tag:${t}`, // (Search puts focus back by it)
            onclick: (e: Event) => {
              // A double tap: the second lands on the chip that slid into the first's place
              if (e.timeStamp - tapped < DOUBLE) return;
              tapped = e.timeStamp;
              pick(t, e);
            },
          },
          tagLabel(t, names.get(t)),
          n !== undefined && h("small", {}, String(n)),
        ),
      );
      if (o.note) all.unshift(h("small", { className: "none" }, o.note));
      el.hidden = !all.length && !lead;
      fold();
      const at = o.focus ?? -1;
      if (at >= 0) ((el.children[at] ?? el.lastElementChild ?? o.back) as HTMLElement)?.focus();
    },
  };
}
