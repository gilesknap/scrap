// Refine a search with a tap (#84): what the pages found have in common (work or personal,
// their top tags), each with how many have it; tapping one adds its filter to the query, and
// the query's filters show first, tapped to take them out (kinds are search.ts's fixed row).
// The chips only edit the query's text (tag:tech, is:personal), so it can be typed too. Also
// Clear, the way to browse tags, the order (sort:), and a time range (presets, or dates). A
// chunk of its own, loaded with the search screen.
import { api } from "./api";
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
// Orders: [sort: as typed, label]; "" is the default (best match, or newest edit first)
const SORTS = [
  ["sort:updated", "Last edited"],
  ["-sort:updated", "First edited"],
  ["sort:created", "Newest"],
  ["-sort:created", "Oldest"],
  ["sort:title", "Title A–Z"],
  ["-sort:title", "Title Z–A"],
];
// A todo's orders, offered on the Todos screen (kind:todo)
const TODO_SORTS = [
  ["sort:due", "Due soonest"],
  ["-sort:due", "Due latest"],
  ["sort:priority", "Priority"],
];
// Saved views of the Todos screen (#104): [label, what each adds to kind:todo]. The ones not
// done or cancelled, soonest first. Tapped again, the view is cleared.
const OPEN = ["-is:done", "-is:cancelled", "sort:due"];
const VIEWS: [string, string[]][] = [
  ["Today", ["due:today", ...OPEN]],
  ["Overdue", ["due:<today", ...OPEN]],
  ["Upcoming", ["due:>today", ...OPEN]],
];
// Time ranges: [label, token value, what it says]
const RANGES = [
  ["1w", "1w", "the past week"],
  ["1m", "1m", "the past month"],
  ["1y", "1y", "the past year"],
];

/** The chips for a query (with none: Tags and the time ranges). apply edits the query in the box and runs it. */
export async function refine(
  q: string,
  signal: AbortSignal,
  apply: (edit: (q: string) => string) => void, // edits the query in the box now
): Promise<HTMLElement> {
  const f = q ? await api<Facets>(`search/facets?q=${encodeURIComponent(q)}`, { signal }) : NONE;
  const add = (t: string) => () => apply((now) => adding(now, t));
  // The Todos screen: its views, the one on as a chip that is on (its filters not shown again)
  const todos = kindsIn(q).length === 1 && kindsIn(q)[0][1] === "todo";
  const on = todos ? VIEWS.find(([, ts]) => ts.every((t) => has(q, t))) : undefined;
  const views = todos
    ? VIEWS.map(([label, ts]) =>
        chip(
          label,
          -1,
          () =>
            apply((now) => {
              let next = (on ?? ["", []])[1].reduce(removing, now);
              if (on?.[0] !== label) next = ts.reduce(adding, next);
              return next;
            }),
          on?.[0] === label,
        ),
      )
    : [];
  // A kind is the fixed row's (search.ts), unless it is a "not" one (-kind:todo); an order
  // is the Sort menu's
  const chips: HTMLElement[] = f.active
    .filter((a) => (a.key !== "kind" || a.neg) && a.key !== "sort" && !on?.[1].includes(a.token))
    .map((a) => {
      const b = chip(a.token, null, () => apply((now) => removing(now, a.token)), true);
      b.setAttribute("aria-label", `Remove ${a.token}`);
      return b;
    });
  // A time range: after:1w (by when last edited; date:created for when made), or dates
  const ranged = f.active.filter((a) => a.key === "after" || a.key === "before");
  const created = f.active.some((a) => a.key === "date" && a.value === "created" && !a.neg);
  const panel = h("div", { className: "range", hidden: true });
  if (!ranged.length) {
    for (const [label, value, says] of RANGES) {
      const b = chip(label, -1, add(`after:${value}`));
      b.setAttribute("aria-label", `${created ? "Made" : "Edited"} in ${says}`);
      chips.push(b);
    }
  } else if (!created) {
    chips.push(chip("By created date", -1, add("date:created")));
  }
  const dates = chip("Dates…", -1, () => {
    panel.hidden = !panel.hidden;
    dates.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) panel.querySelector("input")?.focus();
  });
  dates.setAttribute("aria-expanded", "false");
  chips.push(dates);
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
        className: "primary",
        onclick: () => {
          apply((now) => {
            let next = ranged.reduce((s, a) => removing(s, a.token), now);
            if (day(from.value)) next = adding(next, `after:${day(from.value)}`);
            if (day(to.value)) next = adding(next, `before:${day(to.value)}`);
            return next;
          });
        },
      },
      "Apply",
    ),
    h("small", {}, "Days are UTC; both ends included."),
  );
  // Sort: a native menu (the phone's own picker), writing sort: into the query. Without a
  // query (no facets fetched) the list is the default, newest edit first
  const sorts = f.active.filter((a) => a.key === "sort");
  const last = sorts[sorts.length - 1];
  const words = q.split(/\s+/).some((w) => w && !"-!".includes(w[0]) && !w.includes(":"));
  const sort = h(
    "select",
    {
      className: "button facet sort",
      "aria-label": "Sort",
      onchange: () =>
        apply((now) => {
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
  const side = f.active.find((a) => a.key === "is" && ["work", "personal"].includes(a.value));
  const { work, personal } = f.personal;
  if (!side && work && personal) {
    chips.push(chip("Work", work, add("is:work")), chip("Personal", personal, add("is:personal")));
  }
  for (const [tag, n] of f.tags) chips.push(chip(`#${tag}`, n, add(token("tag", tag))));
  return h(
    "div",
    {},
    h(
      "div",
      { className: "refine", role: "group", "aria-label": "Refine" },
      // Anything chosen or typed: one tap back to every page, newest first
      q && chip("Clear", -1, () => apply(() => "")),
      h("a", { className: "button facet", href: "/tags" }, icon("tag"), "Tags"),
      sort,
      q && h("span", { className: "count" }, `${f.total} ${f.total === 1 ? "page" : "pages"}`),
      ...views,
      ...chips,
    ),
    panel,
  );
}
