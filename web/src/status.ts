// The status todos and Laters carry (open, in_progress, done or cancelled) and what ticks them
// off: on a page (page.ts) and its list row (rows.ts). No DOM here (the unit tests run it); not
// in kinds.ts, which the app shell would then carry whole.

type Fields = Record<string, unknown> | undefined;

/** A page's status, if it can be ticked off: a todo's or a Later's ("open" if it has none). */
export const statusOf = (kind: string, fields: Fields): string | null =>
  kind === "todo" || kind === "consume" ? String(fields?.status ?? "open") : null;

/** What its page offers, [label, the status it sets]: Reopen once done or cancelled, else
 * Mark done; nothing without a status. */
export const ticks = (status: string | null): [string, string][] =>
  status === null
    ? []
    : status === "done" || status === "cancelled"
      ? [["Reopen", "open"]]
      : [["Mark done", "done"]];

/** A list row's chip: only a status that ends it (done, cancelled); its icon says its kind. */
export const chipOf = (kind: string, fields: Fields): string => {
  const s = statusOf(kind, fields);
  return s === "done" || s === "cancelled" ? s : "";
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

/** A todo's due day as it is said ("today", "3 Nov"; a closed one keeps its date) and whether it
 * is overdue (due before today, not done or cancelled). */
const dueDay = (p: Todo, now: string): [string | null | undefined, boolean] => {
  const shut = closed(p);
  return [
    p.due && (p.due === now && !shut ? "today" : short(p.due, now)),
    !!p.due && p.due < now && !shut,
  ];
};

/** A snooze as said: "snoozed till 3 Nov". */
export const snoozeText = (until: string, now = today()) => `snoozed till ${short(until, now)}`;

/** What a todo's row and page say of its due date, priority and snooze ("high · due 3 Nov ·
 * snoozed till 1 Nov"), and its line's class: "due late" when overdue (due before today, not
 * done or cancelled), "due closed" once done or cancelled (greyed, its due date said as a date:
 * never today or overdue), else "due"; null if none. */
export function dueOf(p: Todo, now = today()): [string, string] | null {
  const until = snoozed(p, now) && p.snoozed_until;
  const part = !closed(p) && partly(p);
  if (p.kind !== "todo" || !(p.due || p.priority || until || part)) return null;
  const [day, late] = dueDay(p, now);
  const said = [
    p.priority && (day ? p.priority : `${p.priority} priority`), // "low priority" alone
    day && `${late ? "overdue" : "due"} ${day}`,
    until && snoozeText(until, now),
    part,
  ];
  // Each part kept whole ("snoozed till 29 Oct" never breaks), the line breaking only before a
  // "·", which leads the part after it
  return [
    said
      .filter(Boolean)
      .map((s) => `${s}`.replace(/ /g, "\u00a0"))
      .join(" ·\u00a0"),
    late ? "due late" : closed(p) ? "due closed" : "due",
  ];
}

/** What a todo's due chip on its page says: its day and priority ("30 Oct · high", "today"),
 * and whether it is overdue; null with neither. */
export function dueChip(p: Todo, now = today()): [string, boolean] | null {
  if (p.kind !== "todo" || !(p.due || p.priority)) return null;
  const [day, late] = dueDay(p, now);
  return [[day, p.priority].filter(Boolean).join(" · "), late];
}
