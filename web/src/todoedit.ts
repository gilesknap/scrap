// A todo's due date and priority (#104): a native date picker (No date empties it) with
// one-tap Today, Tomorrow and Next week (in 7 days) under it, and a menu of priorities. In place on a todo's page (todoForm: Save sends both, no new revision) and in
// the editor (todoField, sent with the page). A chunk of its own: the page's due line and the
// editor load it.
import { api, type Page } from "./api";
import { today } from "./status";
import { why } from "./swipe";
import { h, toast } from "./ui";

export const PRIORITIES = ["high", "medium", "low"];

/** A day from today on this phone's calendar, as a due date is written (YYYY-MM-DD). */
export function inDays(n: number, from = new Date()) {
  const d = new Date(from);
  d.setDate(d.getDate() + n);
  return today(d);
}
const SOON: [string, number][] = [
  ["Today", 0],
  ["Tomorrow", 1],
  ["Next week", 7],
];

/** A day field: a native date picker, one-tap chips (pressed while theirs is the day set)
 * and a ghost button that empties it. Each change is an input event (the editor keeps a
 * draft). */
function dayField(label: string, chips: [string, number][], none: string, quick: string) {
  const date = h("input", { type: "date", min: "0001-01-01", max: "9999-12-31" });
  const set = (v: string) => {
    date.value = v;
    date.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const soon = chips.map(([name, n]) => {
    const b = h(
      "button",
      { type: "button", className: "facet", onclick: () => set(inDays(n)) },
      name,
    );
    b.dataset.n = String(n);
    return b;
  });
  const mark = () => {
    for (const b of soon) b.ariaPressed = String(date.value === inDays(Number(b.dataset.n)));
  };
  date.addEventListener("input", mark);
  date.addEventListener("change", mark);
  const clear = h("button", { type: "button", className: "ghost", onclick: () => set("") }, none);
  const group = h("div", { className: "soon", role: "group", "aria-label": quick }, ...soon);
  return { date, mark, els: [h("label", {}, label, date), clear, group] };
}

/** A todo's due date and priority; with snooze (a day, or null), its snooze too. */
export function todoField(
  due: string | null = null,
  priority: string | null = null,
  snooze?: string | null,
) {
  const day = dayField("Due", SOON, "No date", "Due soon");
  const date = day.date;
  const rank = h(
    "select",
    { "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  // Snooze: out of Now (and the Todos tab's count) until that day
  const nap =
    snooze === undefined
      ? null
      : dayField(
          "Snooze until",
          [
            ["Tomorrow", 1],
            ["Next week", 7],
          ],
          "No snooze",
          "Snooze for",
        );
  const reset = (d: string | null, p: string | null, z: string | null = null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
    day.mark();
    if (nap) {
      nap.date.value = z ?? "";
      nap.mark();
    }
  };
  reset(due, priority, snooze);
  const el = h(
    "div",
    { className: "todoedit" },
    ...day.els,
    h("label", {}, "Priority", rank),
    ...(nap?.els ?? []),
  );
  return {
    el,
    date,
    /** As the API takes them: null for none. */
    value: () => ({
      due: date.value || null,
      priority: rank.value || null,
      ...(nap && { snoozed_until: nap.date.value || null }),
    }),
    reset,
  };
}

/** The in-place form on a todo's page; close() gets the page as it is then. */
export function todoForm(p: Page, close: (p: Page) => void) {
  const field = todoField(p.due, p.priority, p.snoozed_until ?? null);
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
