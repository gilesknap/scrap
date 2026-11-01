// "Claude's reading" (#521): one closed fold under each photo, image or file, holding what was
// read from it (its description and text, a file's pages and text), with Regenerate. Where the
// reading is up to (waiting, failed) and Retry or Resume stay outside it, on a line of their
// own, so a failure is never hidden in a closed fold. Part of the figure chunk.
//
// DESIGN MOCK (design/521-reading-fold): both variants of the two open design points are in
// the markup, and the sim picks one with attributes on <html> (sim.js, its Variants tab):
//   data-m521-chev="before" | "after"  the chevron before the words (as scrap's other folds)
//                                      or after them ("Claude's reading ›", the first mock)
//   data-m521-regen="in" | "out"       Regenerate inside the open fold, or on the fold's line
// The build that ships keeps one of each and drops the attributes.
import "./css/reading.css";
import { icon } from "./icons";
import { h } from "./ui";

/** The fold's label, in the app and on public pages. */
export const READING = "Claude's reading";

/** The fold: body inside Claude's card; regen (Regenerate, or Generate the first time) at the
 * card's end, or on the fold's line (variant out); onOpen runs each time it opens. */
export function readingFold(o: {
  body: (Node | string | false | null | undefined)[];
  regen?: { label: string; onclick: () => void } | null;
  onOpen?: () => void;
}): HTMLElement {
  const btn = (where: string) =>
    o.regen
      ? h(
          "button",
          {
            type: "button",
            // Regenerate is rarely wanted: a quiet text button; Generate, the first time, a full one
            className: `${o.regen.label === "Regenerate" ? "link " : ""}regen-${where}`,
            onclick: o.regen.onclick,
          },
          o.regen.label,
        )
      : "";
  // Variant out: on the fold's line there is no room for the word at 308 px and 130 % text
  // beside "Claude's reading" (it needs about 290 px of 276), so it is the redo icon, named
  const out = o.regen
    ? h(
        "button",
        {
          type: "button",
          className: "regen-out",
          title: o.regen.label,
          "aria-label": o.regen.label,
          onclick: o.regen.onclick,
        },
        icon("retry"),
      )
    : "";
  const fold = h(
    "details",
    { className: "reading-fold" },
    h("summary", {}, h("span", {}, READING)),
    h(
      "div",
      { className: "claude" },
      ...o.body.filter((x): x is Node | string => !!x),
      o.regen ? h("div", { className: "regen-row" }, btn("in")) : "",
    ),
  );
  if (o.onOpen) fold.addEventListener("toggle", () => fold.open && o.onOpen?.());
  return h("div", { className: "reading" }, fold, out);
}

/** Where the reading is up to, outside the fold: a pill, and its action (Retry, Resume). */
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
