// A todo's due date and priority (#104): one row of chips (Today, Tomorrow and Next week set it
// in one tap, Pick a date… opens the native date picker for any other day, No date empties it)
// and a menu of priorities. The composer's and the page editor's Due fold (todoField, sent with
// the page: not a text revision). A chunk of its own: the editor loads it.
import type { Page } from "./api";
import { short as dayName, today } from "./status";
import { h } from "./ui";

export const PRIORITIES = ["high", "medium", "low"];

type Todo = { due: string | null; priority: string | null };

/** What the editor starts from: a draft's due date and priority if it kept them (a null there
 * is one the user cleared, not one missing), else the page's. */
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
const PICK = "Pick a date…";

/** A day's chips, in one wrapping row: those that set it in one tap (Today, Tomorrow, Next
 * week: days on), then Pick a date… (the native picker for any other day: the date field is
 * hidden under it, still named, and shown in its place where the picker can't be opened), then
 * one that empties it (No date). Each as if picked (an input event: the editor
 * keeps a draft). The one matching the day set is pressed: Pick a date… saying it ("31 Oct")
 * for any other day, the emptying one while there is none. A group named name. */
function soon(date: HTMLInputElement, days: [string, number][], none: string, name: string) {
  const set = (v: string) => {
    date.className = "vh"; // hidden again once a chip chooses (after a picker that couldn't open)
    date.value = v;
    date.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const chip = (label: string, onclick: () => void) =>
    h("button", { type: "button", className: "facet", onclick }, label);
  const fixed = days.map(([label, n]) => chip(label, () => set(inDays(n))));
  const pick = chip(PICK, () => {
    try {
      date.showPicker();
    } catch {
      date.className = ""; // no picker to open here: the field itself, in view
      date.focus();
    }
  });
  date.className = "vh";
  date.tabIndex = -1; // reached by its chip
  const empty = chip(none, () => set(""));
  const mark = () => {
    const v = date.value;
    const at = days.findIndex(([, n]) => v === inDays(n));
    for (const [i, c] of fixed.entries()) c.setAttribute("aria-pressed", String(!!v && i === at));
    const other = !!v && at < 0;
    pick.setAttribute("aria-pressed", String(other));
    pick.textContent = other ? dayName(v) : PICK;
    if (other) pick.setAttribute("aria-label", `${PICK} ${dayName(v)}`);
    else pick.removeAttribute("aria-label");
    empty.setAttribute("aria-pressed", String(!v));
  };
  for (const type of ["input", "change"]) date.addEventListener(type, mark);
  return {
    el: h(
      "div",
      { className: "soon", role: "group", "aria-label": name },
      ...fixed,
      h("span", { className: "pick" }, pick, date),
      empty,
    ),
    mark,
  };
}

/** A day field: the native date picker for any other day, named name. */
const dayField = (name: string) =>
  h("input", { type: "date", min: "0001-01-01", max: "9999-12-31", "aria-label": name });

/** A small uppercase heading over its controls, as the Filters panel's rows have. */
const heading = (text: string) => h("span", { className: "flabel", "aria-hidden": "true" }, text);

/** A todo's due date and priority (the composer's and the page editor's Due fold). No Due
 * heading: the fold says it. */
export function todoField(due: string | null = null, priority: string | null = null) {
  const date = dayField("Due");
  const chips = soon(date, SOON, "No date", "Due soon");
  const rank = h(
    "select",
    { className: "chipfield", "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  const reset = (d: string | null, p: string | null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
    chips.mark();
  };
  reset(due, priority);
  // Every row on one left edge: the chips; then Priority under its heading
  const el = h("div", { className: "todoedit" }, chips.el, heading("Priority"), rank);
  return {
    el,
    /** Where focus goes when it opens: the due chip pressed. */
    first: () => chips.el.querySelector<HTMLElement>('[aria-pressed="true"]'),
    /** As the API takes them: null for none. */
    value: () => ({ due: date.value || null, priority: rank.value || null }),
    reset,
  };
}
