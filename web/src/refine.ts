// Refine a search with a tap (#84). Under the box, Filters: one line saying what is on
// ("Filters · #home · past month"); tapped, it opens in place, over the results rather than in
// a sheet, so each tap shows its effect at once and a few taps in a row cost nothing. Inside:
// Tags (those on, each with a ✕, then a box that offers the tags in use as you type, or the
// results' top tags with their counts), Order and When, each a row of chips.
// Under the box, each filter that is on, as a chip (tap to take it out), so nothing chosen is
// hidden, led by how many pages were found (no filters on: the count alone, over the list).
// All of it only edits the query's text (tag:tech, is:personal), so it can be typed too, and
// Back, a reload or a link keep it. In the app chunk of its own (search.ts loads it with the
// screen; the service worker keeps it offline).
import { api } from "./api";
import { checkName } from "./checks";
import { day, unsorted } from "./filters";
import { icon } from "./icons";
import { actions } from "./searchacts";
import { MEDIA, removing, withGroup } from "./termedit";
import {
  adding,
  type Group,
  groupAsked,
  groupBy,
  groupDefault,
  has,
  KIND_ROW,
  kindsIn,
  listing,
  tagsIn,
  token,
  ungrouped,
} from "./terms";
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
// (without its group: words: terms.ts ungrouped)
const facets = (q: string, signal?: AbortSignal) =>
  ungrouped(q)
    ? api<Facets>(`search/facets?q=${encodeURIComponent(ungrouped(q))}`, { signal })
    : Promise.resolve(NONE);
/** The query's filters, but the kind row's kind (not a "not" one: -kind:todo). */
const filtersOf = (f: Facets) => f.active.filter((a) => a.key !== "kind" || a.neg);
const pages = (n: number) => `${n} ${n === 1 ? "page" : "pages"}`;
// The most the list shows (search.ts: 500 newest first, 1000 search results)
const shown = (q: string, n: number) => {
  const cap = listing(q) === null ? 1000 : 500;
  return n > cap ? `${pages(n)}, showing the first ${cap}: refine the search` : pages(n);
};

let open = false; // the panel, open or folded: kept while the app is (the next search too)
let typed = ""; // what is in its tag box, kept as the panel is drawn again
let allTags: Promise<[string, number][]> | null = null; // every tag in use, asked once
let inResults: { q: string; tags: Promise<[string, number][]> } | null = null; // a search's

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

// Groupings: [group: value, chip, what the Filters on row says]
// (in the Group row's order, the list's own first: Now · Due · None · A–Z for todos)
const GROUPS: [Group | "none", string, string][] = [
  ["type", "Type", "grouped by type"],
  ["now", "Now", "grouped by Now"],
  ["due", "Due", "grouped by due"],
  ["none", "None", "not grouped"],
  ["letter", "A–Z", "grouped A–Z"],
  ["tag", "Tag", "grouped by tag"],
  ["area", "Area", "grouped by area"],
];
/** The group: asked for, as the Filters on row says it ("grouped A–Z"), or null. */
const grouped = (q: string) => {
  const g = groupAsked(q);
  return g === null ? null : (GROUPS.find(([k]) => k === g)?.[2] ?? `group:${g}`);
};

// is: values in words: the rest are statuses, said as they are ("done", "in progress")
const IS: Record<string, string> = {
  claude: "Written by Claude",
  snoozed: "snoozed",
  topic: "topics",
};

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
  const check = checkName(`${a.key}:${a.value}`); // a store health check: its name
  if (check) return `${not}${check}`;
  if (a.key === "media") return `${not}${MEDIA[a.value] ?? a.value}`;
  if (a.key === "later") return `${not}to ${a.value}`;
  if (a.key === "is") return `${not}${IS[a.value] ?? a.value.replace("_", " ")}`;
  if (a.key === "kind") {
    const k = KIND_ROW.find(([, , names]) => names.includes(a.value.toLowerCase()));
    if (k) return `${not}${k[0]}`;
  }
  return a.token;
}

/** Filters, and the line above the list, for a query. apply edits the query in the box and
 * runs it: the results follow at once, and this is drawn again for the query as it is then. */
