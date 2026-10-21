// The last searches, on this phone only (localStorage: never sent anywhere), shown under the
// empty search box when it is tapped: tap one to run it again, ✕ to forget it, or Clear all.
// A search is remembered when it is run (Enter, a result opened, or the same query left for
// a moment with results), not at each key. Storage may be off (a private tab, a full disk):
// every read and write is guarded, and search works the same without it. A chunk of its own.
import { kept } from "./api";
import { icon } from "./icons";
import { h } from "./ui";

const KEY = "scrap.searches";
export const MOST = 10;

/** The list with q first, once (case and spaces as typed; the same words twice: once). */
export function added(list: string[], q: string): string[] {
  const t = q.trim().replace(/\s+/g, " ");
  if (!t) return list;
  return [t, ...list.filter((x) => x !== t)].slice(0, MOST);
}

export function load(): string[] {
  try {
    const got = JSON.parse(kept(KEY) ?? "[]");
    return Array.isArray(got) ? got.filter((x) => typeof x === "string").slice(0, MOST) : [];
  } catch {
    return []; // not JSON: as if none
  }
}

const store = (list: string[]) => kept(KEY, list.length ? JSON.stringify(list) : null);

export const remember = (q: string) => store(added(load(), q));
export const forget = (q: string) => store(load().filter((x) => x !== q));

/** Show the last searches in slot while input is focused and empty; pick(q) runs one. */
export function attach(input: HTMLInputElement, slot: HTMLElement, pick: (q: string) => void) {
  const draw = () => {
    const list = input.value || document.activeElement !== input ? [] : load();
    slot.replaceChildren();
    if (!list.length) return;
    const clear = h(
      "button",
      {
        type: "button",
        className: "link",
        onclick: () => {
          store([]);
          draw();
        },
      },
      "Clear all",
    );
    slot.append(
      h(
        "div",
        {
          className: "recents",
          role: "group",
          "aria-label": "Recent searches",
          // A tap here keeps the box focused (and the keyboard up) until it has chosen
          onpointerdown: (e: Event) => e.preventDefault(),
        },
        h("div", { className: "recents-top" }, h("h2", { className: "label" }, "Recent"), clear),
        h(
          "ul",
          { className: "list" },
          ...list.map((q) =>
            h(
              "li",
              {},
              h(
                "button",
                {
                  type: "button",
                  className: "again",
                  onclick: () => {
                    slot.replaceChildren();
                    input.blur();
                    pick(q);
                  },
                },
                icon("search"),
                h("span", { dir: "auto" }, q),
              ),
              h(
                "button",
                {
                  type: "button",
                  className: "ghost forget",
                  "aria-label": `Remove ${q}`,
                  onclick: () => {
                    forget(q);
                    draw();
                  },
                },
                icon("close"),
              ),
            ),
          ),
        ),
      ),
    );
  };
  input.addEventListener("focus", draw);
  input.addEventListener("input", draw);
  input.addEventListener("blur", draw);
  draw();
}
