// The page's one Claude card, About this page (#85, #256), under its text: the summary Claude
// wrote (a board's is its write-up's lead), a board's write-up (In detail, writeup.ts), the
// pages it found related (merged with pages linking here), its state while it works, and one
// action: Ask, which reads the page again (a saved link is fetched again) and, on a board,
// writes it up and finds its related pages again too. On a topic (#261) its synthesis is the
// write-up, and its Sources a fold (topic.ts); a source names its topics first. Claude's tags
// are marked in the tag line (page.ts). A chunk of its own: the page view loads it when the
// page has any of it.
import { ApiError, api, kept, type Page } from "./api";
import { icon, kindIcon } from "./icons";
import { sourcesFold, topicsLine } from "./topic";
import { h, toast } from "./ui";
import type { writeupParts } from "./writeup";

/** A board's write-up, as parts of this card (writeup.ts, a chunk of its own). */
type WriteupParts = NonNullable<ReturnType<typeof writeupParts>>;

export type Enrich = NonNullable<Page["enrich"]>;

/** The state line's words: null when there is nothing to say. */
export function stateText(e: Enrich): string | null {
  switch (e.state) {
    case "queued":
      return e.on ? "Waiting for Claude" : "Waiting: Claude is off";
    case "processing":
      return "Claude is reading it…";
    case "paused":
      return `Paused${e.reason ? ` (${e.reason})` : ""}: nothing is lost`;
    case "failed":
      return `Claude couldn't read it${e.error ? `: ${e.error.replace(/^\w+: /, "")}` : ""}`;
    default:
      return null;
  }
}

/** Whether to look again soon: Claude has it queued or is reading it, or the queue is paused
 * (a backoff ends by itself, or Resume is pressed elsewhere). */
export const reading = (p: Page) =>
  !!p.enrich?.on && ["queued", "processing", "paused"].includes(p.enrich.state ?? "");

/** The related pages to list, Claude's picks first, each once (the server merged them); on a
 * topic, not its sources, which its Sources fold lists. */
export const relatedOf = (p: Page) => {
  const sources = new Set(p.topic?.sources.map((s) => s.id));
  return (p.related ?? []).filter((r) => !sources.has(r.id)).slice(0, 8);
};

const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

/** A fold of the card, as a photo's Description is, but open until closed (then remembered
 * closed): what Claude found is short, and what the card is for. */
function fold(label: string, ...body: (Node | string)[]) {
  const key = `scrap.fold.${label}`;
  const head = h("summary", {}, label);
  const el = h("details", { className: "claude-text", open: kept(key) !== "shut" }, head, ...body);
  // Remembered as it is tapped (it is about to change), not on toggle, which comes a task later:
  // a reload or a redraw in between would lose it
  head.onclick = () => kept(key, el.open ? "shut" : null);
  return el;
}

/** Never read: what asking Claude would do. */
export const ASK = "Claude can summarise it, suggest tags and find related pages.";

/** The page's one Claude card, About this page, after its text: Summary, a board's write-up
 * (In detail: wp, its parts) and Related. Null when there is nothing to show and Claude is off.
 * Its title line says where Claude is up to, if anywhere, and its one action, Ask (POST
 * enrich): on a board it writes the write-up again too, so it is named for that. */
