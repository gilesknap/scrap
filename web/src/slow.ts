/** Run slow() if work has not settled after ms (e.g. to show "Loading…"); work's result. */
export function whenSlow<T>(work: Promise<T>, ms: number, slow: () => void): Promise<T> {
  const timer = setTimeout(slow, ms);
  return work.finally(() => clearTimeout(timer));
}
