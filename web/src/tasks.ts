// A page's task list boxes (- [ ] and - [x]), ticked in place: a tap flips that item's marker
// in the page's text and saves it at once, as an edit on the revision shown (a page changed
// elsewhere meanwhile is shown again as it is now, never overwritten). Each box knows its
// item's line in the text (render.ts: data-line, from markdown-it's line map), so the same
// words twice, or a box in code, can't be mistaken. Page edits need the server, so the
// boxes are off while offline. A chunk of its own, loaded for a page that has boxes.
import { ApiError, api, type Page } from "./api";
import { why } from "./swipe";
import { toast } from "./ui";

// A list item's start: quote markers, then a bullet or number, then its task marker
const ITEM = /^((?:[ \t]*>)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[([ xX])\]/;

/** text with the task on line (0-based) ticked (or not), or null if that line holds no task
 * marker in the other state (the text changed since it was drawn). */
export function flip(text: string, line: number, ticked: boolean): string | null {
  const lines = text.split("\n");
  const m = ITEM.exec(lines[line] ?? "");
  if (!m || (m[2] !== " ") !== !ticked) return null;
  lines[line] = `${m[1]}[${ticked ? "x" : " "}]${lines[line].slice(m[0].length)}`;
  return lines.join("\n");
}

let wired = new AbortController(); // the body drawn last: one drawn before is gone

/** Make the boxes in a page's body tickable while online: shown() is the page as shown,
 * show() draws it again (after a save, or as it is now after a conflict). */
export function wire(
  body: HTMLElement,
  shown: () => Page,
  show: (p: Page) => void,
  view: AbortSignal,
) {
  wired.abort();
  wired = new AbortController();
  const signal = AbortSignal.any([view, wired.signal]);
  const boxes = () => body.querySelectorAll<HTMLInputElement>("input[data-line]");
  const online = () => {
    for (const b of boxes()) {
      b.disabled = !navigator.onLine;
      b.title = navigator.onLine ? "" : "Offline: ticking needs the server";
    }
  };
  online();
  addEventListener("online", online, { signal });
  addEventListener("offline", online, { signal });
  body.addEventListener(
    "change",
    async (e) => {
      const box = e.target as HTMLInputElement;
      if (!box.dataset.line) return;
      const p = shown();
      const back = () => {
        box.checked = !box.checked; // as it was: nothing saved
        box.disabled = false;
      };
      const text = flip(p.body, Number(box.dataset.line), box.checked);
      if (text === null) {
        back();
        return toast("That item has moved: open the editor to change it");
      }
      for (const b of boxes()) b.disabled = true; // one save at a time
      try {
        show(
          await api<Page>(`pages/${p.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ base_rev: p.rev, body: text }),
          }),
        );
      } catch (err) {
        back();
        online();
        if (!(err instanceof ApiError && err.status === 409))
          return toast(`Not saved: ${why(err)}`);
        const now = await api<Page>(`pages/${p.id}`).catch(() => null);
        if (now) show(now);
        toast("Changed elsewhere: this is the page as it is now. Tap again to tick it.");
      }
    },
    { signal },
  );
}
