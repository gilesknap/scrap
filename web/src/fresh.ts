// The composer's drafts: one kept draft (Capture's draft row), and a fresh capture's, made while
// one is kept. The fresh one is saved as it is typed under a key of its own, so an app killed
// mid-capture (an iPhone may, after the camera) loses nothing; it takes the kept draft's place
// when left by Back, or when found on the next open, with Undo to put the older one back.
// Each fresh composer has its own key, held by a Web Lock of that name while it is open: the
// browser lets go of it when the tab is closed or killed, so a fresh draft whose lock is free
// was left behind, and one whose lock is held is another tab's, still being typed (#139).
import { drafts } from "./db";
import { toast } from "./ui";

export const DRAFT = "new"; // the kept draft
export const FRESH = "new-fresh"; // fresh captures' keys start with it (older builds': it alone)

const changed = () => document.dispatchEvent(new Event("draftchange"));
/** The Web Lock a fresh draft's composer holds while open (freshlock.ts). */
export const lockName = (key: string) => `scrap-${key}`;
export const locks = () => globalThis.navigator?.locks;

/** The fresh draft under key, if there is one, made the kept draft; said: what to say, given
 * whether it replaced an older one (then with Undo). Whether there was one. */
export async function promote(key: string, said: (older: boolean) => string): Promise<boolean> {
  const [moved, older] = await drafts
    .move<unknown>(key, DRAFT)
    .catch((): [undefined, undefined] => [undefined, undefined]);
  if (moved === undefined) return false;
  changed();
  if (older === undefined) toast(said(false));
  else toast(said(true), "Undo", () => void drafts.put(DRAFT, older).then(changed, () => {}), 8000);
  return true;
}

/** Run fn holding key's lock, if no one holds it; without Web Locks, run it. */
const ifFree = (key: string, fn: () => Promise<boolean>): Promise<boolean> => {
  const l = locks();
  if (!l) return fn();
  return l
    .request(lockName(key), { ifAvailable: true }, (got) => (got ? fn() : false))
    .catch(() => false);
};

/** A fresh draft left behind by an app that was closed or killed (no tab holds its lock): the
 * kept draft now. Whether one was. */
export async function recover(): Promise<boolean> {
  const keys = await drafts.keys(FRESH).catch((): string[] => []);
  // Several left behind (tabs killed mid-capture): the oldest, one per open, so each later one
  // goes over the last with Undo for it, and none is lost unasked. (getAllKeys is in key
  // order, and the keys are ulids: oldest first; an older build's bare FRESH before them all.)
  for (const key of keys) {
    const said = (older: boolean) =>
      older
        ? "Recovered your unsaved capture, in place of the older draft"
        : "Recovered your unsaved capture";
    if (await ifFree(key, () => promote(key, said))) return true;
  }
  return false;
}
