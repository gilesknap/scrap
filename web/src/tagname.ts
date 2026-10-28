// Matching what is typed against the tags in use (the tag editor and Search's Filters → Tags).
// No DOM here (the unit tests run it).

/** The tags matching what is typed (q, cleaned): those starting with it first (a part after a
 * / counts: "bed" finds garden/beds), then those holding it. key: the tag of each. */
export function matching<T>(all: T[], q: string, key: (x: T) => string): T[] {
  const starts = all.filter((x) => {
    const t = key(x);
    return t.startsWith(q) || t.split("/").some((p) => p.startsWith(q));
  });
  return [...starts, ...all.filter((x) => !starts.includes(x) && key(x).includes(q))];
}
