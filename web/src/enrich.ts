// What Claude added to a text page (#85), under its text: the summary it wrote, the pages it
// found related (merged with pages linking here), its state while it reads, and Ask Claude to
// have it read the page now (a saved link is fetched again). Claude's tags are marked in the
// tag line (page.ts). A chunk of its own: the page view loads it when the page has any of it.
import { ApiError, api, kept, type Page } from "./api";
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

/** The related pages to list, Claude's picks first, each once (the server merged them). */
export const relatedOf = (p: Page) => (p.related ?? []).slice(0, 8);

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

/** The page's one Claude card, About this page, at its end: Summary, a board's write-up (In
 * detail: wp, its parts) and Related. Null when there is nothing to show and Claude is off. Its
 * title line says where Claude is up to, if anywhere, and its one action: on a board the
 * write-up's (writing it again reads the page again), else reading the page. */
export function enrichPanel(
  p: Page,
  show: (p: Page) => void,
  wp: WriteupParts | null = null,
): HTMLElement | null {
  const e = p.enrich;
  const related = relatedOf(p);
  if (!wp && !e?.on && !e?.summary && !related.length) return null;
  const read = !!e?.summary || e?.state === "done";
  // Waiting, reading or paused: nothing to ask for meanwhile (paused offers Resume instead)
  const busy = ["queued", "processing", "paused"].includes(e?.state ?? "");
  // Never read: no state to show, only what asking would do, then the button under it
  // The title says what the card holds; the pill only where Claude is up to (none once read)
  const said = e && e.state !== "done" ? stateText(e) : null;
  const ask =
    e?.on &&
    !busy &&
    h(
      "button",
      {
        type: "button",
        className: read && e.state !== "failed" ? "link" : "",
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
      e.state === "failed" ? "Retry" : read ? "Regenerate" : "Generate",
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
  // A board: the write-up's state and action lead (the page's own as a fallback)
  const pill = (wp?.said && [wp.said, wp.state]) || (said && [said, state]);
  const summary = e?.summary || wp?.lead;
  return h(
    "section",
    { className: "enrich claude", "aria-label": "About this page" },
    h(
      "div",
      { className: "ingest" },
      h("h3", { className: "ctitle" }, "About this page"),
      pill && h("span", { className: `state ${pill[1]}`, role: "status" }, pill[0]),
      resume || (wp ? wp.action : ask) || "",
    ),
    // Never read (or, a board, never written): what asking would do. Then its parts as folds:
    // Summary (a board's is its write-up's lead), In detail (a board's write-up) and Related
    ...(wp
      ? (wp.unwritten ?? [])
      : [
          !busy && e?.on && !read ? h("p", { className: "did" }, ASK) : "",
          read && !summary && !related.length
            ? h("p", { className: "did" }, "Claude found nothing to add.")
            : "",
        ]),
    summary ? fold("Summary", h("p", { className: "summary", dir: "auto" }, summary)) : "",
    wp?.detail ?? "",
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
                h("a", { href: `/p/${encodeURIComponent(r.slug)}`, dir: "auto" }, r.title),
                r.via === "link" && h("small", {}, " · links here"),
                r.via === "writeup" && h("small", {}, " · in a write-up"),
              ),
            ),
          ),
        ),
        { className: "claude-text related" },
      ),
  );
}
