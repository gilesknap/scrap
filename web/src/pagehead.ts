// A page's header under its title: the quiet meta line (what it is), the dates line (when it
// was created and edited), and one row of chips (its tags, each a search; + to change them; a
// todo's due chip, which opens the due editor).
import type { Page } from "./api";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { edited, metaParts } from "./pagemeta";
import { closed, dueChip } from "./status";
import { token } from "./terms";
import { h, whenShort } from "./ui";

/** Parts joined by " · ", each never breaking inside: a line breaks only after a ·. */
const joined = (parts: HTMLElement[]) => parts.flatMap((el, i) => (i ? [" · ", el] : [el]));

/** The meta line: "Later · TV · to watch", "Todo · in progress", "Note"; a topic's "Topic by
 * Claude" first, a page Claude wrote "Written by Claude" last. One size and colour, no red. */
export function metaLine(p: Page): HTMLElement {
  const label = p.topic ? undefined : KINDS.find(([k]) => k === p.kind)?.[1];
  const parts: HTMLElement[] = metaParts(p, label).map((text) => h("span", {}, text));
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
  return h("p", { className: "meta" }, ...joined(parts));
}

/** The dates line: "Created 24 Oct, 09:12 · Edited 25 Oct, 14:03", Edited only if it was. */
export const datesLine = (p: Page): HTMLElement =>
  h(
    "p",
    { className: "dates" },
    ...joined([
      h("span", {}, `Created ${whenShort(p.created_at)}`),
      ...(edited(p) ? [h("span", {}, `Edited ${whenShort(p.updated_at)}`)] : []),
    ]),
  );

interface Edits {
  tags: (e: Event) => void;
  due: (e: Event) => void;
  /** The due editor is open (under the row), so the row has no due chip meanwhile. */
  dueOpen: boolean;
}

/** One row of chips, all one size: its tags (each searches for its tag, with its children:
 * tag:a finds a/b), the + that changes them kept on the last tag's line, then a todo's due
 * chip. With no tags, "+ Tag". A closed todo with no due date or priority has no due chip
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
    ...tags,
    // The last tag and + together, so + never sits alone on a line
    last ? h("span", { className: "last" }, last, add) : add,
    due || offer
      ? h(
          "button",
          { type: "button", className: "duechip", title: "Due date and priority", onclick: on.due },
          icon("due"),
          ...(due?.[1] ? [h("span", { className: "late" }, "overdue"), " "] : []),
          due ? due[0] : "Add due date",
        )
      : "",
  );
}
