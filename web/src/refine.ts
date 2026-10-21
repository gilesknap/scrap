// Refine a search with a tap (#84). Under the box, a short row that never grows at its left
// end: Filters (with how many are on), then the results' top tags, each with a count (tap one
// to add tag:). Above the list, how many pages were found and each filter that is on, as a
// chip (tap to take it out), so nothing chosen is hidden. Filters opens a bottom sheet: the
// order, a time range, Work or Personal and Browse tags (a todo's due date is searched by
// typing due:, or on the Todos screen). All of it
// only edits the query's text (tag:tech, is:personal), so it can be typed too. In the app
// shell, so Filters opens at once.
import { api } from "./api";
import { back, go, view } from "./app";
import { icon } from "./icons";
import { adding, day, has, kindsIn, removing, token } from "./terms";
import { h } from "./ui";

interface Facets {
  total: number;
  kinds: [string, number][];
  tags: [string, number][];
  personal: { work: number; personal: number };
  active: { token: string; key: string; value: string; neg: boolean }[];
}
type Edit = (q: string) => string;

/** n: a count to show; null: a filter of the query (tap to remove); -1: neither. */
const chip = (label: Node | string, n: number | null, onclick: () => void, on = false) =>
  h(
    "button",
    { type: "button", className: on ? "facet on" : "facet", onclick },
    label,
    n === null ? icon("close") : n >= 0 && h("small", {}, String(n)),
  );

const NONE: Facets = {
  total: 0,
  kinds: [],
  tags: [],
  personal: { work: 0, personal: 0 },
  active: [],
};
const facets = (q: string, signal?: AbortSignal) =>
  q ? api<Facets>(`search/facets?q=${encodeURIComponent(q)}`, { signal }) : Promise.resolve(NONE);
/** The query's filters, but the kind row's kind (not a "not" one: -kind:todo). */
const filtersOf = (f: Facets) => f.active.filter((a) => a.key !== "kind" || a.neg);
const pages = (n: number) => `${n} ${n === 1 ? "page" : "pages"}`;

/** The row and the line above the list, for a query (with none: Filters alone). apply edits
 * the query in the box and runs it. */
export async function refine(
  q: string,
  signal: AbortSignal,
  apply: (edit: Edit) => void,
): Promise<HTMLElement> {
  const f = await facets(q, signal);
  const on = filtersOf(f);
  const filters = h(
    "button",
    {
      type: "button",
      className: "facet filter",
      "aria-haspopup": "dialog",
      "aria-label": on.length ? `Filters, ${on.length} on` : "Filters",
      onclick: () => sheet(q, f, apply),
    },
    icon("filter"),
    "Filters",
    on.length > 0 && h("b", {}, String(on.length)),
  );
  const tags = f.tags.map(([tag, n]) =>
    chip(`#${tag}`, n, () => apply((now) => adding(now, token("tag", tag)))),
  );
  return h(
    "div",
    {},
    h("div", { className: "refine", role: "group", "aria-label": "Refine" }, filters, ...tags),
    q &&
      h(
        "div",
        { className: "found" },
        h("span", { className: "count" }, pages(f.total)),
        ...on.map((a) => {
          const b = chip(a.token, null, () => apply((now) => removing(now, a.token)), true);
          b.setAttribute("aria-label", `Remove ${a.token}`);
          return b;
        }),
      ),
  );
}

// ---- the Filters sheet

// Orders: [sort: as typed, label]; "" is the default (best match, or newest edit first)
const SORTS = [
  ["sort:updated", "Last edited"],
  ["-sort:updated", "First edited"],
  ["sort:created", "Newest"],
  ["-sort:created", "Oldest"],
  ["sort:title", "Title A–Z"],
  ["-sort:title", "Title Z–A"],
];
// A todo's orders, offered when the search is of todos (kind:todo)
const TODO_SORTS = [
  ["sort:due", "Due soonest"],
  ["-sort:due", "Due latest"],
  ["sort:priority", "Priority"],
];
// Time ranges: [label, token value, what it says]
const RANGES = [
  ["1w", "1w", "the past week"],
  ["1m", "1m", "the past month"],
  ["1y", "1y", "the past year"],
];

