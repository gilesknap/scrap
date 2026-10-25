// What Claude made of a photo, under it on the page: its ingest state with Regenerate, Retry or
// Resume, the description and text it read, and its drawing beside the photo (side by side
// when there is room, else a Photo / Drawing switch).
import { ApiError, api, type FileRef, type Ingest, kept, type Queue } from "./api";
import "./excalidraw.css";
import { drawingCard, openDrawing, type Target } from "./drawing";
import { h, toast } from "./ui";

/** The chip's words for a state. */
export function stateText(i: Ingest, q: Queue | null): string {
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

/** A selectable block of text Claude wrote, folded until opened (and then open next time:
 * remembered). */
function block(summary: string, text: string, pre = false) {
  const key = `scrap.fold.${summary}`;
  const head = h("summary", {}, summary);
  const el = h(
    "details",
    { className: "claude-text", open: kept(key) === "open" },
    head,
    h(pre ? "pre" : "p", {}, text),
  );
  // Remembered as it is tapped (it is about to change), not on toggle: see enrich.ts's fold
  head.onclick = () => kept(key, el.open ? null : "open");
  return el;
}

export function photoPanel(o: {
  cid: string;
  blob: FileRef & { ingest: Ingest };
  figure: HTMLElement; // the photo as the page shows it
  photo: string; // its preview URL
  slug: string;
  queue: Queue | null;
  refresh: () => void; // fetch and show the page again
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
    const open = () => openDrawing(t, o.refresh);
    const drawing = h(
      "figure",
      { className: "orig drawing" },
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

  // Its state, and what can be done about it
  // Its title says what the card holds; the pill only where Claude is up to (none once read)
  const chip =
    i.state !== "done" &&
    h("span", { className: `state ${i.state}`, role: "status" }, stateText(i, o.queue));
  const actions = h("div", { className: "ingest" }, h("h3", { className: "ctitle" }, PHOTO), chip);
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
    actions.after(choice);
  };
  const button = (label: string, onclick: () => void) =>
    h("button", { type: "button", onclick }, label);
  if (i.state === "failed") actions.append(button("Retry", () => void reprocess(false)));
  // Regenerate is rarely wanted: a quiet text button at the row's end, not a full one. Every
  // Claude card says the same: Generate the first time, Regenerate after (enrich.ts, writeup.ts)
  else if (i.state === "done")
    actions.append(h("button", { type: "button", className: "link", onclick: ask }, "Regenerate"));
  else if (i.state === "paused") {
    const resume = async () => {
      try {
        await api("ingest/resume", { method: "POST" });
        o.refresh();
      } catch (err) {
        toast(`Not resumed: ${why(err)}`);
      }
    };
    actions.append(button("Resume", () => void resume()));
  }
  // What Claude made of it, in the brown card all of Claude's work is in (css: .claude)
  panel.append(
    h(
      "div",
      { className: "claude" },
      actions,
      i.description ? block("Description", i.description) : "",
      i.text ? block("Text in the photo", i.text, true) : "",
    ),
  );
  return panel;
}
