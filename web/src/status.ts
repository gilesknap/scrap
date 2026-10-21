// The status todos and Reads carry (open, in_progress, done or cancelled) and what ticks them
// off: on a page (page.ts) and its list row (rows.ts). No DOM here (the unit tests run it); not
// in kinds.ts, which the app shell would then carry whole.

type Fields = Record<string, unknown> | undefined;

/** A page's status, if it can be ticked off: a todo's or a Read's ("open" if it has none). */
export const statusOf = (kind: string, fields: Fields): string | null =>
  kind === "todo" || kind === "consume" ? String(fields?.status ?? "open") : null;

/** What its page offers, [label, the status it sets]: Done from any status but done, Reopen
 * from done or cancelled (a cancelled one has both); nothing without a status. */
export const ticks = (status: string | null): [string, string][] => [
  ...(status === null || status === "done" ? [] : [["Done", "done"] as [string, string]]),
  ...(status === "done" || status === "cancelled" ? [["Reopen", "open"] as [string, string]] : []),
];

const CHIP: Record<string, string> = { todo: "todo", consume: "read" };
/** A list row's chip: a status that ends it (done, cancelled), else its kind (todo, read). */
export const chipOf = (kind: string, fields: Fields): string => {
  const s = statusOf(kind, fields);
  return s === "done" || s === "cancelled" ? s : (CHIP[kind] ?? "");
};

// ---- a todo's due date and priority (#104): columns of its page, a todo's only

/** Today on this device, as a due date is written (YYYY-MM-DD). */
export const today = (d = new Date()) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);

interface Todo {
  kind: string;
  fields?: Fields;
  due?: string | null;
  priority?: string | null;
}

/** What a todo's row and page say of its due date and priority ("high · due 3 Nov"), and
 * whether it is overdue (due before today and not done or cancelled); null if neither. */
export function dueOf(p: Todo, now = today()): [string, boolean] | null {
  if (p.kind !== "todo" || !(p.due || p.priority)) return null;
  const status = statusOf(p.kind, p.fields);
  const late = !!p.due && p.due < now && status !== "done" && status !== "cancelled";
  const day =
    p.due &&
    (p.due === now
      ? "today"
      : new Date(`${p.due}T12:00`).toLocaleDateString(undefined, {
          day: "numeric",
          month: "short",
          ...(p.due.slice(0, 4) !== now.slice(0, 4) && { year: "numeric" }),
        }));
  const said = [p.priority, day && `${late ? "overdue" : "due"} ${day}`];
  return [said.filter(Boolean).join(" · "), late];
}
