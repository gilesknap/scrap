// The Link key's page picker (#511): a sheet over the editor with a search box, the pages
// changed most recently while it is empty, and the pages matching it as you type (the search
// API's). A chunk of its own, loaded by the key's first press (linkkey.ts), so neither the
// shell nor the editor carry it until then.
//
// A modal <dialog>: focus goes to its box, the rest of the screen is inert, and Back (the
// phone's close request), Escape, a tap outside it or its ✕ close it with nothing picked. Its
// box's typing goes in the page's undo history, as any field's does, but the box is removed
// on close, which takes its steps out of the history with it; so Undo in the editor (whose
// floor ignores this box, editor.ts) never reaches it.
import { api, type Hit, type Summary } from "./api";
import { icon, kindIcon } from "./icons";
import { h } from "./ui";
import "./css/linkpick.css";

const SHOWN = 8; // rows in the list: recent or matching

type Row = Pick<Summary, "slug" | "title" | "kind">;

/** Pick a page: resolves its slug, or null when closed without one. */
export function pick(): Promise<string | null> {
  // A text box in the search role, not type=search: Escape in a search box with text only
  // clears it, and the picker should close at the first
  const box = h("input", {
    type: "text",
    role: "searchbox",
    placeholder: "Find a page",
    "aria-label": "Find a page",
    autocomplete: "off",
    enterKeyHint: "go",
  });
  const close = h(
    "button",
    { type: "button", className: "ghost close", "aria-label": "Close" },
    icon("close"),
  );
  const label = h("h2", { className: "label" }, "Recent");
  const list = h("ul", { className: "rows", role: "list" });
  const note = h("p", { className: "note", role: "status" });
  const d = h(
    "dialog",
    { className: "linkpick", "aria-label": "Link to a page" },
    h(
      "div",
      { className: "find" },
      h("label", { className: "field-search" }, icon("search"), box),
      close,
    ),
    label,
    list,
    note,
  );
  // The page being edited is no link of its own
  const here = /^\/p\/([^/]+)/.exec(location.pathname)?.[1];
  let rows: Row[] = [];
  let shown: string | null = null; // the query the rows are for
  const draw = (got: Row[], q: string, empty: string) => {
    shown = q;
    const heading = q ? "Matching" : "Recent";
    rows = got.filter((p) => p.slug !== here).slice(0, SHOWN);
    label.textContent = heading;
    note.textContent = rows.length ? "" : empty;
    list.replaceChildren(
      ...rows.map((p) =>
        h(
          "li",
          {},
          h(
            "button",
            { type: "button", onclick: () => d.close(p.slug) },
            icon(kindIcon(p.kind)),
            h("span", { dir: "auto" }, p.title || p.slug),
          ),
        ),
      ),
    );
  };

  // The latest request wins: an older one still on its way is stopped, its answer dropped
  let ask: AbortController | null = null;
  let timer = 0;
  const find = async () => {
    ask?.abort();
    const q = box.value.trim();
    if (!navigator.onLine) return draw([], q, "Offline: pages can't be found now.");
    const mine = new AbortController();
    ask = mine;
    try {
      const got = q
        ? await api<Hit[]>(`search?q=${encodeURIComponent(q)}&limit=${SHOWN + 1}`, {
            signal: mine.signal,
          })
        : await api<Summary[]>(`pages?limit=${SHOWN + 1}`, { signal: mine.signal });
      if (ask === mine) draw(got, q, q ? "No page matches." : "No pages yet.");
    } catch {
      if (ask === mine) draw([], q, "Pages couldn't be found now.");
    }
  };
  box.addEventListener("input", () => {
    clearTimeout(timer);
    timer = window.setTimeout(() => void find(), 150);
  });
  // Enter picks the first page for what is typed (nothing typed: nothing picked); typed faster
  // than the search answers (the rows still the last query's), it searches now and picks from that
  box.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || e.isComposing) return;
    e.preventDefault();
    if (!box.value.trim()) return;
    if (shown !== box.value.trim()) {
      clearTimeout(timer);
      await find();
    }
    if (d.open && shown === box.value.trim() && rows[0]) d.close(rows[0].slug);
  });
  close.onclick = () => d.close();
  // A tap outside the sheet: its backdrop, which is the dialog itself
  d.addEventListener("click", (e) => e.target === d && d.close());
  // Its keys are its own: not the editor's (Ctrl+Enter there saves)
  d.addEventListener("keydown", (e) => e.stopPropagation());

  document.body.append(d);
  return new Promise((done) => {
    d.addEventListener(
      "close",
      () => {
        clearTimeout(timer);
        ask?.abort();
        d.remove(); // and with it, its box's steps in the undo history
        done(d.returnValue || null);
      },
      { once: true },
    );
    d.showModal();
    box.focus();
    void find();
  });
}
