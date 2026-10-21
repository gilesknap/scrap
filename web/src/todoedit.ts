// A todo's due date and priority (#104): a native date picker (No date empties it, and Today,
// Tomorrow and Next week set it in one tap) and a menu of priorities; on its page also Snooze
// until (a date, No snooze empties it). In place on a
// todo's page (todoForm: Save sends them, no new revision) and in the editor (todoField, sent
// with the page). A chunk of its own: the page's due line and the
// editor load it.
import { api, type Page } from "./api";
import { today } from "./status";
import { why } from "./swipe";
import { h, toast } from "./ui";

export const PRIORITIES = ["high", "medium", "low"];

type Todo = { due: string | null; priority: string | null };

/** What the editor starts from: a draft's due date and priority if it kept them (a null
 * there is one the user cleared, not one missing), else the page's. */
export const todoStart = (kept: { todo?: Todo } | undefined, p: Partial<Page>): Todo =>
  kept?.todo
    ? { due: kept.todo.due, priority: kept.todo.priority }
    : { due: p.due ?? null, priority: p.priority ?? null };

/** The day n days from d on this phone's calendar, as a due date is written. */
export const inDays = (n: number, d = new Date()) =>
  today(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12));

const SOON: [string, number][] = [
  ["Today", 0],
  ["Tomorrow", 1],
  ["Next week", 7],
];

/** Chips that set date in one tap (Today, Tomorrow, Next week: days on), each as if picked;
 * the one matching the date now set is pressed. A group named name. */
function soon(date: HTMLInputElement, days: [string, number][], name: string) {
  const chips = days.map(([label, n]) =>
    h(
      "button",
      {
        type: "button",
        className: "facet",
        onclick: () => {
          date.value = inDays(n);
          date.dispatchEvent(new Event("input", { bubbles: true }));
        },
      },
      label,
    ),
  );
  const mark = () =>
    chips.forEach((c, i) => {
      c.setAttribute("aria-pressed", String(!!date.value && date.value === inDays(days[i][1])));
    });
  date.addEventListener("input", mark);
  return {
    el: h("div", { className: "soon", role: "group", "aria-label": name }, ...chips),
    mark,
  };
}

/** A day field: a native date picker and a ghost button that empties it. Each change is an
 * input event (the editor keeps a draft). */
function dayField(label: string, none: string) {
  const date = h("input", { type: "date", min: "0001-01-01", max: "9999-12-31" });
  const clear = h(
    "button",
    {
      type: "button",
      className: "ghost",
      onclick: () => {
        date.value = "";
        date.dispatchEvent(new Event("input", { bubbles: true }));
      },
    },
    none,
  );
  return { date, els: [h("label", {}, label, date), clear] };
}

/** A todo's due date and priority; with snooze (a day, or null), its snooze too. */
export function todoField(
  due: string | null = null,
  priority: string | null = null,
  snooze?: string | null,
) {
  const day = dayField("Due", "No date");
  const date = day.date;
  const chips = soon(date, SOON, "Due soon");
  const rank = h(
    "select",
    { "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  // Snooze: out of Now (and the Todos tab's count) until that day
  const nap = snooze === undefined ? null : dayField("Snooze until", "No snooze");
  const naps = nap && soon(nap.date, SOON.slice(1), "Snooze for");
  const reset = (d: string | null, p: string | null, z: string | null = null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
    if (nap) nap.date.value = z ?? "";
    chips.mark();
    naps?.mark();
  };
  reset(due, priority, snooze);
  const el = h(
    "div",
    { className: "todoedit" },
    ...day.els,
    chips.el,
    h("label", {}, "Priority", rank),
    ...(nap && naps ? [h("span", { className: "break" }), ...nap.els, naps.el] : []),
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

/** The in-place form on a todo's page; close() gets the page as saved, or nothing when
 * cancelled (the page is then drawn as it is now, not as it was when the form opened). */
export function todoForm(p: Page, close: (p?: Page) => void) {
  const field = todoField(p.due, p.priority, p.snoozed_until ?? null);
  const save = h("button", { type: "submit", className: "primary" }, "Save");
  const form = h(
    "form",
    {
      className: "tagform",
      onkeydown: (e: KeyboardEvent) => {
        if (e.key === "Escape") close();
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
      h("button", { type: "button", className: "ghost", onclick: () => close() }, "Cancel"),
      save,
    ),
  );
  return { form, focus: () => field.date.focus() };
}
