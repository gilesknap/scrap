// Recent searches: the last ten run on this device, under the empty search box while it has
// focus. Tap one to run it again, ✕ to forget it, Clear all to forget them all. Kept in this
// device's storage only (scrap.searches), never sent to the server; with no storage there are
// none, and search works as before. A chunk of its own, loaded with the search screen.
import { kept } from "./api";
import { icon } from "./icons";
import { h } from "./ui";

const KEY = "scrap.searches";
const MOST = 10;

/** The searches kept, newest first (none if storage is missing or holds something else). */
export function load(): string[] {
  try {
    const got = JSON.parse(kept(KEY) ?? "[]");
    return Array.isArray(got) ? got.filter((q) => typeof q === "string").slice(0, MOST) : [];
  } catch {
    return [];
  }
}

const save = (list: string[]) => kept(KEY, list.length ? JSON.stringify(list) : null);

/** list with q at its start, once (its spaces tidied, its case kept), at most ten. */
export function added(list: string[], q: string): string[] {
  const tidy = q.trim().replace(/\s+/g, " ");
  if (!tidy) return list;
  return [tidy, ...list.filter((x) => x !== tidy)].slice(0, MOST);
}

/** Remember a search that was run. */
export const remember = (q: string) => save(added(load(), q));

/** Forget one, or (with no query) all. */
export const forget = (q?: string) => save(q === undefined ? [] : load().filter((x) => x !== q));

/** Show the recent searches in slot while the box is empty and focused; run(q) runs one. */
export function attach(input: HTMLInputElement, slot: HTMLElement, run: (q: string) => void) {
  const show = () => {
    const list = load();
    if (input.value || document.activeElement !== input || !list.length) {
      slot.replaceChildren();
      return;
    }
    const pick = (q: string) => {
      input.value = q;
      slot.replaceChildren();
      input.blur(); // the keyboard goes: the results are what is wanted now
      run(q);
    };
    slot.replaceChildren(
      h(
        "div",
        { className: "recents-top" },
        h("h2", { className: "label" }, "Recent"),
        h(
          "button",
          {
            type: "button",
            className: "link",
            onclick: () => {
              forget();
              input.focus();
              show();
            },
          },
          "Clear all",
        ),
      ),
      h(
        "ul",
        { className: "list recents", role: "group", "aria-label": "Recent searches" },
        ...list.map((q) =>
          h(
            "li",
            {},
            h(
              "button",
              { type: "button", className: "again", dir: "auto", onclick: () => pick(q) },
              icon("search"),
              h("span", {}, q),
            ),
            h(
              "button",
              {
                type: "button",
                className: "ghost forget",
                "aria-label": `Remove ${q}`,
                onclick: () => {
                  forget(q);
                  input.focus();
                  show();
                },
              },
              icon("close"),
            ),
          ),
        ),
      ),
    );
  };
  // A tap on the list keeps the box focused until the choice is made: no flicker of the keyboard
  slot.addEventListener("pointerdown", (e) => e.preventDefault());
  for (const ev of ["focus", "input", "blur"]) input.addEventListener(ev, show);
  show();
  return { remember };
}
