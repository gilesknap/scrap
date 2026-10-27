// The Todos screen: what to do now, first (now.ts ranks it). A switch on top picks the list:
// Now (open todos: overdue, today, high priority with no date, then the rest; done ones
// folded away at the end), Upcoming (due from tomorrow to a week away) or All (last edited first). The address
// says which (/todos, /todos?view=upcoming, /todos?view=all), so Back and a reload come back
// to it. Rows are the search screen's: tick, swipe, a pager through the list. A lazy chunk.
import { api, type Hit, writeClock } from "./api";
import { address, view } from "./app";
import type { Section } from "./groups";
import { icon } from "./icons";
import type { pageRow } from "./lists";
import { isOpen, now, toDo, UPCOMING, upcoming } from "./now";
import { drawSections } from "./sections";
import { today } from "./status";
import { empty, h, problem } from "./ui";

// The snoozed todos, as the search screen has them (the count of them links there)
const SNOOZED = "kind:todo is:snoozed sort:due";
// Each view as a search, for Refine at the count line's end (Now is Todos' own grouping there)
const AS_SEARCH: Record<string, string> = {
  now: "kind:todo",
  upcoming: UPCOMING,
  all: "kind:todo sort:updated group:none",
};

// Each with its icon, as search's kind row has them: Now a clock, Upcoming the due calendar,
// All search's All
const MODES = [
  ["now", "Now", "now"],
  ["upcoming", "Upcoming", "due"],
  ["all", "All", "all"],
] as const;
const LIMIT = 500; // the API's most: the done ones, last edited first
const PAGE = 100; // search's most per request
const OPEN = encodeURIComponent("kind:todo -is:done -is:cancelled");
type Todo = Omit<Hit, "snippet">;

const modeOf = () => {
  const v = new URLSearchParams(location.search).get("view");
  return MODES.find(([m]) => m === v) ?? MODES[0];
};

/** row: lists.ts's pageRow, passed in (main.ts) so this chunk imports nothing from lists.ts:
 * that would split the app shell into more, less compressible chunks. */
export async function todos(row: typeof pageRow): Promise<Node> {
  const { signal } = view;
  const fetchAll = async () => {
    if (!navigator.onLine) throw new TypeError("offline");
    // Every open todo (searched, 100 at a time), however long ago it was edited; the done
    // and cancelled ones only from the last LIMIT edited, for the fold and All
    const open = async () => {
      const got: Hit[] = [];
      for (let n = PAGE; n === PAGE; ) {
        const q = `q=${OPEN}&limit=${PAGE}&offset=${got.length}`;
        const more = await api<Hit[]>(`search?${q}`, { signal });
        got.push(...more);
        n = more.length;
      }
      return got;
    };
    const [opened, recent] = await Promise.all([
      open(),
      api<Todo[]>(`pages?limit=${LIMIT}&kind=todo`, { signal }),
    ]);
    // by id: an edit between two pages shifts the list, so a todo can come twice
    const seen = new Set<string>();
    return [...opened, ...recent.filter((p) => !isOpen(p))]
      .filter((p) => !seen.has(p.id) && !!seen.add(p.id))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  };
  // An upload that lands while the list is first fetched (New todo's, saved just before the
  // composer closed onto this screen) may not be in it: noted here, asked again below
  let missed = false;
  const miss = () => {
    missed = true;
  };
  document.addEventListener("queuechange", miss, { signal });
  let list: Todo[];
  try {
    list = await fetchAll();
  } catch (e) {
    return problem(e);
  } finally {
    document.removeEventListener("queuechange", miss);
  }
  // A todo saved meanwhile (New todo, in the top bar): the list again once its upload is done.
  // Each change asks again; only the newest answer is drawn (an older one may land last)
  let asked = 0;
  const again = async () => {
    const mine = ++asked;
    try {
      const clock = writeClock();
      const got = await fetchAll();
      if (mine !== asked || signal.aborted) return; // a newer ask is on its way, or we left
      // A change (a tick) began or ended meanwhile: this may predate it. Ask again
      if (clock !== writeClock()) return void again();
      list = got;
      draw();
    } catch {} // offline, or the server unreachable: the list as it was
  };
  document.addEventListener("queuechange", again, { signal });
  if (missed) void again();
  const body = h("div", { className: "groups" });
  // The results header, as the search screen's: the count, then its actions at the end
  const count = h("span", { className: "count" });
  const acts = h("span", { className: "acts" });
  const radios = MODES.map(([m, label, glyph]) => {
    const radio = h("input", {
      type: "radio",
      name: "todoview",
      value: m,
      onchange: () => {
        address(m === "now" ? "/todos" : `/todos?view=${m}`); // keeping Back's marks
        draw();
      },
    });
    return h("label", {}, radio, icon(glyph), label);
  });

  function draw() {
    const [m, name] = modeOf();
    for (const l of radios) (l.firstChild as HTMLInputElement).checked = l.textContent === name;
    const day = today();
    const groups: Section<Todo>[] = (
      m === "now" ? now(list, day) : [["", m === "all" ? list : upcoming(list, day)] as const]
    ).map(([label, items]) => ({ label, items }));
    const shown = groups.flatMap((g) => g.items);
    // Now: the done and cancelled ones, folded away at the end, last edited first (a trail of
    // their own: Mark done steps on through the open ones)
    const done = list.filter((p) => !isOpen(p));
    const fold: Section<Todo>[] =
      m === "now" && done.length
        ? [{ label: "Done", items: done, fold: true, trail: "Todos · Done" }]
        : [];
    const lists = drawSections([...groups, ...fold], row, `Todos · ${name}`, "todos");
    const n = shown.length;
    const asleep = list.filter((t) => isOpen(t) && !toDo(t, day)).length;
    count.replaceChildren(
      // none: no count, the empty state says so
      !n
        ? ""
        : [
            `${n} open ${n === 1 ? "todo" : "todos"}`,
            `${n} due in the next 7 days`,
            `${n} ${n === 1 ? "todo" : "todos"}`,
          ][MODES.findIndex(([k]) => k === m)],
    );
    // At the line's end, as the search screen's results header has its actions: Now's snoozed
    // ones, a quiet text button to a search of them (the server's is:snoozed finds open ones
    // only, as here; soonest due first), then Refine, the view in Search with its query filled
    // in, a 48 px ghost icon button
    acts.replaceChildren(
      ...(m === "now" && asleep
        ? [
            h(
              "a",
              {
                className: "button ghost snoozed",
                href: `/search?q=${encodeURIComponent(SNOOZED)}`,
                "aria-label": `${asleep} snoozed: show them`,
              },
              `${asleep} snoozed`,
            ),
          ]
        : []),
      h(
        "a",
        {
          className: "button ghost act",
          href: `/search?q=${encodeURIComponent(AS_SEARCH[m])}`,
          "aria-label": `Refine in Search: ${AS_SEARCH[m]}`,
          title: "Refine in Search",
        },
        icon("filter"),
      ),
    );
    const none = [
      "Nothing to do: every todo is done.",
      "Nothing due in the next 7 days.",
      "No todos yet.",
    ];
    if (!n) lists.splice(groups.length, 0, empty("tick", none[MODES.findIndex(([k]) => k === m)]));
    body.replaceChildren(...lists);
  }
  draw();
  const root = h(
    "section",
    { className: "todos" },
    h("div", { className: "chips kindrow", role: "radiogroup", "aria-label": "Show" }, ...radios),
    h("div", { className: "rhead" }, count, acts),
    body,
  );
  return root;
}
