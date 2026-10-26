// The names of the screens behind this one, by depth (go()'s `at`): each render writes its
// own entry's (a page's title once drawn, a list's name), so Back and the jump to the list
// name a page as it is now, renamed, stepped on by the pager, or replaced by its parent,
// rather than as it was when a link left it. Kept for the tab (sessionStorage: a reload keeps
// it); without storage, the name copied into the entry.

type Crumb = { path: string; name: string };
type Mark = { name: string; at: number };
const KEY = "scrap.crumbs";

function read(): Record<number, Crumb> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? "{}") ?? {};
  } catch {
    return {}; // no storage, or not ours
  }
}

/** The depth of the entry on screen: go()'s mark, 0 for one with none (opened cold); null for
 * an overlay's entry, which is no screen (the editor, Settings, a viewer, a drawing). */
export function depth(): number | null {
  const s = history.state;
  if (s?.editor || s?.settings || s?.viewer || s?.drawing) return null;
  return typeof s?.at === "number" ? s.at : 0;
}

/** Record the name of the entry on screen. */
export function remember(name: string) {
  const at = depth();
  if (at === null || !name) return;
  try {
    const r = read();
    r[at] = { path: location.pathname, name };
    sessionStorage.setItem(KEY, JSON.stringify(r));
  } catch {} // storage full or refused: the copied names serve
}

/** The name of the entry at a depth: as last drawn there, else the copy (m.name). */
export const named = (m: Mark) => read()[m.at]?.name ?? m.name;

/** The name recorded for a depth, if any. */
export const nameAt = (at: number): string | undefined => read()[at]?.name;
