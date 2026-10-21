// The Todos screen: what to do now, first (now.ts ranks it). A switch on top picks the list:
// Now (open todos: overdue, today, high priority with no date, then the rest; done ones
// folded away at the end), Upcoming (due from tomorrow to a week away) or All (last edited first). The address
// says which (/todos, /todos?view=upcoming, /todos?view=all), so Back and a reload come back
// to it. Rows are the search screen's: tick, swipe, a pager through the list. A lazy chunk.
import { api, type Summary } from "./api";
import { view } from "./app";
import { icon } from "./icons";
import type { pageRow } from "./lists";
import { isOpen, now, upcoming } from "./now";
import { today } from "./status";
import { swipeRows, trail } from "./swipe";
import { empty, h, problem, toast } from "./ui";

const MODES = [
  ["now", "Now"],
  ["upcoming", "Upcoming"],
  ["all", "All"],
] as const;
const LIMIT = 500; // the API's most: every todo, for one person's store

const modeOf = () => {
  const v = new URLSearchParams(location.search).get("view");
  return MODES.find(([m]) => m === v) ?? MODES[0];
};

/** row: lists.ts's pageRow, passed in (main.ts) so this chunk imports nothing from lists.ts:
 * that would split the app shell into more, less compressible chunks. */
export async function todos(row: typeof pageRow): Promise<Node> {
  const signal = view.signal;
  const fetchAll = () => {
    if (!navigator.onLine) throw new TypeError("offline");
    return api<Summary[]>(`pages?limit=${LIMIT}&kind=todo`, { signal });
  };
  let list: Summary[];
  try {
    list = await fetchAll();
  } catch (e) {
    return problem(e);
  }
  // A todo saved meanwhile (New todo, below): the list again once the upload is done
  document.addEventListener(
    "queuechange",
    async () => {
      try {
        list = await fetchAll();
        draw();
      } catch {} // offline: as it was
    },
    { signal },
  );
  const keep = () => history.replaceState({ ...history.state, scroll: scrollY }, "");
  const body = h("div");
  const count = h("p", { className: "count" });
  const radios = MODES.map(([m, label]) => {
    const radio = h("input", {
      type: "radio",
      name: "todoview",
      value: m,
      onchange: () => {
        history.replaceState(null, "", m === "now" ? "/todos" : `/todos?view=${m}`);
        draw();
      },
    });
    return h("label", {}, radio, label);
  });

  function draw() {
    const [m, name] = modeOf();
    for (const l of radios) (l.firstChild as HTMLInputElement).checked = l.textContent === name;
    const day = today();
    const groups: [string, Summary[]][] =
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
    count.textContent = [
      `${n} open ${n === 1 ? "todo" : "todos"}`,
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
    icon("todo"),
    "New todo",
  );
  const root = h(
    "section",
    { className: "todos" },
    h("div", { className: "chips kindrow", role: "radiogroup", "aria-label": "Show" }, ...radios),
    count,
    body,
    h(
      "a",
      { className: "button ghost more", href: `/search?q=${encodeURIComponent("kind:todo")}` },
      "Search todos",
    ),
    add,
  );
  // Leaving by a tap or a swipe: where the list is, for Back
  root.addEventListener("pointerdown", keep, { capture: true });
  return root;
}
