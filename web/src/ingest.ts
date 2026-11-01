// What Claude made of a photo, under it on the page: its ingest state with Regenerate, Retry or
// Resume, the description and text it read, and its drawing beside the photo (side by side
// when there is room, else a Photo / Drawing switch).
import { ApiError, api, type FileRef, type Ingest, type Queue } from "./api";
import "./excalidraw.css";
import { drawingCard, openDrawing, type Target } from "./drawing";
import { readingFold, readingState } from "./reading";
import { h, toast } from "./ui";

/** The chip's words for a state. */
function stateText(i: Ingest, q: Queue | null): string {
  switch (i.state) {
    case "queued":
      return q && !q.enabled ? "Waiting: Claude ingest is off" : "Waiting for Claude";
    case "processing":
      return "Claude is reading it…";
    case "done":
      return "Read by Claude";
    case "failed":
      return `Failed${i.error ? `: ${i.error}` : ""}`;
    case "paused":
      return `Paused${q?.reason ? ` (${q.reason})` : ""}: nothing is lost`;
  }
}

/** The photo card's title: what it holds (figure.ts's card for an unread photo says it too). */
export const PHOTO = "What's in the photo";

const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

export function photoPanel(o: {
  cid: string;
  blob: FileRef & { ingest: Ingest };
  figure: HTMLElement; // the photo as the page shows it
  photo: string; // its preview URL
  slug: string;
  queue: Queue | null;
  refresh: (drawn?: boolean) => void; // fetch and show the page again (drawn: a drawing saved)
}): HTMLElement {
  const i = o.blob.ingest;
  const panel = h("section", { className: "photo-panel" });
  const t: Target = {
    cid: o.cid,
    sha: o.blob.sha256,
    name: o.blob.filename || "",
    photo: o.photo,
    slug: o.slug,
  };

  // The photo, and its drawing beside it
  if (i.drawing) {
    const d = i.drawing;
    const frame = d.width && d.height ? { width: d.width, height: d.height } : null;
    const open = () => openDrawing(t, () => o.refresh(true));
    // (its id and photo say which drawing it is, for the publish mode: publicpages.ts)
    const drawing = h(
      "figure",
      {
        className: "orig drawing",
        "data-drawing": String(d.id),
        "data-cid": o.cid,
        "data-sha": o.blob.sha256,
      },
      drawingCard(t, { id: d.id, frame }, open),
    );
    const pair = h("div", { className: "pair show-drawing" }, o.figure, drawing);
    const tabs = h("div", { className: "tabs", role: "tablist", "aria-label": "Show" });
    const tab = (label: string, which: "photo" | "drawing") => {
      const b = h("button", { type: "button", role: "tab" }, label);
      b.onclick = () => {
        pair.className = `pair show-${which}`;
        for (const x of tabs.children) x.setAttribute("aria-selected", String(x === b));
      };
      b.setAttribute("aria-selected", String(which === "drawing"));
      return b;
    };
    tabs.append(tab("Photo", "photo"), tab("Drawing", "drawing"));
    panel.append(tabs, pair);
  } else panel.append(o.figure);

  // Where the reading is up to, outside the fold (#521): never hidden in it while it isn't done
  // (a pill, with Retry or Resume); nothing once read
  const reprocess = async (replace: boolean) => {
    try {
      const r = await api<{ queued: number; already: number }>(`captures/${o.cid}/reprocess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo: o.blob.sha256, replace_human: replace }),
      });
      toast(r.queued ? "Sent to Claude again" : "Already waiting for Claude");
      o.refresh();
    } catch (err) {
      toast(`Not sent: ${why(err)}`);
    }
  };
  const resume = async () => {
    try {
      await api("ingest/resume", { method: "POST" });
      o.refresh();
    } catch (err) {
      toast(`Not resumed: ${why(err)}`);
    }
  };
  if (i.state !== "done")
    panel.append(
      readingState(
        stateText(i, o.queue),
        i.state,
        i.state === "failed"
          ? { label: "Retry", onclick: () => void reprocess(false) }
          : i.state === "paused"
            ? { label: "Resume", onclick: () => void resume() }
            : null,
      ),
    );
  const ask = () => {
    if (i.drawing?.producer !== "human") return void reprocess(false);
    if (panel.querySelector(".choice")) return; // asked already
    // Never replace a drawing the user made without asking
    const choice = h(
      "div",
      { className: "choice", role: "group", "aria-label": "Your drawing" },
      h("p", {}, "Claude will read the photo again. You edited its drawing: replace it?"),
      h("button", { type: "button", onclick: () => void reprocess(true) }, "Replace mine"),
      h(
        "button",
        { type: "button", onclick: () => void reprocess(false) },
        "Keep mine (theirs goes to History)",
      ),
    );
    choice.append(h("button", { type: "button", onclick: () => choice.remove() }, "Cancel"));
    panel.append(choice);
  };
  // What Claude read from it, in one closed fold: its description and the text in it, and
  // Regenerate (only once read). None until there is something to show.
  if (i.description || i.text)
    panel.append(
      readingFold({
        body: [
          i.description && h("p", { className: "desc" }, i.description),
          i.text && h("pre", {}, i.text),
        ],
        regen: i.state === "done" ? { label: "Regenerate", onclick: ask } : null,
      }),
    );
  return panel;
}
