// Save's warning when an edit deletes the embed of a stored image: the page shows its images
// only where its text embeds them, so the image goes from the page with its line. Part of the
// editor's chunk. A file of this page's own (a photo, or any file it holds, such as a PDF)
// that no other page uses, in the trash or not, goes from its capture too, with all that was
// derived from it: Claude's reading and any drawing on it, the user's too (the server's
// Store._unlink), so the nightly scrap gc deletes the file; one another page uses is kept.
import { ApiError, api, type Page } from "./api";

// A file's address in text, as the server's store.body_refs reads it: any mention counts
const ADDRESS = /\/api\/blobs\/([0-9a-f]{64})/g;

/** The stored files a page's text refers to, by SHA-256. */
export const blobRefs = (text: string) => new Set([...text.matchAll(ADDRESS)].map((m) => m[1]));

/** Whether a file is one of the page's own (a capture's), not another page's. */
const own = (sha: string, p: Page) => p.captures.some((c) => c.blobs.some((b) => b.sha256 === sha));

// What goes with a file of the page's own: everything derived from it (Store._unlink)
const GONE = "what Claude read, described and drew from it, and any drawing you made on it";

/** What to call a file in the warning: its name, else its embed's alt text, else its start. */
function nameOf(sha: string, p: Page, text: string) {
  for (const c of p.captures)
    for (const b of c.blobs) if (b.sha256 === sha && b.filename) return b.filename;
  const alt = text.match(new RegExp(`!\\[([^\\]\\n]+)\\]\\(/api/blobs/${sha}`))?.[1]?.trim();
  return alt || `image ${sha.slice(0, 8)}`;
}

/** The warning for saving after (over before) on page p, or null if no stored file's embed
 * goes. Asks the server how many other pages show each; a file it doesn't hold is left out. */
export async function removalWarning(p: Page, before: string, after: string) {
  const kept = blobRefs(after);
  const gone = [...blobRefs(before)].filter((sha) => !kept.has(sha));
  let deleted = false; // a file of its own the nightly cleanup will (or may) delete
  const lines = await Promise.all(
    gone.map(async (sha) => {
      const name = nameOf(sha, p, before);
      try {
        const { pages, trashed } = await api<{ pages: number; trashed?: number }>(
          `blobs/${sha}/uses?page=${encodeURIComponent(p.id)}`,
        );
        if (pages) return `• ${name}: still shown on ${pages} other page${pages === 1 ? "" : "s"}`;
        if (trashed)
          return `• ${name}: no longer shown on any page; kept, as a page in the trash has it`;
        if (!own(sha, p)) return `• ${name}: no longer shown on any page`;
        deleted = true;
        return `• ${name}: no longer shown on any page, so the nightly cleanup deletes the file, with ${GONE}`;
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null; // not a file we hold
        if (!own(sha, p)) return `• ${name}: no longer shown here (other pages may still show it)`;
        deleted = true; // can't tell (offline, or the server failed): warn as if none does
        return `• ${name}: no longer shown here; unless another page has it, the nightly cleanup deletes the file, with ${GONE}`;
      }
    }),
  );
  const shown = lines.filter((l) => l !== null);
  if (!shown.length) return null;
  const n = shown.length;
  return [
    `Saving removes ${n === 1 ? "an image" : `${n} images`} from this page, because you deleted ${n === 1 ? "its line" : "their lines"}:`,
    ...shown,
    "",
    deleted
      ? "A deleted file can't be brought back once the cleanup has run."
      : "A file another page still shows is kept.",
    "",
    "Save anyway? Cancel to keep editing.",
  ].join("\n");
}

/** Save's check: true to go ahead (nothing goes, or the user said OK). */
export async function confirmRemoval(p: Page, before: string, after: string) {
  const warning = await removalWarning(p, before, after);
  return !warning || confirm(warning);
}
