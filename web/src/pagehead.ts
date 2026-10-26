// A page's header under its title: the quiet meta line (what it is, its dates) and one row of
// chips for what is edited in place (its tags, a todo's due date), ended by a + for the tags.
import type { Page } from "./api";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { metaParts } from "./pagemeta";
import { closed, dueChip } from "./status";
import { h } from "./ui";

/** The meta line: "Later · TV · to watch · 26 Oct", in one size and colour, only an overdue
 * part in red; a topic's "Topic by Claude" first, a page Claude wrote "Written by Claude" last.
 * Each part never breaks; the line breaks after a ·, never before one. */
export function metaLine(p: Page): HTMLElement {
  const label = p.topic ? undefined : KINDS.find(([k]) => k === p.kind)?.[1];
  const parts: HTMLElement[] = metaParts(p, label).map(([text, late]) =>
    h("span", { className: late ? "late" : "" }, text),
  );
  // A topic is Claude's (#261): tapped, the Topics screen
  if (p.topic)
    parts.unshift(
      h(
        "a",
        {
          className: "written topicby",
          href: "/topics",
          title: "Made and kept up by Claude from your pages",
        },
        "Topic by Claude",
      ),
    );
  // Written over MCP (made_by, store/roles.py): its origin as the tooltip; tapped, finds them all
  if (p.made_by === "claude")
    parts.push(
      h(
        "a",
        {
          className: "written", // not .badge: that is the top bar's queue pill
          href: "/search?q=is%3Aclaude",
          title: String(p.fields.origin ?? "Written by Claude over MCP"),
        },
        "Written by Claude",
      ),
    );
  const said = parts.flatMap((el, i) => (i ? ["\u00a0· ", el] : [el])); // no break before a ·
  return h("p", { className: "meta" }, ...said);
}

interface Edits {
  tags: (e: Event) => void;
  due: (e: Event) => void;
  /** The due editor is open (under the row), so the row has no due chip meanwhile. */
  dueOpen: boolean;
}

/** One row of chips, all one size: its tags, a todo's due chip, then + (Edit tags). A tag or
 * the + opens the tag editor; the due chip, the due editor. A closed todo with no due date or
 * priority has no due chip (Reopen it first). */
export function chipRow(p: Page, on: Edits): HTMLElement {
  const due = p.kind === "todo" && !on.dueOpen ? dueChip(p) : null;
  const offer = p.kind === "todo" && !on.dueOpen && !due && !closed(p);
  return h(
    "p",
    { className: "tags" },
    ...p.tags.map((t) =>
      h(
        "button",
        {
          type: "button",
          title: "Edit tags",
          onclick: on.tags,
          // Added by Claude: marked, so the user's own stand apart
          ...(p.model_tags?.includes(t) && {
            className: "ai",
            title: "Added by Claude: edit tags",
          }),
        },
        `#${t}`,
      ),
    ),
    due || offer
      ? h(
          "button",
          { type: "button", className: "duechip", title: "Due date and priority", onclick: on.due },
          icon("due"),
          ...(due?.[1] ? [h("span", { className: "late" }, "overdue"), " "] : []),
          due ? due[0] : "Add due date",
        )
      : "",
    h(
      "button",
      {
        type: "button",
        className: "add",
        "aria-label": "Edit tags",
        title: "Edit tags",
        onclick: on.tags,
      },
      icon("add"),
    ),
  );
}
