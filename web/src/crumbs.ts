// The names of the screens behind this one, by depth (go()'s `at`): each screen writes its
// own entry's (a list's when drawn, a page's title each time it is shown, so renamed in place
// too), so Back and the jump to the list name a page as it is now, renamed, stepped on by the
// pager, or replaced by its parent, rather than as it was when a link left it. Kept for the tab
// in sessionStorage, so a reload keeps it, and in memory, so a browser that refuses storage
// still has it until a reload (then the name copied into the entry serves).

type Crumb = { path: string; name: string };
type Mark = { name: string; at: number; path?: string };
const KEY = "scrap.crumbs";
let mirror: Record<number, Crumb> = {};

function read(): Record<number, Crumb> {
  try {
    const kept = sessionStorage.getItem(KEY);
    if (kept) mirror = JSON.parse(kept) ?? {};
  } catch {} // no storage, or not ours: the mirror
  return mirror;
}

/** The depth of the entry on screen: go()'s mark, 0 for one with none (opened cold); null for
 * an overlay's entry, which is no screen (the editor, Settings, a viewer, a drawing). */
function depth(): number | null {
  const s = history.state;
  if (s?.editor || s?.settings || s?.viewer || s?.drawing) return null;
  return typeof s?.at === "number" ? s.at : 0;
}

/** Record the name of the entry on screen. */
export function remember(name: string) {
  const at = depth();
  if (at === null || !name) return;
  mirror = { ...read(), [at]: { path: location.pathname, name } };
  try {
    sessionStorage.setItem(KEY, JSON.stringify(mirror));
  } catch {} // storage full or refused: the mirror serves
}

/** The name of the entry at a depth: as last drawn there, else the copy (m.name). A mark that
 * says where it was (a list's) takes only a name recorded there, so a depth that drifted from
 * the history never names it wrong. */
export function named(m: Mark) {
  const c = read()[m.at];
  return c && (!m.path || c.path === m.path) ? c.name : m.name;
}

/** The name recorded for a depth, if any. */
export const nameAt = (at: number): string | undefined => read()[at]?.name;
