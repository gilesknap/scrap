// The Store health screen (#262), opened from Settings: each health check with how many pages
// it finds (GET /api/health, one cheap count each), a tap listing them in Search. Nothing is
// dismissed here: a check that keeps finding a page you're happy with is the check to change.
// A chunk of its own.
import { api } from "./api";
import { CHECKS, checkSearch } from "./checks";
import "./health.css";
import { h } from "./ui";

export interface Check {
  term: string; // as a search takes it: is:orphan, has:dangling...
  count: number;
}

/** A check's row: its name, what it finds, and its count at the end; a link to its search. */
export function checkRow({ term, count }: Check): HTMLLIElement {
  const [, name, about] = CHECKS.find(([t]) => t === term) ?? [term, term, ""];
  return h(
    "li",
    {},
    h(
      "a",
      { href: checkSearch(term), "aria-label": `${name}: ${count}` },
      h("span", {}, h("strong", {}, name), h("small", {}, about)),
      h("b", { className: count ? "n" : "n none" }, String(count)),
    ),
  );
}

export async function health(signal: AbortSignal): Promise<Node> {
  const { checks } = await api<{ checks: Check[] }>("health", { signal });
  return h(
    "section",
    { className: "health" },
    h("h2", { className: "label" }, "Store health"),
    h("p", { className: "hint" }, "Pages that may need a look. Tap a check to see them."),
    h("ul", { className: "list" }, ...checks.map(checkRow)),
    h(
      "p",
      { className: "hint" },
      "Related pages are refreshed each night and topic syntheses each week, while Claude is on. An outdated write-up waits for you to regenerate it.",
    ),
  );
}