/** The Filters sheet: a modal dialog at the bottom of the screen, under the thumb. A tap in
 * it edits the query at once (the list behind follows); Done, Escape, Back or a tap outside
 * closes it, and focus goes back to Filters. It has a history entry of its own, so Back
 * closes it rather than leaving the screen. */
function sheet(q: string, f: Facets, apply: (edit: Edit) => void) {
  const here = () => location.pathname + location.search;
  let url = here(); // the query's address, as the edits leave it
  let then: (() => void) | null = null; // after it has closed: e.g. on to the tags
  let entry = true; // its history entry is the current one
  let n = 0; // the latest facets asked for
  const body = h("div", { className: "sheet-body" });
  const title = h("h2", { id: "sheet-title", tabIndex: -1, autofocus: true }, "Filters");
  const count = h("span", { className: "count" });
  const clear = h("button", { type: "button", className: "ghost" }, "Clear filters");
  const done = h("button", { type: "button", className: "primary" }, "Done");
  const dlg = h(
    "dialog",
    { className: "sheet", "aria-labelledby": "sheet-title" },
    h(
      "div",
      {},
      h("div", { className: "sheet-top" }, title, count),
      body,
      h("div", { className: "sheet-bar" }, clear, done),
    ),
  );
  const set = (edit: Edit) => {
    q = edit(q);
    apply(() => q);
    url = here();
    const k = (document.activeElement as HTMLElement | null)?.dataset?.k;
    const mine = ++n;
    facets(q).then(
      (got) => {
        if (mine !== n || !dlg.open) return;
        fill(got);
        if (k) (body.querySelector(`[data-k="${k}"]`) as HTMLElement | null)?.focus();
      },
      () => {},
    );
  };
  const fill = (got: Facets) => {
    f = got;
    count.textContent = q ? pages(f.total) : "";
    clear.hidden = !filtersOf(f).length;
    body.replaceChildren(
      ...sections(q, f, set, () => {
        then = () => go("/tags");
        dlg.close();
      }),
    );
  };
  clear.onclick = () => set((now) => filtersOf(f).reduce((s, a) => removing(s, a.token), now));
  done.onclick = () => dlg.close();
  dlg.onclick = (e) => e.target === dlg && dlg.close(); // a tap outside it (on the backdrop)
  const popped = () => {
    entry = false; // main.ts took it off back.take: the screen stays as it is
    if (here() !== url) history.replaceState(null, "", url); // the query as it is now
    if (dlg.open) dlg.close();
    then?.();
  };
  dlg.addEventListener("close", () => {
    dlg.remove();
    if (entry) history.back(); // its entry off the stack: popped() runs next
    if (!then) (document.querySelector(".refine .filter") as HTMLElement | null)?.focus();
  });
  view.signal.addEventListener("abort", () => {
    if (back.take === popped) back.take = null;
    dlg.remove();
  });
  fill(f);
  history.pushState({ sheet: 1 }, "");
  back.take = popped;
  document.body.append(dlg);
  dlg.showModal();
}

