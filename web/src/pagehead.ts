// A page's header under its title: what it is and when (one line, or two when there is more
// to say than its kind), and one row of chips, read only (a todo's due chip, which opens the
// editor at its Due fold; its tags, each a search).
import type { Page } from "./api";
import { foldChips } from "./chipfold";
import { icon, kindIcon } from "./icons";
import { KINDS } from "./kinds";
import { edited, metaParts } from "./pagemeta";
import { closed, dueChip } from "./status";
import { tagLabel } from "./taglabel";
import { token } from "./terms";
import { h, whenShort } from "./ui";

/** Parts in a row that wraps between them, each never breaking inside. Each part after the
 * first draws its own leading "·" (CSS); the row is shifted left so a part that starts a line
 * has it clipped: no line ever ends or starts with a dot. */
const joined = (parts: HTMLElement[]) => [h("span", { className: "parts" }, ...parts)];

/** "by Claude", a quiet link in the meta line after the kind word: on a topic (#261), to the
 * Topics screen; on a page written over MCP, to all of them. Named in full for a screen
 * reader ("Topic by Claude", "Written by Claude"). */
const byClaude = (href: string, name: string, title: string) =>
  h("a", { className: "written", href, title, "aria-label": name }, "by Claude");

/** What it is and when, under the title: "Todo · Created 25 Oct, 11:52 · Edited …" on one
 * line when the kind is all there is to say, else two: "Later · TV · to watch", then the dates.
 * The kind word leads in semibold ink with its icon (a topic's: the open book); a page Claude
 * made says "by Claude" after it ("Topic · by Claude", "Note · by Claude"). One size, no red,
 * no pills. */
export function headLines(p: Page): HTMLElement[] {
  const label = p.topic ? undefined : KINDS.find(([k]) => k === p.kind)?.[1];
  const said = metaParts(p, label);
  // The kind word, after its icon (the search kind bar's; decoration: aria-hidden)
  const meta: HTMLElement[] = said.map((text, i) =>
    label && !i
      ? h("span", { className: "kind" }, icon(kindIcon(p.kind)), text)
      : h("span", {}, text),
  );
  // A topic is Claude's (#261): "Topic · by Claude", the latter to the Topics screen
  if (p.topic)
    meta.unshift(
      h("span", { className: "kind" }, icon("topic"), "Topic"),
      byClaude("/topics", "Topic by Claude", "Made and kept up by Claude from your pages"),
    );
  // Written over MCP (made_by, store/roles.py): its origin as the tooltip; tapped, finds them all
  else if (p.made_by === "claude")
    meta.splice(
      label ? 1 : 0,
      0,
      byClaude(
        "/search?q=is%3Aclaude",
        "Written by Claude",
        String(p.fields.origin ?? "Written by Claude over MCP"),
      ),
    );
  // Created, and Edited only if it was
  const dates = [
    h("span", {}, `Created ${whenShort(p.created_at)}`),
    ...(edited(p) ? [h("span", {}, `Edited ${whenShort(p.updated_at)}`)] : []),
  ];
  return said.length > (label ? 1 : 0)
    ? [
        h("p", { className: "meta" }, ...joined(meta)),
        h("p", { className: "dates" }, ...joined(dates)),
      ]
    : [h("p", { className: "meta dates" }, ...joined([...meta, ...dates]))];
}

/** One row of chips, all one size, at most two rows (chipfold.ts: "+N" for the rest, "−" to
 * fold them again): a todo's due chip, then its tags (each by its full path, searching for the
 * whole tag with its children: tag:a finds a/b). Beside the due chip the tags are one group
 * (.tagset): they stay together on the line after it when they do not all fit beside it, never
 * one alone. Read only: the due chip opens the editor at its Due fold (due), the tags are
 * changed in the editor. A closed todo with no due date or priority has no due chip (Reopen it
 * first); none at all, and no tags: no row. */
export function chipRow(p: Page, due: () => void): HTMLElement | null {
  const said = p.kind === "todo" ? dueChip(p) : null;
  const offer = p.kind === "todo" && !said && !closed(p);
  // Each tag by its full path, also its accessible name and tooltip; Claude's marked ✦ (CSS),
  // so the user's own stand apart
  const tag = (t: string) => {
    const ai = p.model_tags?.includes(t);
    const name = `Tag ${t}${ai ? ", added by Claude" : ""}`;
    return h(
      "a",
      {
        href: `/search?q=${encodeURIComponent(token("tag", t))}`,
        "aria-label": name,
        title: name,
        ...(ai && { className: "ai" }),
      },
      tagLabel(t),
    );
  };
  const tags = p.tags.map(tag);
  if (!said && !offer && !tags.length) return null;
  const row = h(
    "p",
    { className: "tags" },
    // A todo's due chip first: what it is for
    said || offer
      ? h(
          "button",
          {
            type: "button",
            className: "duechip",
            title: "Change the due date and priority",
            onclick: due,
          },
          icon("due"),
          ...(said?.[1] ? [h("span", { className: "late" }, "overdue"), " "] : []),
          said ? said[0] : "Add due date",
        )
      : "",
    ...(said || offer ? [h("span", { className: "tagset" }, ...tags)] : tags),
  );
  // At most two rows: the rest behind a +N chip that shows them in place
  if (tags.length > 1) foldChips(row, tags, p.id);
  return row;
}
