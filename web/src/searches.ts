// Recent searches: the last ten run on this device, under the empty search box while it has
// focus. Tap one to run it again, ✕ to forget it, Clear all to forget them all. Kept in this
// device's storage only (scrap.searches), never sent to the server; with no storage there are
// none, and search works as before. A chunk of its own, loaded with the search screen.
// Above them, Pinned (pins.ts): the Pinned page's links, a launcher of searches and pages kept
// on the server; a Recent row's pin adds its search there.
import { kept } from "./api";
import { icon } from "./icons";
import {
  CHANGED,
  isPinned,
  keyOf,
  nameOf,
  PINS_PAGE,
  type Pin,
  pin,
  pins,
  searchHref,
  unpin,
} from "./pins";
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
export function attach(
  input: HTMLInputElement,
  slot: HTMLElement,
  run: (q: string) => void,
  signal?: AbortSignal, // the screen's: no pins listener once left
) {
  let pinned: Pin[] = [];
  const fetchPins = () =>
    void pins().then((got) => {
      pinned = got;
      show();
    });
  const show = () => {
    const list = load();
    if (input.value || document.activeElement !== input || !(list.length || pinned.length)) {
      slot.replaceChildren();
      return;
    }
    const keys = new Set(pinned.map((p) => p.key));
    const pick = (q: string) => {
      input.value = q;
      slot.replaceChildren();
      input.blur(); // the keyboard goes: the results are what is wanted now
      run(q);
    };
    // Pinned: each a link (a search, or a page), in the page's order; Edit pins opens the page
    const launcher = pinned.length
      ? [
          h(
            "div",
            { className: "recents-top" },
            h("h2", { className: "label" }, "Pinned"),
            h("a", { className: "link", href: PINS_PAGE }, "Edit pins"),
          ),
          h(
            "ul",
            { className: "list recents pins", role: "group", "aria-label": "Pinned" },
            ...pinned.map((p) =>
              h(
                "li",
                {},
                h(
                  "a",
                  { className: "again", href: p.href, dir: "auto" },
                  icon(p.key.startsWith("p:") ? "note" : "search"),
                  h("span", {}, p.name),
                ),
              ),
            ),
          ),
        ]
      : [];
    const pinButton = (q: string) => {
      const key = keyOf(searchHref(q));
      const on = keys.has(key);
      return h(
        "button",
        {
          type: "button",
          className: on ? "ghost forget pin on" : "ghost forget pin",
          "aria-label": on ? `Unpin ${q}` : `Pin ${q}`,
          onclick: async () => {
            if (await isPinned(key)) await unpin(key);
            else await pin(nameOf(q), searchHref(q));
            input.focus();
          },
        },
        icon("pin"),
      );
    };
    if (!list.length) return slot.replaceChildren(...launcher);
    slot.replaceChildren(
      ...launcher,
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
            pinButton(q),
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
  document.addEventListener(CHANGED, fetchPins, { signal });
  fetchPins();
  show();
  return { remember };
}
