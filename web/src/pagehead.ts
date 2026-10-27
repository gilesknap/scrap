// A page's header under its title: what it is and when (one line, or two when there is more
// to say than its kind), and one row of chips (its tags, each a search; + to change them; a
// todo's due chip, which opens the due editor).
import type { Page } from "./api";
import { icon, kindIcon } from "./icons";
import { KINDS } from "./kinds";
import { edited, metaParts } from "./pagemeta";
import { closed, dueChip } from "./status";
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

interface Edits {
  tags: (e: Event) => void;
  due: (e: Event) => void;
  /** The due editor is open (under the row), so the row has no due chip meanwhile. */
  dueOpen: boolean;
}

/** One row of chips, all one size: a todo's due chip, then its tags (each searches for its
 * tag, with its children: tag:a finds a/b), the + that changes them kept on the last tag's
 * line. With no tags, "+ Tag". A closed todo with no due date or priority has no due chip
 * (Reopen it first). */
export function chipRow(p: Page, on: Edits): HTMLElement {
  const due = p.kind === "todo" && !on.dueOpen ? dueChip(p) : null;
  const offer = p.kind === "todo" && !on.dueOpen && !due && !closed(p);
  const tag = (t: string) =>
    h(
      "a",
      {
        href: `/search?q=${encodeURIComponent(token("tag", t))}`,
        // Added by Claude: marked, so the user's own stand apart
        ...(p.model_tags?.includes(t) && { className: "ai", title: "Added by Claude" }),
      },
      `#${t}`,
    );
  // Not "Edit tags": the toolbar's Edit stays the only button named Edit
  const add = h(
    "button",
    {
      type: "button",
      className: p.tags.length ? "add" : "add first",
      "aria-label": p.tags.length ? "Change tags" : "Add tags",
      title: p.tags.length ? "Change tags" : "Add tags",
      onclick: on.tags,
    },
    icon("add"),
    p.tags.length ? "" : "Tag",
  );
  const tags = p.tags.map(tag);
  const last = tags.pop();
  return h(
    "p",
    { className: "tags" },
    // A todo's due chip first: what it is for
    due || offer
      ? h(
          "button",
          { type: "button", className: "duechip", title: "Due date and priority", onclick: on.due },
          icon("due"),
          ...(due?.[1] ? [h("span", { className: "late" }, "overdue"), " "] : []),
          due ? due[0] : "Add due date",
        )
      : "",
    ...tags,
    // The last tag and + together, so + never sits alone on a line
    last ? h("span", { className: "last" }, last, add) : add,
  );
}
