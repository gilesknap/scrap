// Claude's topic pages (#261) in the page's one Claude card, About this page (enrich.ts): on a
// topic, its Sources (each with a ✕ that takes it out, and Put back for one taken out); on a
// source, the line naming its topics. The synthesis itself is the topic's write-up
// (writeup.ts). Loaded with the enrich chunk.
import { ApiError, api, kept, type Page, type Source } from "./api";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { h, toast } from "./ui";
import "./topic.css";

const OFFLINE = "Offline: changing a topic's sources needs the server";
/** The ✕ and Put back buttons on screen: off while offline, with a tooltip saying why (as a
 * page's task boxes are). */
function online() {
  for (const b of document.querySelectorAll<HTMLButtonElement>(".enrich .sources li > button")) {
    b.disabled = !navigator.onLine;
    b.title = navigator.onLine ? (b.dataset.title ?? "") : OFFLINE;
  }
}
globalThis.addEventListener?.("online", online); // (none in the unit tests)
globalThis.addEventListener?.("offline", online);

const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");
const href = (slug: string) => `/p/${encodeURIComponent(slug)}`;

/** A source's kind in a word, as the kind chips say it: "Note", "Later", "Board". */
export function kindWord(kind: string): string {
  const named = KINDS.find(([k]) => k === kind)?.[1];
  return named ?? kind.charAt(0).toUpperCase() + kind.slice(1);
}

/** The sources in, then those the owner took out. */
export function ordered(sources: Source[]): Source[] {
  return [...sources.filter((s) => !s.excluded), ...sources.filter((s) => s.excluded)];
}

/** The topics a page is a source of, a line each (the topic's icon, its title a link), for its
 * card's Topics fold, drawn as Related is; null on a page in none. */
export function topicsList(p: Page): HTMLElement | null {
  const topics = p.topics ?? [];
  if (!topics.length) return null;
  return h(
    "ul",
    {},
    ...topics.map((t) =>
      h("li", {}, h("a", { href: href(t.slug), dir: "auto" }, icon("topic"), t.title)),
    ),
  );
}

/** Take a source out (the ✕) or put it back: the topic page as it is then, shown; taken out,
 * a toast with Undo. */
async function change(p: Page, s: Source, back: boolean, show: (p: Page) => void) {
  const path = `pages/${p.id}/topic/sources/${s.id}`;
  try {
    show(await api<Page>(path, { method: back ? "POST" : "DELETE" }));
  } catch (err) {
    return toast(`${back ? "Not put back" : "Not taken out"}: ${why(err)}`);
  }
  // Drawn again: focus back on that source's button (now Put back, or the ✕ again)
  document.querySelector<HTMLElement>(`.enrich .sources li[data-id="${s.id}"] > button`)?.focus();
  if (!back) toast(`Taken out: ${s.title}`, "Undo", () => void change(p, s, true, show), 6000);
  else toast(`Put back: ${s.title}`);
}

/** A topic's Sources, a fold of its card, open until closed: each source's title (a link)
 * and kind, with a ✕ that takes it out of the synthesis; one taken out stays, marked, with
 * Put back. Null on a page that is not a topic. */
export function sourcesFold(p: Page, show: (p: Page) => void): HTMLElement | null {
  if (!p.topic) return null;
  const all = ordered(p.topic.sources);
  const n = all.filter((s) => !s.excluded).length;
  const rows = all.map((s) => {
    const out = !!s.excluded;
    const b = h(
      "button",
      {
        type: "button",
        className: out ? "link" : "ghost drop",
        "aria-label": out ? `Put back ${s.title}` : `Take out ${s.title}`,
        "data-title": out ? "Put it back into this topic" : "Take it out of this topic",
        disabled: !navigator.onLine,
      },
      out ? "Put back" : icon("close"),
    );
    b.title = navigator.onLine ? (b.dataset.title ?? "") : OFFLINE;
    b.onclick = () => {
      b.disabled = true;
      void change(p, s, out, show).finally(() => (b.disabled = !navigator.onLine));
    };
    return h(
      "li",
      { className: out ? "out" : "", "data-id": s.id },
      h(
        "span",
        {},
        h("a", { href: href(s.slug), dir: "auto" }, s.title),
        h("small", {}, ` · ${kindWord(s.kind)}${out ? " · taken out" : ""}`),
      ),
      b,
    );
  });
  const key = "scrap.fold.Sources";
  const head = h("summary", {}, `Sources · ${n}`);
  const el = h(
    "details",
    { className: "claude-text sources", open: kept(key) !== "shut" },
    head,
    rows.length
      ? h("ul", {}, ...rows)
      : h("p", { className: "did" }, "None: Claude finds them in the weekly topics pass."),
  );
  head.onclick = () => kept(key, el.open ? "shut" : null); // (about to change)
  return el;
}
