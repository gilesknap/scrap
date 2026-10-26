// The Trash screen (#276), opened from Settings: the pages in the trash (GET /api/trash), most
// recently deleted first, each with when it was deleted, when scrap purges it for good (the
// nightly gc, after SCRAP_TRASH_DAYS) and Restore. A topic page is kept there: its key stops
// Claude making the topic again. A chunk of its own.
import { api } from "./api";
import { go } from "./app";
import { icon } from "./icons";
import { why } from "./swipe";
import "./trash.css";
import { empty, h, toast } from "./ui";

export interface Trashed {
  id: string;
  slug: string;
  title: string;
  kind: string;
  deleted_at: string;
  topic: boolean;
  purge_at: string | null;
}

/** A date as a row says it: "3 Oct", with the year only if it is not this year's. */
export function day(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const year = d.getFullYear() !== now.getFullYear() && "numeric";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(year && { year }) });
}

/** What happens to a page in the trash, in words: when it was deleted and when it goes. */
export function fate(t: Trashed, now = new Date()): string {
  const deleted = `Deleted ${day(t.deleted_at, now)}`;
  if (t.topic) return `${deleted} · kept: Claude won't make this topic again`;
  if (!t.purge_at) return deleted;
  if (new Date(t.purge_at) <= now) return `${deleted} · deleted for good tonight`;
  return `${deleted} · deleted for good after ${day(t.purge_at, now)}`;
}

/** The hint over the list: how long a page stays. */
export const stay = (days: number | null) =>
  days === null
    ? "Deleted pages stay here until you restore them."
    : `Deleted pages stay here for ${days} days, then scrap deletes them for good, with the photos and files no other page uses. Restore one to bring it back.`;

function row(t: Trashed, list: HTMLUListElement, gone: () => void): HTMLLIElement {
  const restore = h(
    "button",
    { type: "button", "aria-label": `Restore ${t.title}` },
    icon("retry"),
    "Restore",
  );
  const li = h(
    "li",
    {},
    h(
      "div",
      {},
      h("span", {}, h("strong", { dir: "auto" }, t.title), h("small", {}, fate(t))),
      restore,
    ),
  );
  restore.onclick = async () => {
    restore.disabled = true;
    try {
      await api(`pages/${encodeURIComponent(t.id)}/undelete`, { method: "POST" });
    } catch (err) {
      restore.disabled = false;
      return toast(`Not restored: ${why(err)}`);
    }
    const next = (li.nextElementSibling ?? li.previousElementSibling)?.querySelector("button");
    li.remove();
    if (!list.children.length) gone();
    else (next as HTMLButtonElement | null)?.focus();
    toast(`Restored: ${t.title}`, "Open", () => go(`/p/${encodeURIComponent(t.slug)}`), 8000);
  };
  return li;
}

export async function trash(signal: AbortSignal): Promise<Node> {
  const { days, results } = await api<{ days: number | null; results: Trashed[] }>("trash", {
    signal,
  });
  const none = () => empty("trash", "The trash is empty.");
  const list = h("ul", { className: "list" });
  const section = h(
    "section",
    { className: "trash" },
    h("h2", { className: "label" }, "Trash"),
    h("p", { className: "hint" }, stay(days)),
  );
  const gone = () => list.replaceWith(none());
  list.append(...results.map((t) => row(t, list, gone)));
  section.append(results.length ? list : none());
  return section;
}
