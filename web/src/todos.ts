// The Todos screen: what to do now, first (now.ts ranks it). A switch on top picks the list:
// Now (open todos: overdue, today, high priority with no date, then the rest; done ones
// folded away at the end), Upcoming (due from tomorrow to a week away) or All (last edited first). The address
// says which (/todos, /todos?view=upcoming, /todos?view=all), so Back and a reload come back
// to it. Rows are the search screen's: tick, swipe, a pager through the list. A lazy chunk.
import { api, type Hit } from "./api";
import { view } from "./app";
import { icon } from "./icons";
import type { pageRow } from "./lists";
import { isOpen, now, toDo, upcoming } from "./now";
import { today } from "./status";
import { swipeRows, trail } from "./swipe";
import { empty, h, problem, toast } from "./ui";

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
  let list: Todo[];
  try {
    list = await fetchAll();
  } catch (e) {
    return problem(e);
  }
  // A todo saved meanwhile (New todo, below): the list again once its upload is done. Each
  // change asks again; only the newest answer is drawn (an older one may land last)
  let asked = 0;
  document.addEventListener(
    "queuechange",
    async () => {
      const mine = ++asked;
      try {
        const got = await fetchAll();
        if (mine !== asked) return; // a newer ask is on its way
        list = got;
        draw();
      } catch {} // offline, or the server unreachable: the list as it was
    },
    { signal },
  );
  const keep = () => history.replaceState({ ...history.state, scroll: scrollY }, "");
  const body = h("div");
  const count = h("p", { className: "count" });
  const radios = MODES.map(([m, label, glyph]) => {
    const radio = h("input", {
      type: "radio",
      name: "todoview",
      value: m,
      onchange: () => {
        history.replaceState(null, "", m === "now" ? "/todos" : `/todos?view=${m}`);
        draw();
      },
    });
    return h("label", {}, radio, icon(glyph), label);
  });

  function draw() {
    const [m, name] = modeOf();
    body.dataset.view = m; // Now and Upcoming leave out when each was edited: All keeps it
    for (const l of radios) (l.firstChild as HTMLInputElement).checked = l.textContent === name;
    const day = today();
    const groups: [string, Todo[]][] =
      m === "now" ? now(list, day) : [["", m === "all" ? list : upcoming(list, day)]];
    const shown = groups.flatMap(([, ts]) => ts);
    const slugs = shown.map((p) => p.slug);
    const lists = groups.map(([label, ts]) => {
      const ul = trail(
        h("ul", { className: "list" }, ...ts.map((p) => row(p))),
        `Todos · ${name}`,
        slugs,
      );
      swipeRows(ts.map((p, i) => [ul.children[i], p]));
      if (!label) return ul;
      const id = `todos-${label.split(" ")[0].toLowerCase()}`;
      return h(
        "section",
        { "aria-labelledby": id },
        h("h2", { className: "label", id }, `${label} · ${ts.length}`),
        ul,
      );
    });
    const n = shown.length;
    const asleep = list.filter((t) => isOpen(t) && !toDo(t, day)).length;
    count.textContent = [
      `${n} open ${n === 1 ? "todo" : "todos"}${asleep ? ` · ${asleep} snoozed (in All)` : ""}`,
      `${n} due in the next 7 days`,
      `${n} ${n === 1 ? "todo" : "todos"}`,
    ][MODES.findIndex(([k]) => k === m)];
    const none = [
      "Nothing to do: every todo is done.",
      "Nothing due in the next 7 days.",
      "No todos yet.",
    ];
    if (!n) lists.push(empty("todo", none[MODES.findIndex(([k]) => k === m)]));
    // Now: the done and cancelled ones, folded away at the end, last edited first
    const done = list.filter((p) => !isOpen(p));
    if (m === "now" && done.length) {
      const ul = trail(
        h("ul", { className: "list" }, ...done.map((p) => row(p))),
        "Todos · Done",
        done.map((p) => p.slug),
      );
      swipeRows(done.map((p, i) => [ul.children[i], p]));
      lists.push(
        h("details", { className: "donefold" }, h("summary", {}, `Done · ${done.length}`), ul),
      );
    }
    body.replaceChildren(...lists);
  }
  draw();
  const y = history.state?.scroll;
  if (y) requestAnimationFrame(() => scrollTo(0, y));
  // New todo: the composer with Todo chosen; saved, it closes back onto this list
  const add = h(
    "button",
    {
      type: "button",
      className: "primary newtodo",
      onclick: () =>
        import("./composer").then(
          (m) => m.compose([], "todo"),
          () => toast("Can't open the composer: reload scrap and try again"),
        ),
    },
    icon("add"),
    "New todo",
  );
  const root = h(
    "section",
    { className: "todos" },
    h("div", { className: "chips kindrow", role: "radiogroup", "aria-label": "Show" }, ...radios),
    count,
    body,
    add,
  );
  // Leaving by a tap or a swipe: where the list is, for Back
  root.addEventListener("pointerdown", keep, { capture: true });
  return root;
}