export async function refine(
  q: string,
  signal: AbortSignal,
  apply: (edit: Edit) => void,
  button: HTMLButtonElement,
): Promise<HTMLElement> {
  // Where focus is now, to put it back on the same control once drawn again
  const was = document.activeElement as HTMLElement | null;
  const k = was?.closest(".fpanel, .fon") ? was.dataset.k : null;
  const f = await facets(q, signal);
  const on = filtersOf(f);
  const group = grouped(q); // a group: asked for: a filter on too, read here (not the server's)
  const n = on.length + (group ? 1 : 0);
  const panel = h(
    "div",
    { className: "fpanel", id: "fpanel", hidden: !open },
    ...rows(q, f, apply),
  );
  // The box's slider (no count on it: the chips under the kinds say what is on); tapped, the
  // panel opens under the box
  button.replaceChildren(icon("filter"));
  button.setAttribute("aria-label", n ? `Filters, ${n} on` : "Filters");
  button.setAttribute("aria-controls", "fpanel");
  button.setAttribute("aria-expanded", String(open));
  button.onclick = () => {
    open = !open;
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  };
  // The results header: how many were found, and with results the search's own Pin and
  // Copy link at its end (searchacts.ts), one row that never changes shape
  const header =
    q &&
    h(
      "div",
      { className: "rhead" },
      h("span", { className: "count" }, shown(q, f.total)),
      f.total > 0 && actions(q),
    );
  // The filters on, as chips on a row of their own under the kinds, wrapping (none: no row):
  // each says what it is ("#home", "past month") and a tap takes it off
  const chips = on.map((a) => {
    const b = chip(label(a), null, () => apply((now) => removing(now, a.token)), true);
    b.setAttribute("aria-label", `Remove ${label(a)}`);
    b.dataset.k = `off:${a.token}`;
    return b;
  });
  if (group) {
    const b = chip(group, null, () => apply(ungrouped), true);
    b.setAttribute("aria-label", `Remove ${group}`);
    b.dataset.k = "off:group";
    chips.push(b);
  }
  const fon =
    chips.length > 0 &&
    h("div", { className: "fon", role: "group", "aria-label": "Filters on" }, ...chips);
  if (k)
    requestAnimationFrame(() => {
      const el =
        document.querySelector<HTMLElement>(`.search [data-k="${CSS.escape(k)}"]`) ??
        (k.startsWith("off:")
          ? (document.querySelector<HTMLElement>(".search .fon button") ?? button)
          : null);
      el?.focus({ preventScroll: true });
      if (el instanceof HTMLInputElement) el.setSelectionRange(el.value.length, el.value.length);
    });
  // (search.ts puts each in its place: the panel under the box, the chips under the kinds,
  // then the header over the results)
  return h("div", {}, panel, fon, header);
}

