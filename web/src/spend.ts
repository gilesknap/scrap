// What the photo panel says about Claude's spend (GET /api/ingest): a line once the month
// passes 80% of its cap, and why nothing is sent while the cap is reached. No DOM here (the
// unit tests run it); loaded with the photo panel, never in the app shell.
import type { Queue } from "./api";

const usd = (n: number) => `$${n.toFixed(2)}`;

/** True while the queue is paused because the month's spend reached its cap. */
export const capped = (q: Queue | null): boolean => q?.reason === "cap";

/** Why a photo is not sent while capped. */
export const cappedText = (q: Queue | null): string =>
  `Claude is paused: this month's spend reached its ${
    q?.monthly_cap_usd ? `${usd(q.monthly_cap_usd)} ` : ""
  }cap. Photos wait until next month or a higher cap.`;

/** "Claude this month: $16.20 of $20.00", once the month passes 80% of a cap; else null. */
export function spendLine(q: Queue | null): string | null {
  const cap = q?.monthly_cap_usd;
  if (!q || !cap || q.spent_month_usd < 0.8 * cap) return null;
  return `Claude this month: ${usd(q.spent_month_usd)} of ${usd(cap)}`;
}
