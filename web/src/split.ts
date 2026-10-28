// A capture split into one per file, for files too big to send together (the composer's Save
// separately, a failed row's Split and retry). Not in the app shell: the composer's chunk and
// the failed row's (rowbar.ts) load it.
import type { Capture } from "./queue";

// A token placing one of the capture's files in its text, as the server reads them (#403):
// ⟦image N⟧ or ⟦file N⟧, N the file's place among those sent, from 1
const SENT = /⟦(?:image|file) (\d+)(?::[^⟦⟧\n]*)?⟧/g;

/** text with only the first file's tokens: the others' go (a line left empty by them, too),
 * as their files go to pages of their own. */
export const firstOnly = (text: string) =>
  text
    .split("\n")
    .flatMap((line) => {
      const left = line.replace(SENT, (t, n) => (n === "1" ? t : ""));
      return left.trim() || !line.trim() ? [left] : [];
    })
    .join("\n");

/** One capture per file, the text (with that file's token only) with the first. Each page gets
 * the tags and the kind (or an older build's hint), if any. */
export const split = (c: Capture): Capture[] =>
  c.files.map((f, i) => {
    const text = !i && c.text ? firstOnly(c.text) : undefined;
    const part: Capture = { ...(!i && { text, url: c.url }), source: c.source, files: [f] };
    // The text once; the kind, its due date and priority, and the tags on every part
    for (const k of ["kind", "hint", "tags", "due", "priority", "page", "to"] as const)
      if (c[k]) Object.assign(part, { [k]: c[k] });
    return part;
  });