/** The panel's rows: Tags, When, then Arrange (Order and Group). */
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
  // A row: its heading above, its chips under it, wrapping (nothing scrolls out of sight)
  const row = (label: string, ...kids: (Node | false | null)[]) =>
    h(
      "div",
      { className: "frow", role: "group", "aria-label": label },
      h("span", { className: "flabel" }, label),
      h("div", { className: "opts" }, ...kids),
    );
  // Arrange's two lines: a short label, then its chips beside it, wrapping under themselves
  const line = (label: string, ...kids: Node[]) =>
    h(
      "div",
      { className: "fsub", role: "group", "aria-label": label },
      h("span", { className: "fsublabel", "aria-hidden": "true" }, label),
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
    // Only tags that narrow what is found: with a search, those of its results (each on some
    // of them, not all), with how many; before one, every tag in use
    // Asked for only when needed (a failure is not kept: the next try asks again)
    const source = (): Promise<[string, number][]> => {
      if (!q) {
        allTags ??= api<[string, number, number][]>("tags").then(
          (all) => all.map(([t, n]) => [t, n] as [string, number]),
          () => {
            allTags = null;
            return [];
          },
        );
        return allTags;
      }
      if (inResults?.q !== q) {
        const ask = {
          q,
          tags: api<Facets>(`search/facets?q=${encodeURIComponent(q)}&top=1000`).then(
            (got) => got.tags,
            () => {
              if (inResults === ask) inResults = null;
              return f.tags;
            },
          ),
        };
        inResults = ask;
      }
      return inResults.tags;
    };
    let list: [string, number][];
    // Nothing typed: the results' top tags (the facets already here); with no search yet,
    // the most used of all. Typed: every tag of the results (top=1000), fetched only now
    if (!want)
      list = q
        ? f.tags
        : (await source())
            .filter(([t]) => !t.includes("/"))
            .sort((a, b) => b[1] - a[1])
            .slice(0, 8);
    else {
      const all = (await source()).filter(([t]) => !asked.includes(t));
      const starts = all.filter(
        ([t]) => t.startsWith(want) || t.split("/").some((p) => p.startsWith(want)),
      );
      const holds = all.filter((r) => !starts.includes(r) && r[0].includes(want));
      list = [...starts, ...holds].slice(0, 8);
    }
    if (box.value.trim().replace(/^#+/, "").toLowerCase() !== want) return; // typed on meanwhile
    offers.replaceChildren(
      ...list.map(([t, n]) => {
        const b = chip(`#${t}`, n, () => addTag(t));
        b.setAttribute("aria-label", `Filter by #${t}`);
        b.dataset.k = `tag:${t}`;
        return b;
      }),
    );
    // None to offer: say why, rather than an empty row
    if (!list.length)
      offers.prepend(
        h(
          "small",
          { className: "none" },
          want ? `No tag in these results has “${want}”` : "No tag narrows these results",
        ),
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
  // (grouped A–Z with no order chosen: A–Z, as the server does)
  const now = last
    ? `${last.neg ? "-" : ""}sort:${last.value}`
    : groupBy(q) === "letter"
      ? "sort:title"
      : "";
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
  // A year past 9999 was clamped to this day: from it, nothing is found
  if (ranged.some((a) => a.key === "after" && a.value === "9999-12-31"))
    range.append(h("p", { className: "hint" }, "Dates run to 9999-12-31: nothing is after it."));

  const clear =
    filtersOf(f).length || groupAsked(q) !== null
      ? Object.assign(h("button", { type: "button", className: "link" }, "Clear filters"), {
          onclick: () => {
            typed = "";
            apply((q2) => filtersOf(f).reduce((s, a) => removing(s, a.token), ungrouped(q2)));
          },
        })
      : null;
  clear?.setAttribute("data-k", "clear");

  // Group: the list's own first (Later's Type, Todos' Now, else None), as Order has its
  // default first; Tag only with a tag filter on, Type only for Later alone, Now and Due only
  // for Todos alone
  const own = groupDefault(q) ?? "none";
  const by = groupBy(q) ?? "none";
  const fits = (k: string) =>
    k === "tag"
      ? tagsIn(q).length > 0
      : k === "type" || k === "now" || k === "area"
        ? k === own
        : k === "due"
          ? own === "now"
          : true;
  const groups = [...GROUPS.filter(([k]) => k === own), ...GROUPS.filter(([k]) => k !== own)]
    .filter(([k]) => fits(k))
    .map(([k, label]) => {
      const b = chip(label, -1, () => apply((q2) => withGroup(q2, k)));
      b.setAttribute("aria-pressed", String(k === by));
      b.setAttribute("aria-label", k === "none" ? "Not grouped" : `Group by ${label}`);
      b.dataset.k = `group:${k}`;
      return b;
    });

  // Tags and When choose what is found; Arrange, how it is laid out: Order and Group
  const arrange = h(
    "div",
    { className: "frow", role: "group", "aria-label": "Arrange" },
    h("span", { className: "flabel" }, "Arrange"),
    line("Order", ...orders),
    line("Group", ...groups),
  );
  return [
    tags,
    row(
      "When",
      ...presets,
      dates,
      (ranged.length > 0 || created) && toggle("By created date", "date:created"),
    ),
    range,
    arrange,
    clear as HTMLElement,
  ].filter(Boolean);
}
