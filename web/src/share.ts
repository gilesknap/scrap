// Turn a share-sheet POST (manifest share_target) into a capture.
import type { Capture } from "./queue";

const TRAILING_URL = /(?:^|\s)(https?:\/\/\S+)$/;

export function fromShare(form: FormData): Capture | null {
  const get = (k: string) => String(form.get(k) ?? "").trim();
  const title = get("title");
  let text = get("text");
  let url = get("url");
  // Android usually sends a link as text, often after the page title.
  const m = url ? null : text.match(TRAILING_URL);
  if (m) {
    url = m[1];
    text = text.slice(0, -m[1].length).trim();
  }
  if (title && !text.includes(title)) text = text ? `${title}\n\n${text}` : title;
  const files = form
    .getAll("files")
    .filter((f): f is File => typeof f !== "string" && f.size > 0)
    .map((f) => ({ name: f.name, blob: f as Blob }));
  if (!text && !url && !files.length) return null;
  return { text: text || undefined, url: url || undefined, source: "share", files };
}
