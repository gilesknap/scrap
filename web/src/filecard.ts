// A file's card under its row on a page (a PDF, a text or Markdown file), in the shape of a
// photo's (ingest.ts photoPanel): its title, where the reading is up to while it isn't done,
// what was found (pages, whether search can find it), a PDF's text in a fold, and Retry or
// Regenerate. scrap reads a file itself, for search (#234): no model is involved, so the card
// never says Claude. Part of the figure chunk.
import { ApiError, api, type FileIngest, type FileRef, kept } from "./api";
import { fileFacts } from "./filerow";
import { h, toast } from "./ui";

/** The file card's title, as the photo card's is PHOTO. */
export const FILE = "What's in the file";

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

/** A PDF's text as scrap read it, folded until opened (and then open next time: remembered,
 * as the photo card's folds are); fetched the first time it opens. */
function readText(cid: string, sha: string) {
  const key = "scrap.fold.Text read from it";
  const head = h("summary", {}, "Text read from it");
  const body = h("pre", {}, "…");
  const el = h("details", { className: "claude-text" }, head, body);
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
  el.addEventListener("toggle", () => el.open && void load());
  head.onclick = () => kept(key, el.open ? null : "open");
  if (kept(key) === "open") el.open = true; // its toggle loads it
  return el;
}

/** The row (filerow.ts: its name, link and Download) with the card under it. */
export function fileCard(o: {
  cid: string;
  blob: FileRef;
  row: HTMLElement;
  refresh: () => void; // fetch and show the page again
}): HTMLElement {
  const i = o.blob.ingest && "kind" in o.blob.ingest ? o.blob.ingest : null;
  const pill =
    i && i.state !== "done"
      ? h("span", { className: `state ${i.state}`, role: "status" }, fileStateText(i))
      : "";
  const actions = h("div", { className: "ingest" }, h("h3", { className: "ctitle" }, FILE), pill);
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
  // Named as the photo card's: Retry when it failed, Regenerate (a quiet text button) once
  // read, Generate for a file never queued (attached before scrap read files)
  if (!i) actions.append(h("button", { type: "button", onclick: () => void again() }, "Generate"));
  else if (i.state === "failed")
    actions.append(h("button", { type: "button", onclick: () => void again() }, "Retry"));
  else if (i.state === "done")
    actions.append(
      h("button", { type: "button", className: "link", onclick: () => void again() }, "Regenerate"),
    );
  const says = fileSays(i);
  return h(
    "section",
    { className: "file-panel" },
    o.row,
    h(
      "div",
      { className: "claude" },
      actions,
      says ? h("p", { className: "did" }, says) : "",
      // Only a PDF's: what extraction found. A text file's own link opens its text
      i?.state === "done" && i.searchable && isPdf(o.blob) ? readText(o.cid, o.blob.sha256) : "",
    ),
  );
}
