// A todo's due: terms, read by the Todos screen's Now (a chunk of its own, not the app shell)
import { keyed, wordValue } from "./terms";

// ---- due: a todo's due day, as the server reads it (scrap/query.py due), plus days from
// today: due:<=7d (on or before 7 days from now), due:>=2w; d, w, m (30 days) and y as after:
// takes them, the number 1 to 100 and left out for 1

const SAID_DAYS: Record<string, number> = { yesterday: -1, today: 0, tomorrow: 1 };
const UNIT_DAYS: Record<string, number> = { d: 1, w: 7, m: 30, y: 365 };

/** A day n days after day (YYYY-MM-DD), on the calendar. */
const plus = (day: string, n: number) => {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** A due: value as a comparison with a day ("<=" and YYYY-MM-DD), "none" (no due date),
 * or null (matches nothing). today: YYYY-MM-DD. */
export function dueBound(value: string, today: string): [string, string] | "none" | null {
  const v = value.toLowerCase();
  const op = [">=", "<=", ">", "<", "="].find((o) => v.startsWith(o)) ?? "=";
  const d = v.slice(v.startsWith(op) ? op.length : 0);
  if (d === "none") return op === "=" ? "none" : null;
  if (d in SAID_DAYS) return [op, plus(today, SAID_DAYS[d])];
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) return [op, d];
  const unit = UNIT_DAYS[d.slice(-1)];
  const n = d.length > 1 ? Number(d.slice(0, -1)) : 1;
  if (!unit || !/^\d{0,3}$/.test(d.slice(0, -1)) || n < 1 || n > 100) return null;
  return [op, plus(today, n * unit)];
}

/** Whether a todo's due day (or none) meets a due: value. */
export function dueMeets(value: string, due: string | null | undefined, today: string) {
  const b = dueBound(value, today);
  if (b === null) return false;
  if (b === "none") return !due;
  if (!due) return false;
  const [op, day] = b;
  return op === "<"
    ? due < day
    : op === "<="
      ? due <= day
      : op === ">"
        ? due > day
        : op === ">="
          ? due >= day
          : due === day;
}

/** The query's due: values (not -due:). */
export const duesIn = (q: string) =>
  keyed(q, "due")
    .filter(([a]) => !"-!".includes(q[a]))
    .map((w) => wordValue(q, w));