export function enrichPanel(
  p: Page,
  show: (p: Page) => void,
  wp: WriteupParts | null = null,
): HTMLElement | null {
  const e = p.enrich;
  const related = relatedOf(p);
  const topics = topicsLine(p); // a source's topics
  const sources = sourcesFold(p, show); // a topic's sources
  if (!wp && !e?.on && !e?.summary && !related.length && !topics && !sources) return null;
  const read = !!e?.summary || e?.state === "done";
  // Waiting, reading or paused: nothing to ask for meanwhile (paused offers Resume instead)
  const busy = ["queued", "processing", "paused"].includes(e?.state ?? "");
  // Never read: no state to show, only what asking would do, then the button under it
  // The title says what the card holds; the pill only where Claude is up to (none once read)
  const said = e && e.state !== "done" ? stateText(e) : null;
  // Named for what there is: a board's write-up, else the page's reading
  const failed = e?.state === "failed" || wp?.state === "failed";
  const made = wp ? wp.written : read;
  const ask =
    e?.on &&
    !busy &&
    !wp?.busy &&
    h(
      "button",
      {
        type: "button",
        className: made && !failed ? "link" : "",
        onclick: async (ev: Event) => {
          const b = ev.currentTarget as HTMLButtonElement;
          b.disabled = true;
          try {
            show(await api<Page>(`pages/${p.id}/enrich`, { method: "POST" }));
          } catch (err) {
            b.disabled = false;
            toast(`Not sent: ${why(err)}`);
          }
        },
      },
      failed ? "Retry" : made ? "Regenerate" : "Generate",
    );
  // The queue is the photos' too: its Resume (api/ingest/resume) ends the pause for both
  const resume =
    e?.state === "paused" &&
    h(
      "button",
      {
        type: "button",
        onclick: async (ev: Event) => {
          const b = ev.currentTarget as HTMLButtonElement;
          b.disabled = true;
          try {
            await api("ingest/resume", { method: "POST" });
            show(await api<Page>(`pages/${p.id}`));
          } catch (err) {
            b.disabled = false;
            toast(`Not resumed: ${why(err)}`);
          }
        },
      },
      "Resume",
    );
  const state = e?.state === "failed" || e?.state === "paused" ? e.state : read ? "done" : "";
  // A board: the write-up's state leads, but a pause is the page's (it says why, and Resume is
  // beside it); a board's Summary is its write-up's lead
  const pill =
    (e?.state !== "paused" && wp?.said && [wp.said, wp.state]) || (said && [said, state]);
  const summary = wp?.lead || e?.summary;
  const action = resume || ask || (!e?.on && wp?.action) || "";
  // Only a source's topics to say, and nothing to do: the line alone, not a card for one line
  if (topics && !wp && !summary && !related.length && !sources && !pill && !action)
    return h(
      "section",
      { className: "enrich topicsonly", "aria-label": "About this page" },
      topics,
    );
  return h(
    "section",
    { className: "enrich claude", "aria-label": "About this page" },
    h(
      "div",
      { className: "ingest" },
      h("h3", { className: "ctitle" }, "About this page"),
      pill && h("span", { className: `state ${pill[1]}`, role: "status" }, pill[0]),
      // (the write-up's own when the page's reading is off; never beside a busy Ask)
      action,
    ),
    // Never read (or, a board, never written): what asking would do (not once it failed: the
    // state line says why, Retry beside it)
    wp
      ? (wp.unwritten ?? wp.stale ?? "")
      : !busy && e?.on && !read && !failed
        ? h("p", { className: "did" }, ASK)
        : "",
    // The topics it is a source of, as a line: "Topics: ibek · RTEMS IOCs". Then its parts as
    // folds: Summary, In detail (a board's write-up or a topic's synthesis, or its guidance
    // before there is one), a topic's Sources and Related
    topics,
    !wp && read && !summary && !related.length && !topics
      ? h("p", { className: "did" }, "Claude found nothing to add.")
      : "",
    summary ? fold("Summary", h("p", { className: "summary", dir: "auto" }, summary)) : "",
    wp?.detail ?? wp?.guidance ?? "",
    sources,
    related.length > 0 &&
      Object.assign(
        fold(
          "Related",
          h(
            "ul",
            {},
            ...related.map((r) =>
              h(
                "li",
                {},
                h(
                  "a",
                  { href: `/p/${encodeURIComponent(r.slug)}`, dir: "auto" },
                  icon(kindIcon(r.kind)),
                  r.title,
                ),
                r.via === "link" && h("small", {}, " · links here"),
                r.via === "writeup" && h("small", {}, " · in a write-up"),
                r.via === "topic" && h("small", {}, " · in a topic"),
              ),
            ),
          ),
        ),
        { className: "claude-text related" },
      ),
  );
}
