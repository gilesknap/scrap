// Edit a page's tags: its tags as chips (tap one to take it off) and a box to add one, which
// suggests the tags already in use (a native datalist, from /api/tags). Enter, a comma or a
// suggestion picked adds what is typed; what is still in the box when saving counts too. The
// server cleans tags as the importer does (lower case, no leading #), so this does the same
// for what it shows. A chunk of its own: the page's Tags button and the editor load it.
import { api } from "./api";
import { icon } from "./icons";
import { h } from "./ui";

/** A tag as the server keeps it: lower case, one space between words, no leading #. */
export const clean = (t: string) =>
  t.split(/\s+/).join(" ").trim().replace(/^#+/, "").trim().toLowerCase();

let n = 0; // a datalist id per field

export function tagField(initial: string[], onchange: () => void = () => {}) {
  let tags = [...initial];
  const list = h("datalist", { id: `tags-${++n}` });
  api<[string, number][]>("tags")
    .then((all) => list.replaceChildren(...all.map(([t]) => h("option", { value: t }))))
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
  input.setAttribute("list", list.id);
  const chips = h("span", { className: "tagchips" });
  const draw = () =>
    chips.replaceChildren(
      ...tags.map((t) =>
        h(
          "button",
          {
            type: "button",
            className: "facet on",
            "aria-label": `Remove #${t}`,
            onclick: () => {
              tags = tags.filter((x) => x !== t);
              draw();
              onchange();
            },
          },
          h("span", { dir: "auto" }, `#${t}`),
          icon("close"),
        ),
      ),
    );
  /** What is typed, as tags (a comma separates them), added; the box emptied. */
  const add = () => {
    const typed = input.value.split(",").map(clean).filter(Boolean);
    input.value = "";
    const fresh = typed.filter((t, i) => !tags.includes(t) && typed.indexOf(t) === i);
    if (!fresh.length) return;
    tags.push(...fresh);
    draw();
    onchange();
  };
  input.onkeydown = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault(); // not the form's submit: adding a tag saves nothing yet
    add();
  };
  // A comma typed (Android keyboards send no key for it), or a suggestion picked
  input.oninput = (e) => {
    const how = (e as InputEvent).inputType; // none, or a replacement: a suggestion picked
    const picked = !how || how === "insertReplacementText";
    if (
      input.value.includes(",") ||
      (picked && [...list.options].some((o) => o.value === input.value))
    )
      add();
  };
  draw();
  const el = h("div", { className: "tagedit" }, chips, input, list);
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
