// The Todos screen's lists (todos.ts): what to do now, first. No DOM here, so the unit tests
// run it. Days are YYYY-MM-DD on this device's calendar (status.ts today()).
import type { Summary } from "./api";
import { dueMeets, duesIn } from "./dues";
import { snoozed, statusOf } from "./status";

type Todo = Pick<Summary, "kind" | "fields" | "due" | "priority" | "updated_at" | "snoozed_until">;

/** Not done or cancelled (open, in progress). */
export const isOpen = (t: Todo) =>
  !["done", "cancelled"].includes(String(statusOf(t.kind, t.fields)));

const RANKS: Record<string, number> = { high: 0, medium: 1, low: 2 };
const rank = (t: Todo) => RANKS[t.priority ?? ""] ?? 3; // none last
const due = (t: Todo) => t.due ?? "~"; // no date last
const recent = (t: Todo) => -Date.parse(t.updated_at); // last edited first

/** Compare by each key in turn. */
const by =
  <T>(...keys: ((t: T) => string | number)[]) =>
  (a: T, b: T) => {
    for (const k of keys) {
      const [x, y] = [k(a), k(b)];
      if (x !== y) return x < y ? -1 : 1;
    }
    return 0;
  };

/** To do now: open and not snoozed (snoozed ones come back on their day). */
export const toDo = (t: Todo, today: string) => isOpen(t) && !snoozed(t, today);

/** Now: the open todos (not snoozed) in groups, each in its order: Overdue (oldest due first), Today, High
 * priority with no date, then the rest, Open (by priority, then due, then last edited). Empty groups
 * are left out. */
export function now<T extends Todo>(list: T[], today: string): [string, T[]][] {
  const groups: [string, T[]][] = [
    ["Overdue", []],
    ["Today", []],
    ["High priority", []],
    ["Open", []], // not "Later": that is a kind
  ];
  for (const t of list.filter((t) => toDo(t, today))) {
    const late = t.due && t.due < today;
    groups[late ? 0 : t.due === today ? 1 : !t.due && t.priority === "high" ? 2 : 3][1].push(t);
  }
  const orders = [by(due, rank, recent), by(rank, recent), by(recent), by(rank, due, recent)];
  for (const [i, [, ts]] of groups.entries()) ts.sort(orders[i]);
  return groups.filter(([, ts]) => ts.length);
}

/** A day n days after day (YYYY-MM-DD), on the calendar: no clock, so no time zone. */
export function after(day: string, n: number) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export const AHEAD = 7; // Upcoming: from tomorrow to this many days away

/** Upcoming as a search: the Todos screen's view, which upcoming() reads its due: from. */
export const UPCOMING = `kind:todo due:>today due:<=${AHEAD}d sort:due`;

/** Upcoming: the open todos (not snoozed) due from tomorrow to a week away (UPCOMING's due:
 * terms), soonest first. */
export const upcoming = <T extends Todo>(list: T[], today: string) =>
  list
    .filter((t) => toDo(t, today) && duesIn(UPCOMING).every((v) => dueMeets(v, t.due, today)))
    .sort(by(due, rank, recent));
