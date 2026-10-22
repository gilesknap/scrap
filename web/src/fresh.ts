// The composer's drafts: one kept draft (Capture's draft row), and a fresh capture's, made while
// one is kept. The fresh one is saved as it is typed under a key of its own, so an app killed
// mid-capture (an iPhone may, after the camera) loses nothing; it takes the kept draft's place
// when left by Back, or when found on the next open, with Undo to put the older one back.
import { drafts } from "./db";
import { toast } from "./ui";

export const DRAFT = "new"; // the kept draft
export const FRESH = "new-fresh"; // a fresh capture's, while another is kept

const changed = () => document.dispatchEvent(new Event("draftchange"));

/** The fresh draft, if there is one, made the kept draft; said: what to say, given whether it
 * replaced an older one (then with Undo). Whether there was one. */
export async function promote(said: (older: boolean) => string): Promise<boolean> {
  const [moved, older] = await drafts
    .move<unknown>(FRESH, DRAFT)
    .catch((): [undefined, undefined] => [undefined, undefined]);
  if (moved === undefined) return false;
  changed();
  if (older === undefined) toast(said(false));
  else toast(said(true), "Undo", () => void drafts.put(DRAFT, older).then(changed, () => {}), 8000);
  return true;
}

/** A fresh draft left behind by an app that was closed or killed: the kept draft now. */
export const recover = () =>
  promote((older) =>
    older
      ? "Recovered your unsaved capture, in place of the older draft"
      : "Recovered your unsaved capture",
  );
