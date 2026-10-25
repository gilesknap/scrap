// What Claude added to a text page (#85), under its text: the summary it wrote, the pages it
// found related (merged with pages linking here), its state while it reads, and Ask Claude to
// have it read the page now (a saved link is fetched again). Claude's tags are marked in the
// tag line (page.ts). A chunk of its own: the page view loads it when the page has any of it.
import { ApiError, api, kept, type Page } from "./api";
import { h, toast } from "./ui";

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
  const el = h(
    "details",
    { className: "claude-text", open: kept(key) !== "shut" },
    h("summary", {}, label),
    ...body,
  );
  el.ontoggle = () => kept(key, el.open ? null : "shut");
  return el;
}

/** Never read: what asking Claude would do. */
export const ASK = "Claude can summarise it, suggest tags and find related pages.";

/** The panel, or null when there is nothing to show and Claude is off. Its row says it as a
 * photo's does: Read by Claude (or where it is up to), then Regenerate. */
export function enrichPanel(p: Page, show: (p: Page) => void): HTMLElement | null {
  const e = p.enrich;
  const related = relatedOf(p);
  if (!e?.on && !e?.summary && !related.length) return null;
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
  return h(
    "section",
    { className: "enrich claude" },
    h(
      "div",
      { className: "ingest" },
      h("h3", { className: "ctitle" }, "About this page"),
      said && h("span", { className: `state ${state}`, role: "status" }, said),
      resume || ask,
    ),
    // Never read: what asking would do. Read: its parts under headings, Summary (a board has
    // none: its write-up says what it shows) and Related
    !busy && e?.on && !read ? h("p", { className: "did" }, ASK) : "",
    read && !e?.summary && !related.length
      ? h("p", { className: "did" }, "Claude found nothing to add.")
      : "",
    e?.summary ? fold("Summary", h("p", { className: "summary", dir: "auto" }, e.summary)) : "",
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
