// The status todos and Reads carry (open, in_progress, done or cancelled) and what ticks them
// off: on a page (page.ts) and its list row (rows.ts). No DOM here (the unit tests run it); not
// in kinds.ts, which the app shell would then carry whole.

type Fields = Record<string, unknown> | undefined;

/** A page's status, if it can be ticked off: a todo's or a Read's ("open" if it has none). */
export const statusOf = (kind: string, fields: Fields): string | null =>
  kind === "todo" || kind === "consume" ? String(fields?.status ?? "open") : null;

/** What its page offers, [label, the status it sets]: Mark done from any status but done,
 * Reopen from done or cancelled (a cancelled one has both); nothing without a status. */
export const ticks = (status: string | null): [string, string][] => [
  ...(status === null || status === "done" ? [] : [["Mark done", "done"] as [string, string]]),
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
  snoozed_until?: string | null;
  tasks?: { done: number; total: number };
}

/** Some of a todo's task boxes ticked, not all: "2 of 5" (its tick is shown partly done). */
export const partly = (p: Todo) =>
  !!p.tasks &&
  p.tasks.done > 0 &&
  p.tasks.done < p.tasks.total &&
  `${p.tasks.done} of ${p.tasks.total}`;

/** A day as a row says it: "3 Nov", with the year if it is not this one's. */
const short = (d: string, now: string) =>
  new Date(`${d}T12:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(d.slice(0, 4) !== now.slice(0, 4) && { year: "numeric" }),
  });

/** Snoozed: out of Now and the Todos tab's count until its day (not once done). */
export const snoozed = (p: Todo, now = today()) =>
  !!p.snoozed_until && p.snoozed_until > now && !closed(p);

/** Done or cancelled: a todo that is closed. */
export const closed = (p: Todo) => ["done", "cancelled"].includes(`${statusOf(p.kind, p.fields)}`);

/** What a todo's row and page say of its due date, priority and snooze ("high · due 3 Nov ·
 * snoozed till 1 Nov"), and its line's class: "due late" when overdue (due before today, not
 * done or cancelled), "due closed" once done or cancelled (greyed, its due date said as a date:
 * never today or overdue), else "due"; null if none. */
export function dueOf(p: Todo, now = today()): [string, string] | null {
  const until = snoozed(p, now) && p.snoozed_until;
  const shut = closed(p);
  const part = !shut && partly(p);
  if (p.kind !== "todo" || !(p.due || p.priority || until || part)) return null;
  const late = !!p.due && p.due < now && !shut;
  const day = p.due && (p.due === now && !shut ? "today" : short(p.due, now));
  const said = [
    p.priority,
    day && `${late ? "overdue" : "due"} ${day}`,
    until && `snoozed till ${short(until, now)}`,
    part,
  ];
  return [said.filter(Boolean).join(" · "), late ? "due late" : shut ? "due closed" : "due"];
}
