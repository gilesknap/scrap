import { describe, expect, it } from "vitest";
import type { Queue } from "../src/api";
import { capped, cappedText, spendLine } from "../src/spend";

const queue = (o: Partial<Queue>): Queue => ({
  enabled: true,
  paused: false,
  reason: null,
  paused_until: null,
  spent_month_usd: 0,
  monthly_cap_usd: 20,
  ...o,
});

describe("spend", () => {
  it("says nothing below 80% of the cap, or with no cap", () => {
    expect(spendLine(queue({ spent_month_usd: 15.99 }))).toBeNull();
    expect(spendLine(queue({ spent_month_usd: 99, monthly_cap_usd: null }))).toBeNull();
    expect(spendLine(null)).toBeNull();
  });

  it("gives the month's spend from 80% of the cap", () => {
    expect(spendLine(queue({ spent_month_usd: 16.2 }))).toBe("Claude this month: $16.20 of $20.00");
  });

  it("explains a capped queue", () => {
    const q = queue({ paused: true, reason: "cap", spent_month_usd: 19.8 });
    expect(capped(q)).toBe(true);
    expect(capped(queue({ paused: true, reason: "budget" }))).toBe(false);
    expect(cappedText(q)).toBe(
      "Claude is paused: this month's spend reached its $20.00 cap. Photos wait until next month or a higher cap.",
    );
  });
});
