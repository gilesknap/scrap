// Save's warning when an edit deletes the embed of a stored image: the page shows its images
// only where its text embeds them, so the image goes from the page with its line. Part of the
// editor's chunk. The file itself (and what Claude made of it) is kept while anything still
// uses it: another page, or this page's capture (see scrap gc).
import { ApiError, api, type Page } from "./api";

// A file's address in text, as the server's store.body_refs reads it: any mention counts
const ADDRESS = /\/api\/blobs\/([0-9a-f]{64})/g;

/** The stored files a page's text refers to, by SHA-256. */
export const blobRefs = (text: string) => new Set([...text.matchAll(ADDRESS)].map((m) => m[1]));

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
  const lines = await Promise.all(
    gone.map(async (sha) => {
      const name = nameOf(sha, p, before);
      try {
        const { pages } = await api<{ pages: number }>(
          `blobs/${sha}/uses?page=${encodeURIComponent(p.id)}`,
        );
        return pages
          ? `• ${name}: still shown on ${pages} other page${pages === 1 ? "" : "s"}`
          : `• ${name}: no longer shown on any page`;
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null; // not a file we hold
        return `• ${name}: no longer shown here (other pages may still show it)`; // offline: can't tell
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
    "This doesn't delete the stored file: a photo stays with its capture, and scrap gc deletes a file only once nothing uses it.",
    "",
    "Save anyway? Cancel to keep editing.",
  ].join("\n");
}

/** Save's check: true to go ahead (nothing goes, or the user said OK). */
export async function confirmRemoval(p: Page, before: string, after: string) {
  const warning = await removalWarning(p, before, after);
  return !warning || confirm(warning);
}
