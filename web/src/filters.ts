// What only the Filters panel needs of the query (a chunk of its own, out of the app shell): the
// orders, a picked date.
import { without, words } from "./terms";

const orders = (q: string) => words(q).filter(([, , key]) => key === "sort");

/** The orders a query has, as typed. */
export const sortsIn = (q: string) => orders(q).map(([a, b]) => q.slice(a, b));

/** The query without its orders. */
export const unsorted = (q: string) => without(q, orders(q));

/** A date picker's value as after:/before: take it (YYYY-MM-DD, years 1 to 9999), or ""
 * (a typed year past 9999 is clamped to 9999-12-31). */
export function day(v: string): string {
  if (v.length === 10 && v[4] === "-" && v[7] === "-") return v;
  return v.length > 10 && /^\+?\d{5,}-/.test(v) ? "9999-12-31" : "";
}
