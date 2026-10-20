// Refine a search with a tap (#84): what the pages found have in common (work or personal,
// their kinds, their top tags), each with how many have it; tapping one adds its filter to
// the query, and the query's filters show first, tapped to take them out. The chips only
// edit the query's text (kind:todo, tag:tech, is:personal), so it can be typed too.
// Also the way to browse tags and a time range (presets, or dates). A chunk of its own,
// loaded with the search screen.
import { api } from "./api";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { adding, day, removing, token } from "./terms";
import { h } from "./ui";

interface Facets {
  total: number;
  kinds: [string, number][];
  tags: [string, number][];
  personal: { work: number; personal: number };
  active: { token: string; key: string; value: string; neg: boolean }[];
}

/** A kind as the PWA names it (consume: Read), and as kind: takes it. */
function kindName(kind: string): [string, string] {
  const k = KINDS.find(([name]) => name === kind);
  const label = k ? k[1] : kind.charAt(0).toUpperCase() + kind.slice(1);
  return [label, label.toLowerCase()];
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
  const chips: HTMLElement[] = f.active.map((a) => {
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
  const side = f.active.find((a) => a.key === "is" && ["work", "personal"].includes(a.value));
  const { work, personal } = f.personal;
  if (!side && work && personal) {
    chips.push(chip("Work", work, add("is:work")), chip("Personal", personal, add("is:personal")));
  }
  if (f.kinds.length > 1) {
    for (const [kind, n] of f.kinds) {
      const [label, name] = kindName(kind);
      chips.push(chip(label, n, add(token("kind", name))));
    }
  }
  for (const [tag, n] of f.tags) chips.push(chip(`#${tag}`, n, add(token("tag", tag))));
  return h(
    "div",
    {},
    h(
      "div",
      { className: "refine", role: "group", "aria-label": "Refine" },
      h("a", { className: "button facet", href: "/tags" }, icon("tag"), "Tags"),
      q && h("span", { className: "count" }, `${f.total} ${f.total === 1 ? "page" : "pages"}`),
      ...chips,
    ),
    panel,
  );
}