/** The sheet's sections for a query: Sort, When, Work or personal, Due (todos), Tags. */
function sections(q: string, f: Facets, set: (edit: Edit) => void, toTags: () => void) {
  const toggle = (label: string, t: string, n = -1, others: string[] = []) => {
    const on = has(q, t);
    const b = chip(label, n, () =>
      set((now) => (on ? removing(now, t) : adding(others.reduce(removing, now), t))),
    );
    b.setAttribute("aria-pressed", String(on));
    b.dataset.k = label;
    return b;
  };
  const group = (label: string, ...kids: (Node | false)[]) =>
    h(
      "section",
      { "aria-label": label },
      h("h3", {}, label),
      h("div", { className: "opts" }, ...kids),
    );
  // Sort: a native menu (the phone's own picker), writing sort: into the query
  const todos = kindsIn(q).length === 1 && kindsIn(q)[0][1] === "todo";
  const sorts = f.active.filter((a) => a.key === "sort");
  const last = sorts[sorts.length - 1];
  const words = q.split(/\s+/).some((w) => w && !"-!".includes(w[0]) && !w.includes(":"));
  const sort = h(
    "select",
    {
      className: "button facet sort",
      "aria-label": "Sort",
      onchange: () =>
        set((now) => {
          const rest = sorts.reduce((s, a) => removing(s, a.token), now);
          return sort.value ? adding(rest, sort.value) : rest;
        }),
    },
    h("option", { value: "" }, words ? "Best match" : "Last edited"),
    ...[...SORTS, ...(todos ? TODO_SORTS : [])]
      .filter(([t]) => words || t !== "sort:updated")
      .map(([t, label]) => h("option", { value: t }, label)),
  );
  sort.value = last ? `${last.neg ? "-" : ""}sort:${last.value}` : "";
  if (sort.selectedIndex < 0) sort.value = ""; // an unknown order: the default
  sort.dataset.k = "sort";
  // When: a preset (after:1w, by when last edited; date:created for when made), or dates
  const ranged = f.active.filter((a) => a.key === "after" || a.key === "before");
  const created = has(q, "date:created");
  const presets = RANGES.map(([label, value, says]) => {
    const others = ranged.map((a) => a.token);
    const b = toggle(label, `after:${value}`, -1, others);
    b.setAttribute("aria-label", `${created ? "Made" : "Edited"} in ${says}`);
    return b;
  });
  const dated = ranged.some((a) => a.value.length === 10);
  const panel = h("div", { className: "range", hidden: !dated });
  const dates = chip("Dates…", -1, () => {
    panel.hidden = !panel.hidden;
    dates.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) panel.querySelector("input")?.focus();
  });
  dates.setAttribute("aria-expanded", String(dated));
  dates.dataset.k = "dates";
  const range = { type: "date", min: "0001-01-01", max: "9999-12-31" };
  const from = h("input", { ...range, "aria-label": "From" });
  const to = h("input", { ...range, "aria-label": "To" });
  for (const a of ranged)
    (a.key === "after" ? from : to).value = a.value.length === 10 ? a.value : "";
  panel.append(
    h("label", {}, "From", from),
    h("label", {}, "To", to),
    h(
      "button",
      {
        type: "button",
        onclick: () =>
          set((now) => {
            let next = ranged.reduce((s, a) => removing(s, a.token), now);
            if (day(from.value)) next = adding(next, `after:${day(from.value)}`);
            if (day(to.value)) next = adding(next, `before:${day(to.value)}`);
            return next;
          }),
      },
      "Apply",
    ),
    h("small", {}, "Days are UTC; both ends included."),
  );
  const { work, personal } = f.personal;
  const sides = [
    (work > 0 || has(q, "is:work")) && toggle("Work", "is:work", work, ["is:personal"]),
    (personal > 0 || has(q, "is:personal")) &&
      toggle("Personal", "is:personal", personal, ["is:work"]),
  ];
  const tags = h("a", { className: "button facet", href: "/tags" }, icon("tag"), "Browse tags");
  tags.onclick = (e) => {
    e.preventDefault();
    toTags();
  };
  return [
    group("Sort", sort),
    group(
      "When",
      ...presets,
      dates,
      (ranged.length > 0 || created) && toggle("By created date", "date:created"),
      panel,
    ),
    sides.some(Boolean) && group("Work or personal", ...sides),
    group("Tags", tags),
  ].filter((s): s is HTMLElement => !!s);
}
