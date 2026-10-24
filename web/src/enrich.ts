// What Claude added to a text page (#85), under its text: the summary it wrote, the pages it
// found related (merged with pages linking here), its state while it reads, and Ask Claude to
// have it read the page now (a saved link is fetched again). Claude's tags are marked in the
// tag line (page.ts). A chunk of its own: the page view loads it when the page has any of it.
import { ApiError, api, type Page } from "./api";
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

/** The panel, or null when there is nothing to show and Claude is off. */
export function enrichPanel(p: Page, show: (p: Page) => void): HTMLElement | null {
  const e = p.enrich;
  const related = relatedOf(p);
  if (!e?.on && !e?.summary && !related.length) return null;
  const said = e && stateText(e);
  const ask =
    e?.on &&
    h(
      "button",
      {
        type: "button",
        className: "ghost",
        disabled: ["queued", "processing", "paused"].includes(e.state ?? ""),
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
      e.summary || e.state === "done" ? "Ask again" : "Ask Claude",
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
  return h(
    "section",
    { className: "enrich" },
    h(
      "div",
      { className: "row" },
      h("b", {}, "Claude"),
      said && h("span", { className: e?.state === "failed" ? "err" : "" }, said),
      resume,
      ask,
    ),
    e?.summary && h("p", { className: "summary", dir: "auto" }, e.summary),
    related.length > 0 &&
      h(
        "div",
        { className: "related" },
        h("h2", {}, "Related"),
        h(
          "ul",
          {},
          ...related.map((r) =>
            h(
              "li",
              {},
              h("a", { href: `/p/${encodeURIComponent(r.slug)}`, dir: "auto" }, r.title),
              r.via === "link" && h("small", {}, " · links here"),
            ),
          ),
        ),
      ),
  );
}
