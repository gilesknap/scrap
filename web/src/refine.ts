// Refine a search with a tap (#84): what the pages found have in common (work or personal,
// their kinds, their top tags), each with how many have it; tapping one adds its filter to
// the query, and the query's filters show first, tapped to take them out. The chips only
// edit the query's text (kind:todo, tag:tech, is:personal), so it can be typed too.
// A chunk of its own, loaded with the first search.
import { api } from "./api";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { adding, removing, token } from "./terms";
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

const chip = (label: Node | string, n: number | null, onclick: () => void, on = false) =>
  h(
    "button",
    { type: "button", className: on ? "facet on" : "facet", onclick },
    label,
    n === null ? icon("close") : h("small", {}, String(n)),
  );

/** The chips for a query, or null if it has no results to refine. apply runs a new query. */
export async function refine(
  q: string,
  signal: AbortSignal,
  apply: (q: string) => void,
): Promise<HTMLElement | null> {
  const f = await api<Facets>(`search/facets?q=${encodeURIComponent(q)}`, { signal });
  if (!f.total && !f.active.length) return null;
  const add = (t: string) => () => apply(adding(q, t));
  const chips: HTMLElement[] = f.active.map((a) => {
    const b = chip(a.token, null, () => apply(removing(q, a.token)), true);
    b.setAttribute("aria-label", `Remove ${a.token}`);
    return b;
  });
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
    { className: "refine", role: "group", "aria-label": "Refine" },
    h("span", { className: "count" }, `${f.total} ${f.total === 1 ? "page" : "pages"}`),
    ...chips,
  );
}
