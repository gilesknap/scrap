// The Todos screen's lists (todos.ts): what to do now, first. No DOM here, so the unit tests
// run it. Days are YYYY-MM-DD on this device's calendar (status.ts today()).
import type { Summary } from "./api";
import { statusOf } from "./status";

type Todo = Pick<Summary, "kind" | "fields" | "due" | "priority" | "updated_at">;

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

/** Now: the open todos in groups, each in its order: Overdue (oldest due first), Today, High
 * priority with no date, then Later (by priority, then due, then last edited). Empty groups
 * are left out. */
export function now<T extends Todo>(list: T[], today: string): [string, T[]][] {
  const groups: [string, T[]][] = [
    ["Overdue", []],
    ["Today", []],
    ["High priority", []],
    ["Later", []],
  ];
  for (const t of list.filter(isOpen)) {
    const late = t.due && t.due < today;
    groups[late ? 0 : t.due === today ? 1 : !t.due && t.priority === "high" ? 2 : 3][1].push(t);
  }
  const orders = [by(due, rank, recent), by(rank, recent), by(recent), by(rank, due, recent)];
  for (const [i, [, ts]] of groups.entries()) ts.sort(orders[i]);
  return groups.filter(([, ts]) => ts.length);
}

/** Upcoming: the open todos due after today, soonest first. */
export const upcoming = <T extends Todo>(list: T[], today: string) =>
  list.filter((t) => isOpen(t) && !!t.due && t.due > today).sort(by(due, rank, recent));
