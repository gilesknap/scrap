// Edit a page's tags: its tags as chips (tap one to take it off) and a box to add one. Enter
// or a comma adds what is typed; what is still in the box when saving counts too. The server
// cleans tags as the importer does (lower case, no leading #), so this does the same for what
// it shows. Under the box, one row of chips, one tap each: with nothing typed, the most used
// tags not on it yet (counted by the pages given that very tag: not a/b's parent a, which
// /api/tags adds and counts over a's children); as you type, the tags in use that match. Our
// own row, not a native datalist: on a phone that pops a menu over the keyboard. A chunk of its
// own: the page's Tags button and the editor load it.
import { api } from "./api";
import { icon } from "./icons";
import { h } from "./ui";

/** A tag as the server keeps it: lower case, one space between words, no leading #. */
export const clean = (t: string) =>
  t.split(/\s+/).join(" ").trim().replace(/^#+/, "").trim().toLowerCase();

// The server's limits on a page's tags: MAX_TAGS and MAX_TAG in src/scrap/store.py.
export const MAX_TAGS = 64;
export const MAX_TAG = 64; // characters (code points, after NFC)

/** Why the server would refuse these (cleaned) tags, or undefined if it would take them. */
export function tagProblem(tags: string[]): string | undefined {
  if (tags.length > MAX_TAGS) return `At most ${MAX_TAGS} tags, not ${tags.length}.`;
  const long = tags.find((t) => [...t.normalize("NFC")].length > MAX_TAG);
  if (long) return `A tag can be at most ${MAX_TAG} characters: "${long.slice(0, 40)}…"`;
}

const TOP = 6; // tags offered at a time
const DOUBLE = 400; // ms: a second tap on the chips sooner than this is a double tap, ignored

export function tagField(initial: string[], onchange: () => void = () => {}) {
  let tags = [...initial];
  let used: string[] = []; // the tags pages were given, most used first
  let every: string[] = []; // every tag in use (parents too), most pages first
  let tapped = -Infinity; // when a chip under the box was last tapped
  const top = h("div", {
    className: "toptags",
    role: "group",
    "aria-label": "Most used tags",
    hidden: true, // until they come (never offline)
  });
  /** With nothing typed, the most used; else those in use that match what is typed: starting
   * with it first (a part after a / counts: "bed" finds garden/beds), then holding it. */
  const offered = () => {
    const q = clean(input.value);
    if (!q) return used.filter((t) => !tags.includes(t)).slice(0, TOP);
    const free = every.filter((t) => !tags.includes(t) && t !== q);
    const starts = free.filter((t) => t.startsWith(q) || t.split("/").some((p) => p.startsWith(q)));
    const holds = free.filter((t) => !starts.includes(t) && t.includes(q));
    return [...starts, ...holds].slice(0, TOP);
  };
  const drawTop = (focus = -1) => {
    const typing = !!clean(input.value);
    top.setAttribute("aria-label", typing ? "Matching tags" : "Most used tags");
    top.replaceChildren(
      ...offered().map((t) =>
        h(
          "button",
          {
            type: "button",
            className: "facet",
            "aria-label": `Add #${t}`,
            onclick: (e: Event) => {
              // A double tap: the second lands on the chip that slid into the first's place
              if (e.timeStamp - tapped < DOUBLE) return;
              tapped = e.timeStamp;
              if (!tags.includes(t)) tags.push(t);
              if (typing) input.value = ""; // what was typed is now that tag
              const at = [...top.children].indexOf(e.currentTarget as Element);
              draw(top.contains(document.activeElement) ? at : -1);
              onchange();
            },
          },
          h("span", { dir: "auto" }, `#${t}`),
        ),
      ),
    );
    top.hidden = !top.childElementCount;
    // The tapped chip is gone: focus the one now in its place (else the last), or the box
    if (focus >= 0)
      (((top.children[focus] ?? top.lastElementChild) as HTMLElement | null) ?? input).focus();
  };
  // [tag, pages under it, pages with that very tag]
  api<[string, number, number][]>("tags")
    .then((all) => {
      every = [...all].sort((a, b) => b[1] - a[1]).map(([t]) => t);
      used = all
        .filter((r) => r[2] > 0)
        .sort((a, b) => b[2] - a[2])
        .map(([t]) => t);
      drawTop();
    })
    .catch(() => {}); // offline: no suggestions, typing still works
  const input = h("input", {
    type: "text",
    placeholder: "Add a tag",
    "aria-label": "Add a tag",
    autocapitalize: "none",
    autocomplete: "off",
    enterKeyHint: "done",
    dir: "auto",
  });
  const chips = h("span", { className: "tagchips" });
  const draw = (focus = -1) => {
    drawTop(focus);
    chips.replaceChildren(
      ...tags.map((t) =>
        h(
          "button",
          {
            type: "button",
            className: "facet on",
            "aria-label": `Remove #${t}`,
            onclick: (e: Event) => {
              // The button is replaced: if it had focus, the next chip (else the last) or the box
              const at = tags.indexOf(t);
              const had =
                chips.contains(document.activeElement) &&
                e.currentTarget === document.activeElement;
              tags = tags.filter((x) => x !== t);
              draw();
              if (had)
                ((chips.children[at] ?? chips.lastElementChild ?? input) as HTMLElement).focus();
              onchange();
            },
          },
          h("span", { dir: "auto" }, `#${t}`),
          icon("close"),
        ),
      ),
    );
  };
  /** What is typed, as tags (a comma separates them), added; the box emptied. */
  const add = () => {
    const typed = input.value.split(",").map(clean).filter(Boolean);
    input.value = "";
    const fresh = typed.filter((t, i) => !tags.includes(t) && typed.indexOf(t) === i);
    if (!fresh.length) return drawTop();
    tags.push(...fresh);
    draw();
    onchange();
  };
  input.onkeydown = (e) => {
    if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return; // an IME's Enter
    e.preventDefault(); // not the form's submit: adding a tag saves nothing yet
    add();
  };
  // A comma typed (Android keyboards send no key for it) adds it; else the row offers matches
  input.oninput = () => {
    if (input.value.includes(",")) add();
    else drawTop();
  };
  draw();
  const el = h("div", { className: "tagedit" }, chips, input, top);
  return {
    el,
    input,
    /** The tags, with what is still typed in the box. */
    value: () => {
      const typed = input.value.split(",").map(clean).filter(Boolean);
      return [...new Set([...tags, ...typed])];
    },
    reset: (to: string[]) => {
      tags = [...to];
      input.value = "";
      draw();
    },
  };
}

/** Whether two lists hold the same tags, in any order. */
export const same = (a: string[], b: string[]) =>
  a.length === b.length && a.every((t) => b.includes(t));

/** A draft's tags on the page's now: theirs (the server's), plus what the draft added to
 * `from` (the tags it started from), less what it took off. */
export const mergeTags = (server: string[], from: string[], ours: string[]) => [
  ...server.filter((t) => !from.includes(t) || ours.includes(t)),
  ...ours.filter((t) => !from.includes(t) && !server.includes(t)),
];
