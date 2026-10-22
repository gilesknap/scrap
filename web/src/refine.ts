// Refine a search with a tap (#84). Under the box, Filters: one line saying what is on
// ("Filters · #home · past month"); tapped, it opens in place, over the results rather than in
// a sheet, so each tap shows its effect at once and a few taps in a row cost nothing. Inside:
// Tags (those on, each with a ✕, then a box that offers the tags in use as you type, or the
// results' top tags with their counts), Order, When, and Work or personal, each a row of chips.
// Above the list, how many pages were found and each filter that is on, as a chip (tap to take
// it out), so nothing chosen is hidden. All of it only edits the query's text (tag:tech,
// is:personal), so it can be typed too, and Back, a reload or a link keep it. In the app
// shell, so Filters opens at once.
import { api } from "./api";
import { icon } from "./icons";
import { adding, day, has, kindsIn, removing, token, unsorted } from "./terms";
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

let open = false; // the panel, open or folded: kept while the app is (the next search too)
let typed = ""; // what is in its tag box, kept as the panel is drawn again
let allTags: Promise<[string, number][]> | null = null; // every tag in use, asked once

// Orders: [sort: as typed, label]; "" is the default (best match, or newest edit first)
const SORTS = [
  ["sort:created", "Newest"],
  ["-sort:created", "Oldest"],
  ["sort:updated", "Last edited"],
  ["sort:title", "A–Z"],
];
// A todo's orders, offered when the search is of todos (kind:todo)
const TODO_SORTS = [
  ["sort:due", "Due soonest"],
  ["sort:priority", "Priority"],
];
// Time ranges: [label, token value, what it says]
const RANGES = [
  ["1w", "1w", "the past week"],
  ["1m", "1m", "the past month"],
  ["1y", "1y", "the past year"],
];

/** A filter on, as a chip says it: "#home", "past month", "A–Z", "personal". */
function label(a: Facets["active"][number]) {
  const not = a.neg ? "not " : "";
  if (a.key === "tag") return `${not}#${a.value}`;
  if (a.key === "sort") {
    const t = `${a.neg ? "-" : ""}sort:${a.value}`;
    const named = [...SORTS, ...TODO_SORTS, ["-sort:updated", "First edited"]];
    return named.find(([k]) => k === t)?.[1] ?? t;
  }
  if (a.key === "after" && /^\d+[dwmy]$/.test(a.value))
    return RANGES.find(([, v]) => v === a.value)?.[2].replace("the ", "") ?? a.token;
  if (a.key === "is") return `${not}${a.value}`;
  return a.token;
}

/** Filters, and the line above the list, for a query. apply edits the query in the box and
 * runs it: the results follow at once, and this is drawn again for the query as it is then. */
export async function refine(
  q: string,
  signal: AbortSignal,
  apply: (edit: Edit) => void,
): Promise<HTMLElement> {
  // Where focus is now, to put it back on the same control once drawn again
  const was = document.activeElement as HTMLElement | null;
  const k = was?.closest(".refine") ? was.dataset.k : null;
  const f = await facets(q, signal);
  const on = filtersOf(f);
  const panel = h(
    "div",
    { className: "fpanel", id: "fpanel", hidden: !open },
    ...rows(q, f, apply),
  );
  // Filters (how many are on), then the filters on as chips, one line that scrolls sideways:
  // each says what it is ("#home", "past month") and a tap takes it off. Filters opens the
  // panel under them, in place
  const toggle = h(
    "button",
    {
      type: "button",
      className: "facet ftoggle",
      "aria-expanded": String(open),
      "aria-controls": "fpanel",
      "aria-label": on.length ? `Filters, ${on.length} on` : "Filters",
      onclick: () => {
        open = !open;
        panel.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
      },
    },
    icon("filter"),
    "Filters",
    on.length > 0 && h("b", {}, String(on.length)),
  );
  toggle.dataset.k = "toggle";
  const chips = on.map((a) => {
    const b = chip(label(a), null, () => apply((now) => removing(now, a.token)), true);
    b.setAttribute("aria-label", `Remove ${label(a)}`);
    b.dataset.k = `off:${a.token}`;
    return b;
  });
  const bar = h(
    "div",
    { className: "refine", role: "group", "aria-label": "Filters" },
    h("div", { className: "fbar" }, toggle, h("div", { className: "fon" }, ...chips)),
    panel,
  );
  // Each row scrolled so what is chosen in it shows (an order off to the right, say)
  requestAnimationFrame(() => {
    for (const b of panel.querySelectorAll<HTMLElement>('.opts [aria-pressed="true"]')) {
      const row = b.parentElement as HTMLElement;
      if (b.offsetLeft + b.offsetWidth > row.scrollLeft + row.clientWidth)
        row.scrollLeft = b.offsetLeft + b.offsetWidth - row.clientWidth + 16;
    }
  });
  if (k)
    requestAnimationFrame(() => {
      const el =
        bar.querySelector<HTMLElement>(`[data-k="${CSS.escape(k)}"]`) ??
        (k.startsWith("off:") ? toggle : null); // a chip taken off: Filters, beside it
      el?.focus({ preventScroll: true });
      if (el instanceof HTMLInputElement) el.setSelectionRange(el.value.length, el.value.length);
    });
  return h(
    "div",
    {},
    bar,
    q && h("p", { className: "found" }, h("span", { className: "count" }, pages(f.total))),
  );
}

