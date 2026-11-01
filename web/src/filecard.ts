// A file's card under its row on a page (a PDF, a text or Markdown file), in the shape of a
// photo's (ingest.ts photoPanel): where the reading is up to while it isn't done (Retry when it
// failed), and once read the fold, "Claude's reading" as a photo's is (#521: one label for
// both, though scrap reads a file itself, for search, #234), with what was found (pages,
// whether search can find it), a PDF's text and Regenerate. Part of the figure chunk.
import { ApiError, api, type FileIngest, type FileRef } from "./api";
import { fileFacts } from "./filerow";
import { readingFold, readingState } from "./reading";
import { h, toast } from "./ui";

/** The state line's words while a file's reading isn't done. */
export function fileStateText(i: FileIngest): string {
  switch (i.state) {
    case "queued":
      return "Waiting to be read";
    case "processing":
      return "Reading the text…";
    case "done":
      return "Read";
    case "failed":
      return `Couldn't read it${i.error ? `: ${i.error}` : ""}`;
  }
}

/** What the card says was found: "12 pages · searchable", or why search can't find it. */
export function fileSays(i: FileIngest | null): string | null {
  if (!i || i.state === "queued" || i.state === "processing") return null;
  const { pages, hint } = fileFacts(i);
  return [pages, hint ?? "Searchable"].filter(Boolean).join(" · ");
}

const isPdf = (f: FileRef) => f.mime.split(";")[0].trim().toLowerCase() === "application/pdf";
const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

/** A PDF's text as scrap read it, fetched the first time the fold opens. Its capture and file
 * are on it, so publishing (publicpages.ts) can fetch the text the fold would show. */
function readText(cid: string, sha: string) {
  const body = h("pre", { className: "filetext", "data-cid": cid, "data-sha": sha }, "…");
  let asked = false;
  const load = async () => {
    if (asked) return;
    asked = true;
    try {
      const r = await api<{ text: string | null; truncated: boolean }>(
        `captures/${cid}/files/${sha}/text`,
      );
      body.textContent = r.text
        ? r.text + (r.truncated ? "\n\n… (the start only: search has it all)" : "")
        : "No text was found in it.";
    } catch (err) {
      asked = false; // try again on the next open
      body.textContent = `Not shown: ${why(err)}`;
    }
  };
  return { body, load };
}

/** The row (filerow.ts: its name and link) with, under it, where its reading is up to while it
 * isn't done (Retry when it failed) and the fold with what was read (#521). */
export function fileCard(o: {
  cid: string;
  blob: FileRef;
  row: HTMLElement;
  refresh: () => void; // fetch and show the page again
}): HTMLElement {
  const i = o.blob.ingest && "kind" in o.blob.ingest ? o.blob.ingest : null;
  const again = async () => {
    try {
      const r = await api<{ queued: number; already: number }>(`captures/${o.cid}/reprocess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo: o.blob.sha256 }),
      });
      toast(r.queued ? "Reading it again" : "Already waiting to be read");
      o.refresh();
    } catch (err) {
      toast(`Not sent: ${why(err)}`);
    }
  };
  const panel = h("section", { className: "file-panel" }, o.row);
  if (i && i.state !== "done")
    panel.append(
      readingState(
        fileStateText(i),
        i.state,
        i.state === "failed" ? { label: "Retry", onclick: () => void again() } : null,
      ),
    );
  const says = fileSays(i);
  const text =
    i?.state === "done" && i.searchable && isPdf(o.blob) ? readText(o.cid, o.blob.sha256) : null;
  // Generate for a file never queued (attached before scrap read files), Regenerate once read
  if (!i || i.state === "done")
    panel.append(
      readingFold({
        body: [
          h(
            "p",
            { className: "did" },
            i ? (says ?? "") : "Not read yet: search can't find its text.",
          ),
          text?.body,
        ],
        regen: { label: i ? "Regenerate" : "Generate", onclick: () => void again() },
        onOpen: text ? () => void text.load() : undefined,
      }),
    );
  return panel;
}
