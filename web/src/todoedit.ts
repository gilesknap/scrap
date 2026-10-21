// A todo's due date and priority (#104): a native date picker (Clear empties it) and a menu
// of priorities. In place on a todo's page (todoForm: Save sends both, no new revision) and in
// the editor (todoField, sent with the page). A chunk of its own: the page's due line and the
// editor load it.
import { api, type Page } from "./api";
import { why } from "./swipe";
import { h, toast } from "./ui";

export const PRIORITIES = ["high", "medium", "low"];

export function todoField(due: string | null = null, priority: string | null = null) {
  const date = h("input", { type: "date", min: "0001-01-01", max: "9999-12-31" });
  const rank = h(
    "select",
    { "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  const clear = h(
    "button",
    {
      type: "button",
      className: "ghost",
      onclick: () => {
        date.value = "";
        date.dispatchEvent(new Event("input", { bubbles: true })); // the editor keeps a draft
      },
    },
    "No date",
  );
  const reset = (d: string | null, p: string | null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
  };
  reset(due, priority);
  const el = h(
    "div",
    { className: "todoedit" },
    h("label", {}, "Due", date),
    clear,
    h("label", {}, "Priority", rank),
  );
  return {
    el,
    date,
    /** As the API takes them: null for none. */
    value: () => ({ due: date.value || null, priority: rank.value || null }),
    reset,
  };
}

/** The in-place form on a todo's page; close() gets the page as it is then. */
export function todoForm(p: Page, close: (p: Page) => void) {
  const field = todoField(p.due, p.priority);
  const save = h("button", { type: "submit", className: "primary" }, "Save");
  const form = h(
    "form",
    {
      className: "tagform",
      onkeydown: (e: KeyboardEvent) => {
        if (e.key === "Escape") close(p);
      },
      onsubmit: (e: Event) => {
        e.preventDefault();
        save.disabled = true;
        api<Page>(`pages/${p.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(field.value()),
        }).then(close, (err) => {
          save.disabled = false;
          toast(`Not saved: ${why(err)}`);
        });
      },
    },
    field.el,
    h(
      "div",
      { className: "row" },
      h("button", { type: "button", className: "ghost", onclick: () => close(p) }, "Cancel"),
      save,
    ),
  );
  return { form, focus: () => field.date.focus() };
}
