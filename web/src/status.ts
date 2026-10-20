// The status todos and Reads carry (open, in_progress, done or cancelled) and what ticks them
// off: on a page (page.ts) and its list row (rows.ts). No DOM here (the unit tests run it); not
// in kinds.ts, which the app shell would then carry whole.

type Fields = Record<string, unknown> | undefined;

/** A page's status, if it can be ticked off: a todo's or a Read's ("open" if it has none). */
export const statusOf = (kind: string, fields: Fields): string | null =>
  kind === "todo" || kind === "consume" ? String(fields?.status ?? "open") : null;

/** What its page offers, [label, the status it sets]: Done from any status but done, Reopen
 * from done or cancelled (a cancelled one has both); nothing without a status. */
export const ticks = (status: string | null): [string, string][] => [
  ...(status === null || status === "done" ? [] : [["Done", "done"] as [string, string]]),
  ...(status === "done" || status === "cancelled" ? [["Reopen", "open"] as [string, string]] : []),
];

const CHIP: Record<string, string> = { todo: "todo", consume: "read" };
/** A list row's chip: a status that ends it (done, cancelled), else its kind (todo, read). */
export const chipOf = (kind: string, fields: Fields): string => {
  const s = statusOf(kind, fields);
  return s === "done" || s === "cancelled" ? s : (CHIP[kind] ?? "");
};
