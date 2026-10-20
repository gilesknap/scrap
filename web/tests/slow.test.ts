import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { whenSlow } from "../src/slow";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("whenSlow", () => {
  it("says nothing for a quick answer", async () => {
    const slow = vi.fn();
    const work = whenSlow(Promise.resolve(1), 150, slow);
    await expect(work).resolves.toBe(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(slow).not.toHaveBeenCalled();
  });

  it("calls slow once a slow answer passes ms, then gives the answer", async () => {
    const slow = vi.fn();
    let done: (v: string) => void = () => {};
    const work = whenSlow(new Promise<string>((ok) => (done = ok)), 150, slow);
    await vi.advanceTimersByTimeAsync(149);
    expect(slow).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(slow).toHaveBeenCalledTimes(1);
    done("view");
    await expect(work).resolves.toBe("view");
  });

  it("passes a failure on, and stops the timer", async () => {
    const slow = vi.fn();
    await expect(whenSlow(Promise.reject(new Error("x")), 150, slow)).rejects.toThrow("x");
    await vi.advanceTimersByTimeAsync(1000);
    expect(slow).not.toHaveBeenCalled();
  });
});
