// A tag's short name, as a page's chip row and the tag picker say it: its last part, with as
// much of its path as tells it from the other tags shown. No DOM here (the unit tests run it).

/** What a page's tag chips say: each tag's last part ("kind/project-management" is
 * "project-management"), with as many parts before it as tell it from the page's other tags
 * that end the same ("epics/thoth" beside "other/thoth"). */
export function tagNames(tags: string[]): Map<string, string> {
  const parts = tags.map((t) => t.split("/"));
  const depth = tags.map(() => 1);
  const said = (i: number) => parts[i].slice(-depth[i]).join("/");
  for (let more = true; more; ) {
    // every tag whose name another shares takes one more part, all at once
    const now = tags.map((_, i) => said(i));
    const clash = now.map((n, i) => now.some((m, j) => i !== j && m === n));
    more = false;
    clash.forEach((c, i) => {
      if (c && depth[i] < parts[i].length) {
        depth[i]++;
        more = true;
      }
    });
  }
  return new Map(tags.map((t, i) => [t, said(i)]));
}

/** The tags matching what is typed (q, cleaned): those starting with it first (a part after a
 * / counts: "bed" finds garden/beds), then those holding it. key: the tag of each. */
export function matching<T>(all: T[], q: string, key: (x: T) => string): T[] {
  const starts = all.filter((x) => {
    const t = key(x);
    return t.startsWith(q) || t.split("/").some((p) => p.startsWith(q));
  });
  return [...starts, ...all.filter((x) => !starts.includes(x) && key(x).includes(q))];
}
