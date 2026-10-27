// A file listed below a page's text that is not shown as a photo (a PDF, a text file, an image
// the server can't preview): its name, a link that opens it, a PDF's page count once read, and
// Download. A short hint only when its text couldn't be read for search (#234): nothing while
// it waits or is being read, nor for a file never queued.
import type { FileIngest, Ingest } from "./api";
import { icon } from "./icons";
import { h } from "./ui";

export const UNREAD = "Text couldn't be read; not searchable";
/** A failure that may not repeat (the reader timed out or didn't start): not the file's fault. */
export const RETRY = "Text couldn't be read this time; not searchable. Try Reprocess";

/** What a file's row says besides its name: its pages ("12 pages", a PDF's once read) and
 * the hint, if its reading failed or found no text. Nothing for a photo's ingest. */
export function fileFacts(i: Ingest | FileIngest | null | undefined): {
  pages: string | null;
  hint: string | null;
} {
  if (!i || !("kind" in i)) return { pages: null, hint: null };
  const pages = i.pages == null ? null : `${i.pages} page${i.pages === 1 ? "" : "s"}`;
  const unread = i.state === "failed" || (i.state === "done" && !i.searchable);
  const transient = i.state === "failed" && /^(timeout|internal):/.test(i.error ?? "");
  return { pages, hint: unread ? (transient ? RETRY : UNREAD) : null };
}

export function fileRow(
  href: string,
  name: string,
  save: HTMLElement,
  ingest?: Ingest | FileIngest | null,
): HTMLElement {
  const { pages, hint } = fileFacts(ingest);
  const words = h(
    "span",
    { className: "words" },
    h("span", {}, name),
    pages && h("small", {}, pages),
  );
  return h(
    "div",
    { className: "orig filerow" },
    h("a", { href, target: "_blank", className: "file" }, icon("file"), words),
    hint && h("p", { className: "hint" }, hint),
    save,
  );
}
