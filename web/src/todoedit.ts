// A todo's due date and priority (#104): one row of chips (No date empties it, Today,
// Tomorrow and Next week set it in one tap), a native date picker for any other day, and a menu
// of priorities; on its page also Snooze (No snooze, Tomorrow, Next week, and a date). In place on a
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

/** A day's chips, in one row: one that empties it (No date, No snooze), then those that set
 * it in one tap (Today, Tomorrow, Next week: days on), each as if picked; the one matching
 * the day now set is pressed (the emptying one while there is none). A group named name. */
function soon(date: HTMLInputElement, none: string, days: [string, number][], name: string) {
  const set = (v: string) => {
    date.value = v;
    date.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const chip = (label: string, onclick: () => void) =>
    h("button", { type: "button", className: "facet", onclick }, label);
  const chips = [
    chip(none, () => set("")),
    ...days.map(([label, n]) => chip(label, () => set(inDays(n)))),
  ];
  const mark = () =>
    chips.forEach((c, i) => {
      const on = i ? !!date.value && date.value === inDays(days[i - 1][1]) : !date.value;
      c.setAttribute("aria-pressed", String(on));
    });
  date.addEventListener("input", mark);
  return {
    el: h("div", { className: "soon", role: "group", "aria-label": name }, ...chips),
    mark,
  };
}

/** A day field: a native date picker for any other day (each change an input event: the
 * editor keeps a draft), named name. */
const dayField = (name: string) =>
  h("input", { type: "date", min: "0001-01-01", max: "9999-12-31", "aria-label": name });

/** A small uppercase heading over its controls, as the Filters panel's rows have. */
const heading = (text: string) => h("span", { className: "flabel", "aria-hidden": "true" }, text);

/** A todo's due date and priority; with snooze (a day, or null), its snooze too: that is the
 * page's own form, which says Due over its chips (in the editor its fold says it already). */
export function todoField(
  due: string | null = null,
  priority: string | null = null,
  snooze?: string | null,
) {
  const date = dayField("Due");
  const chips = soon(date, "No date", SOON, "Due soon");
  const rank = h(
    "select",
    { "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  // Snooze: out of Now (and the Todos tab's count) until that day
  const nap = snooze === undefined ? null : dayField("Snooze until");
  const naps = nap && soon(nap, "No snooze", SOON.slice(1), "Snooze for");
  const reset = (d: string | null, p: string | null, z: string | null = null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
    if (nap) nap.value = z ?? "";
    chips.mark();
    naps?.mark();
  };
  reset(due, priority, snooze);
  // Each part under its heading, every row on one left edge: the chips, then the date
  // picker for any other day; then Priority; then (on the page) Snooze
  const el = h(
    "div",
    { className: "todoedit" },
    nap && heading("Due"),
    chips.el,
    date,
    heading("Priority"),
    rank,
    ...(nap && naps ? [heading("Snooze"), naps.el, nap] : []),
  );
  return {
    el,
    date,
    /** As the API takes them: null for none. */
    value: () => ({
      due: date.value || null,
      priority: rank.value || null,
      ...(nap && { snoozed_until: nap.value || null }),
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
        const v = field.value();
        // Snoozed past its due date: asked first whether the due date moves with it
        if (v.due && v.snoozed_until && v.snoozed_until > v.due) return ask(v);
        send(v);
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
  type Value = ReturnType<typeof field.value>;
  const send = (v: Value) => {
    save.disabled = true;
    api<Page>(`pages/${p.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(v),
    }).then(close, (err) => {
      save.disabled = false;
      toast(`Not saved: ${why(err)}`);
    });
  };
  const day = (d: string) =>
    new Date(`${d}T12:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const ask = (v: Value) => {
    form.querySelector(".choice")?.remove();
    const until = v.snoozed_until as string;
    const choice = h(
      "div",
      { className: "choice", role: "group", "aria-label": "Due date" },
      h(
        "p",
        {},
        `Snoozed past its due date (${day(v.due as string)}). Move the due date to ${day(until)} too?`,
      ),
      h(
        "button",
        { type: "button", className: "primary", onclick: () => send({ ...v, due: until }) },
        "Move due date",
      ),
      h("button", { type: "button", onclick: () => send(v) }, "Keep due date"),
    );
    form.querySelector(".row")?.before(choice);
    (choice.querySelector("button") as HTMLButtonElement).focus();
  };
  return { form, focus: () => field.date.focus() };
}
