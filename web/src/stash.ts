// Keeping a draft, for the editor (a lazy chunk).
import { drafts } from "./db";

/** Keep a draft. Whether it was kept: storage can refuse it (full, e.g. with large photos), and
 * then an older save under the key, if any, is what a later open would find. */
export const stash = (key: string, value: unknown): Promise<boolean> =>
  drafts.put(key, value).then(
    () => true,
    () => false,
  );

/** What to tell the user when a draft could not be kept. */
export const NOT_KEPT =
  "Couldn't keep a draft: the phone refused to store it (it may be full). Your text is still here: Save it, or free some space.";