/** The panel's rows: Tags, Order, When, Work or personal. */
function rows(q: string, f: Facets, apply: (edit: Edit) => void): HTMLElement[] {
  const toggle = (label: string, t: string, n = -1, others: string[] = []) => {
    const on = has(q, t);
    const b = chip(label, n, () =>
      apply((now) => (on ? removing(now, t) : adding(others.reduce(removing, now), t))),
    );
    b.setAttribute("aria-pressed", String(on));
    b.dataset.k = label;
    return b;
  };
  const row = (label: string, ...kids: (Node | false | null)[]) =>
    h(
      "div",
      { className: "frow", role: "group", "aria-label": label },
      h("span", { className: "flabel" }, label),
      h("div", { className: "opts" }, ...kids),
    );

  // Tags: those on (a ✕ each), a box, and the tags it offers: as typed, the tags in use that
  // match; with nothing typed, the results' top tags with their counts
  const asked = f.active.filter((a) => a.key === "tag" && !a.neg).map((a) => a.value);
  const offers = h("div", { className: "opts" });
  const box = h("input", {
    type: "text",
    value: typed,
    placeholder: "Add a tag",
    "aria-label": "Add a tag filter",
    autocapitalize: "none",
    autocomplete: "off",
    enterKeyHint: "done",
  });
  box.dataset.k = "tagbox";
  const addTag = (t: string) => {
    typed = "";
    apply((now) => adding(now, token("tag", t)));
  };
  const offer = async () => {
    const want = box.value.trim().replace(/^#+/, "").toLowerCase();
    typed = box.value;
    allTags ??= api<[string, number, number][]>("tags").then(
      (all) => all.map(([t, n]) => [t, n] as [string, number]),
      () => [],
    );
    let list: [string, number][];
    // Nothing typed: the results' top tags; with no search yet, the most used of all
    if (!want)
      list = f.tags.length
        ? f.tags
        : (await allTags)
            .filter(([t]) => !asked.includes(t) && !t.includes("/"))
            .sort((a, b) => b[1] - a[1])
            .slice(0, 8);
    else {
      const all = (await allTags).filter(([t]) => !asked.includes(t));
      const starts = all.filter(
        ([t]) => t.startsWith(want) || t.split("/").some((p) => p.startsWith(want)),
      );
      const holds = all.filter((r) => !starts.includes(r) && r[0].includes(want));
      list = [...starts, ...holds].slice(0, 8);
    }
    if (box.value.trim().replace(/^#+/, "").toLowerCase() !== want) return; // typed on meanwhile
    offers.replaceChildren(
      ...list.map(([t, n]) => {
        const b = chip(`#${t}`, want ? -1 : n, () => addTag(t));
        b.setAttribute("aria-label", `Filter by #${t}`);
        b.dataset.k = `tag:${t}`;
        return b;
      }),
      ...(want
        ? []
        : [h("a", { className: "button facet", href: "/tags" }, icon("tag"), "All tags")]),
    );
  };
  box.oninput = () => void offer();
  box.onkeydown = (e) => {
    if (e.key !== "Enter" || e.isComposing) return;
    e.preventDefault();
    const first = offers.querySelector<HTMLElement>("[data-k^='tag:']");
    const want = box.value.trim().replace(/^#+/, "").toLowerCase();
    if (first && want) first.click();
    else if (want) addTag(want); // a tag typed whole: searched as typed
  };
  void offer();
  const tags = h(
    "div",
    { className: "frow ftags", role: "group", "aria-label": "Tags" },
    h("span", { className: "flabel" }, "Tags"),
    h("div", { className: "tagline" }, box),
    offers,
  );

  // Order: one tap each; the default (best match, or last edited) has its own chip
  const todos = kindsIn(q).length === 1 && kindsIn(q)[0][1] === "todo";
  const last = f.active.filter((a) => a.key === "sort").at(-1);
  const now = last ? `${last.neg ? "-" : ""}sort:${last.value}` : "";
  const words = q.split(/\s+/).some((w) => w && !"-!".includes(w[0]) && !w.includes(":"));
  const orders = [
    ["", words ? "Best match" : "Last edited"],
    ...SORTS,
    ...(todos ? TODO_SORTS : []),
  ]
    .filter(([t]) => words || t !== "sort:updated")
    .map(([t, label]) => {
      const b = chip(label, -1, () => apply((q2) => (t ? adding(unsorted(q2), t) : unsorted(q2))));
      b.setAttribute("aria-pressed", String(t === now));
      b.dataset.k = `sort:${t}`;
      return b;
    });

  // When: a preset (after:1w, by when last edited; date:created for when made), or dates
  const ranged = f.active.filter((a) => a.key === "after" || a.key === "before");
  const created = has(q, "date:created");
  const presets = RANGES.map(([label, value, said]) => {
    const others = ranged.map((a) => a.token);
    const b = toggle(label, `after:${value}`, -1, others);
    b.setAttribute("aria-label", `${created ? "Made" : "Edited"} in ${said}`);
    return b;
  });
  const dated = ranged.some((a) => a.value.length === 10);
  const range = h("div", { className: "range", hidden: !dated });
  const dates = chip("Dates…", -1, () => {
    range.hidden = !range.hidden;
    dates.setAttribute("aria-expanded", String(!range.hidden));
    if (!range.hidden) range.querySelector("input")?.focus();
  });
  dates.setAttribute("aria-expanded", String(dated));
  dates.dataset.k = "dates";
  const kind = { type: "date", min: "0001-01-01", max: "9999-12-31" };
  const from = h("input", { ...kind, "aria-label": "From" });
  const to = h("input", { ...kind, "aria-label": "To" });
  for (const a of ranged)
    (a.key === "after" ? from : to).value = a.value.length === 10 ? a.value : "";
  const setDates = () =>
    apply((q2) => {
      let next = ranged.reduce((s, a) => removing(s, a.token), q2);
      if (day(from.value)) next = adding(next, `after:${day(from.value)}`);
      if (day(to.value)) next = adding(next, `before:${day(to.value)}`);
      return next;
    });
  from.onchange = to.onchange = setDates; // applied as picked: no Apply to find
  range.append(h("label", {}, "From", from), h("label", {}, "To", to));

  const { work, personal } = f.personal;
  const sides = [
    (work > 0 || has(q, "is:work")) && toggle("Work", "is:work", work, ["is:personal"]),
    (personal > 0 || has(q, "is:personal")) &&
      toggle("Personal", "is:personal", personal, ["is:work"]),
  ];
  const clear = filtersOf(f).length
    ? Object.assign(h("button", { type: "button", className: "link" }, "Clear filters"), {
        onclick: () => {
          typed = "";
          apply((q2) => filtersOf(f).reduce((s, a) => removing(s, a.token), q2));
        },
      })
    : null;
  clear?.setAttribute("data-k", "clear");

  return [
    tags,
    row("Order", ...orders),
    row(
      "When",
      ...presets,
      dates,
      (ranged.length > 0 || created) && toggle("By created date", "date:created"),
    ),
    range,
    sides.some(Boolean) ? row("Area", ...sides) : (null as unknown as HTMLElement),
    clear as HTMLElement,
  ].filter(Boolean);
}
