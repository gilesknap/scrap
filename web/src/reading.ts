// "Claude's reading" (#521): one closed fold under each photo, image or file, holding what was
// read from it (its description and text, a PDF's text), with Regenerate (Generate the first
// time) at the card's end. Where the reading is up to (waiting, failed, paused) and Retry or
// Resume stay outside it, on a line of their own, so a failure is never hidden in a closed
// fold. The fold always starts closed and is not remembered. Part of the figure chunk.
import "./css/reading.css";
import { h } from "./ui";

/** The fold's label, in the app and on public pages (publish.ts writes the same). */
export const READING = "Claude's reading";

/** The fold: body inside Claude's card, then regen (Regenerate, or Generate the first time) at
 * the card's end; onOpen runs each time it opens. */
export function readingFold(o: {
  body: (Node | string | false | null | undefined)[];
  regen?: { label: string; onclick: () => void } | null;
  onOpen?: () => void;
}): HTMLElement {
  const regen =
    o.regen &&
    h(
      "div",
      { className: "regen-row" },
      h(
        "button",
        {
          type: "button",
          // Regenerate is rarely wanted: a quiet text button; Generate, the first time, a full one
          className: o.regen.label === "Regenerate" ? "link" : "",
          onclick: o.regen.onclick,
        },
        o.regen.label,
      ),
    );
  const fold = h(
    "details",
    { className: "reading-fold" },
    h("summary", {}, h("span", {}, READING)),
    h(
      "div",
      { className: "claude" },
      ...o.body.filter((x): x is Node | string => !!x),
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
