// "Claude's reading" (#521): one closed fold under each photo, image or file, holding what was
// read from it (its description and text, a PDF's text), with Regenerate (Generate the first
// time) at the card's end. Where the reading is up to (waiting, failed, paused) and Retry or
// Resume stay outside it, on a line of their own, so a failure is never hidden in a closed
// fold. The fold always starts closed and is not remembered. In an image's (#538), the text
// read from it is a fold of its own, closed, and the owner's Guidance for Claude is at the
// bottom (guidance.ts), for the next Regenerate. Part of the figure chunk.
import "./css/reading.css";
import { api } from "./api";
import { guidanceFold } from "./guidance";
import { h } from "./ui";

/** The fold's label, in the app and on public pages (publish.ts writes the same). */
export const READING = "Claude's reading";

/** The label of the text read from an image, a fold inside the reading (publish.ts too). */
export const READ_TEXT = "Text read from the image";

/** The text read from an image, in a closed fold of its own inside the reading (#538). */
export const readText = (text: string): HTMLElement =>
  h(
    "details",
    { className: "claude-text readtext" },
    h("summary", {}, READ_TEXT),
    h("pre", {}, text),
  );

/** The owner's guidance for an image's next reading (#538): the write-up's fold (guidance.ts),
 * for the image of capture cid; read says whether Claude has read it (Regenerate) or not yet
 * (Generate). Saving it stores it and shows the page again; it queues nothing. */
export function photoGuidance(o: {
  cid: string;
  sha: string;
  saved: string | null | undefined;
  read: boolean;
  refresh: () => void;
}): HTMLDetailsElement {
  return guidanceFold({
    key: `${o.cid}/${o.sha}`,
    saved: o.saved,
    placeholder: "e.g. it's a wiring diagram; 'R1' is a resistor",
    line: o.read
      ? "Used by the next Regenerate, and kept with it."
      : "Used by Generate, and kept with it.",
    done: o.read ? "Saved: the next Regenerate follows it" : "Saved: Generate follows it",
    put: (text) =>
      api<{ guidance: string | null }>(`captures/${o.cid}/photos/${o.sha}/guidance`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guidance: text }),
      }),
    shown: () => o.refresh(),
  });
}

/** The fold: body inside Claude's card, then guidance (an image's, #538), then regen (Regenerate, or Generate the first time) at
 * the card's end, its button off while what it does (a promise) runs; onOpen runs each time
 * it opens. */
export function readingFold(o: {
  body: (Node | string | false | null | undefined)[];
  guidance?: HTMLDetailsElement | null;
  regen?: { label: string; onclick: () => void | Promise<void> } | null;
  onOpen?: () => void;
}): HTMLElement {
  const act = o.regen?.onclick;
  const button =
    o.regen &&
    h(
      "button",
      {
        type: "button",
        // Regenerate is rarely wanted: a quiet text button; Generate, the first time, a full one
        className: o.regen.label === "Regenerate" ? "link" : "",
      },
      o.regen.label,
    );
  if (button && act)
    button.onclick = async () => {
      button.disabled = true;
      try {
        await act();
      } finally {
        button.disabled = false;
      }
    };
  const regen = button && h("div", { className: "regen-row" }, button);
  const fold = h(
    "details",
    // open while its guidance is being typed: kept across a redraw, as the write-up's is (#538)
    { className: "reading-fold", open: !!o.guidance?.open },
    h("summary", {}, h("span", {}, READING)),
    h(
      "div",
      { className: "claude" },
      ...o.body.filter((x): x is Node | string => !!x),
      o.guidance || "",
      regen || "",
    ),
  );
  if (o.onOpen) fold.addEventListener("toggle", () => fold.open && o.onOpen?.());
  return h("div", { className: "reading" }, fold);
}

/** Where the reading is up to, outside the fold: its words (no pill), and its action (Retry,
 * Resume) beside them. */
export function readingState(
  words: string,
  state: string,
  action?: { label: string; onclick: () => void } | null,
): HTMLElement {
  return h(
    "div",
    { className: "reading-state" },
    h("span", { className: `state ${state}`, role: "status" }, words),
    action ? h("button", { type: "button", onclick: action.onclick }, action.label) : "",
  );
}
