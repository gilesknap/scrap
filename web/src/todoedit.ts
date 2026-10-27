// A todo's due date and priority (#104): one row of chips (Today, Tomorrow and Next week set it
// in one tap, Pick a date… opens the native date picker for any other day, No date empties it)
// and a menu of priorities; on its page also Snooze, folded to one line (Tomorrow, Next week,
// Pick a date…, Not snoozed). In place on a todo's page (todoForm: Save sends them, no new
// revision; its Cancel and Save take over the page's action row) and in the editor (todoField,
// sent with the page). A chunk of its own: the page's due line and the editor load it.
import { api, type Page } from "./api";
import { icon } from "./icons";
import { short as dayName, today } from "./status";
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
const PICK = "Pick a date…";

/** A day's chips, in one wrapping row: those that set it in one tap (Today, Tomorrow, Next
 * week: days on), then Pick a date… (the native picker for any other day: the date field is
 * hidden under it, still named, and shown in its place where the picker can't be opened), then
 * one that empties it (No date, Not snoozed). Each as if picked (an input event: the editor
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

/** A todo's due date and priority; with snooze (a day, or null), its snooze too: that is the
 * page's own form, which says Due over its chips (in the editor its fold says it already). */
export function todoField(
  due: string | null = null,
  priority: string | null = null,
  snooze?: string | null,
) {
  const date = dayField("Due");
  const chips = soon(date, SOON, "No date", "Due soon");
  const rank = h(
    "select",
    { "aria-label": "Priority" },
    h("option", { value: "" }, "No priority"),
    ...PRIORITIES.map((p) => h("option", { value: p }, `${p[0].toUpperCase()}${p.slice(1)}`)),
  );
  // Snooze: out of Now (and the Todos tab's count) until that day. Rarely set, so folded to one
  // quiet line under its heading, saying the day it is snoozed till ("till 29 Oct") or none
  const nap = snooze === undefined ? null : dayField("Snooze until");
  const naps = nap && soon(nap, SOON.slice(1), "Not snoozed", "Snooze for");
  const said = h("span", { className: "says" });
  const says = () => {
    said.textContent = nap?.value ? `till ${dayName(nap.value)}` : "none";
  };
  nap?.addEventListener("input", says);
  nap?.addEventListener("change", says);
  const reset = (d: string | null, p: string | null, z: string | null = null) => {
    date.value = d ?? "";
    rank.value = p ?? "";
    if (nap) nap.value = z ?? "";
    chips.mark();
    naps?.mark();
    says();
  };
  reset(due, priority, snooze);
  // Each part under its heading, every row on one left edge: the chips; then Priority; then (on
  // the page) Snooze, a fold
  const el = h(
    "div",
    { className: "todoedit" },
    nap && heading("Due"),
    chips.el,
    heading("Priority"),
    rank,
    nap && naps
      ? h(
          "details",
          { className: "snooze" },
          h("summary", {}, h("span", { className: "flabel" }, "Snooze"), said),
          naps.el,
        )
      : "",
  );
  return {
    el,
    /** Where focus goes when it opens: the due chip pressed. */
    first: () => chips.el.querySelector<HTMLElement>('[aria-pressed="true"]'),
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
 * cancelled (the page is then drawn as it is now, not as it was when the form opened). Its
 * Cancel and Save (acts) are the page's to show in its action row, in Mark done's place: in
 * view however tall the form is. Save is the form's (its form attribute), so Enter in a field
 * still sends it. */
export function todoForm(p: Page, close: (p?: Page) => void) {
  const field = todoField(p.due, p.priority, p.snoozed_until ?? null);
  const save = h("button", { type: "submit", className: "primary" }, icon("done"), "Save");
  save.setAttribute("form", "dueform");
  const form = h(
    "form",
    {
      id: "dueform",
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
  const ask = (v: Value) => {
    form.querySelector(".choice")?.remove();
    const until = v.snoozed_until as string;
    const choice = h(
      "div",
      { className: "choice", role: "group", "aria-label": "Due date" },
      h(
        "p",
        {},
        `Snoozed past its due date (${dayName(v.due as string)}). Move the due date to ${dayName(until)} too?`,
      ),
      h(
        "button",
        { type: "button", className: "primary", onclick: () => send({ ...v, due: until }) },
        "Move due date",
      ),
      h("button", { type: "button", onclick: () => send(v) }, "Keep due date"),
    );
    form.append(choice);
    (choice.querySelector("button") as HTMLButtonElement).focus();
  };
  const cancel = h("button", { type: "button", onclick: () => close() }, icon("close"), "Cancel");
  // Escape cancels from the action row's buttons too (they go with the form when it closes)
  for (const b of [cancel, save])
    b.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  return { form, acts: [cancel, save], focus: () => field.first()?.focus() };
}
