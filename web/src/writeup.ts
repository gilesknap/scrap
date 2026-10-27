// Claude's write-up of a board page (#256), or a topic's synthesis (#261): its parts for the page's one Claude card, About
// this page (enrich.ts): where Claude is up to, the lead (the card's Summary) and the write-up
// itself as a fold, In detail, with who wrote it and when, its Markdown (its [[slug]] links as
// page links), the owner's guidance for the next one and its versions with Restore. Nobody
// edits it. A chunk of its own: the page view loads it for a page with a write-up or a board.
import { ApiError, api, kept, type Page, type Writeup, type WriteupVersion } from "./api";
import { bodyView, h, toast, whenShort } from "./ui";
import "./writeup.css";

const JSON_TYPE = { "Content-Type": "application/json" };
const FOLD = "scrap.fold.writeup";
const TOPIC_FOLD = "scrap.fold.synthesis";
/** Guidance being typed, by page: kept, with its fold open, when the page is drawn again. */
const typing = new Map<string, string>();
const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

/** Whether to look again soon: one is waiting, being written, or paused. */
export const writing = (p: Page) =>
  !!p.writeup?.on && ["queued", "processing", "paused"].includes(p.writeup.state ?? "");

/** The state line's words: null when there is nothing to say. */
export function stateText(w: Writeup): string | null {
  switch (w.state) {
    case "queued":
      return w.on ? "Waiting for Claude" : "Waiting: Claude is off";
    case "processing":
      return "Claude is writing it…";
    case "paused":
      return "Paused: nothing is lost";
    case "failed":
      return `Claude couldn't write it${w.error ? `: ${w.error.replace(/^\w+: /, "")}` : ""}`;
    default:
      return null;
  }
}

/** The quiet line under the card's title when the current write-up is outdated (the page's
 * text, title or tags, a board photo or Claude's prompt changed since): Regenerate, beside it,
 * makes it again. Nothing regenerates it on its own but a newly read photo. */
export const OUTDATED =
  "The page, a page it links to, or Claude's prompt has changed since this write-up.";
export const outdatedLine = (w: Writeup) =>
  w.outdated && w.current && !["queued", "processing", "paused"].includes(w.state ?? "")
    ? OUTDATED
    : null;

/** Who wrote a version and when: "Claude · 25 Oct, 10:04 · v2" (the model by name in the
 * line's tooltip). */
export const byline = (v: WriteupVersion) =>
  [
    /^claude/i.test(v.producer) ? "Claude" : v.producer,
    whenShort(v.created_at),
    `v${v.version}`,
    v.restored_from && `restored from v${v.restored_from}`,
  ]
    .filter(Boolean)
    .join(" · ");

/** A write-up's text with no link but to the pages the server says it links (that exist):
 * the server keeps only its [[slug]] links, and anything else that renders as one (linkify,
 * a page not there) is shown as its words. */
export function pageLinksOnly(el: HTMLElement, slugs: string[]): HTMLElement {
  const ok = new Set(slugs.map((s) => `/p/${s}`));
  for (const a of el.querySelectorAll("a"))
    if (!ok.has(a.getAttribute("href") ?? "")) a.replaceWith(...a.childNodes);
  return el;
}

/** A button that does one thing, disabled while it does it. */
function act(label: string, run: () => Promise<void>, className = "") {
  const b = h("button", { type: "button", className }, label);
  b.onclick = async () => {
    b.disabled = true;
    try {
      await run();
    } finally {
      b.disabled = false;
    }
  };
  return b;
}

/** A board's write-up, as parts of the page's one Claude card (About this page, enrich.ts):
 * where Claude is up to, its action, its lead (the board's Summary) and the write-up itself as
 * a fold, In detail. Null when there is none to show and none can be written. */
export function writeupParts(p: Page, show: (p: Page) => void) {
  const w = p.writeup;
  const can = !!w && (w.board || !!w.topic); // one can be written: a board, or a topic
  if (!w || (!w.current && !(can && w.on))) return null;
  const up = w.current;
  const busy = ["queued", "processing", "paused"].includes(w.state ?? "");
  // Generate the first time, Regenerate after, Retry when it failed: the card's action only when
  // the page's own (Ask, enrich.ts) is not there, Claude being off for it
  const action =
    w.on &&
    can &&
    !busy &&
    act(
      w.state === "failed" ? "Retry" : up ? "Regenerate" : "Generate",
      async () => {
        try {
          show(await api<Page>(`pages/${p.id}/writeup`, { method: "POST" }));
        } catch (err) {
          toast(`Not sent: ${why(err)}`);
        }
      },
      up && w.state !== "failed" ? "link" : "",
    );
  const head = h("summary", {}, "In detail");
  // A board's is folded until opened; a topic's synthesis is what the page is for, so it is
  // open until closed. Each remembered on the phone
  const key = w.topic ? TOPIC_FOLD : FOLD;
  const open = w.topic ? kept(key) !== "shut" : kept(key) === "open";
  const detail =
    up &&
    h(
      "details",
      { className: "claude-text writeup", open },
      head,
      h(
        "div",
        { className: "card" },
        h("p", { className: "by", title: up.producer }, byline(up)),
        pageLinksOnly(bodyView(up.text, false), up.links ?? []),
        guidanceFold(p, w, show),
        w.versions > 1 ? versionsFold(p, up, show) : "",
      ),
    );
  // Remembered as it is tapped, not on toggle (which comes a task later): the page may be
  // drawn again in between, from what was remembered
  if (detail)
    head.onclick = () =>
      w.topic ? kept(key, detail.open ? "shut" : null) : kept(key, detail.open ? null : "open"); // (about to change)
  const stale = outdatedLine(w);
  return {
    said: stateText(w), // where Claude is up to: null when there is nothing to say
    state: w.state ?? "",
    busy,
    written: !!up,
    action: action || null,
    lead: up?.summary ?? null, // the board's summary
    detail: detail || null,
    // Outdated: a quiet line under the title, Regenerate on the title line
    stale: stale && h("p", { className: "did stale" }, stale),
    // None yet: what Claude would do, and the guidance it would follow (after Summary)
    unwritten:
      !up && !busy
        ? h(
            "p",
            { className: "did" },
            w.topic
              ? "Claude can draw this topic's sources together: an overview, key facts with their sources, and open questions."
              : "Claude can describe this board in detail: its parts and how they connect.",
          )
        : null,
    guidance:
      !up && can
        ? Object.assign(guidanceFold(p, w, show), { className: "claude-text sub writeup" })
        : null,
  };
}

/** The owner's guidance for the next write-up: a note, kept apart from the text. */
function guidanceFold(p: Page, w: Writeup, show: (p: Page) => void) {
  const box = h("textarea", {
    rows: 3,
    maxLength: 2000,
    value: typing.get(p.id) ?? w.guidance ?? "",
    placeholder: "e.g. focus on the data flow; 'Enc' means encoder",
    "aria-label": "Guidance for Claude",
    oninput: () => typing.set(p.id, box.value),
  });
  const save = act(
    "Save",
    async () => {
      try {
        const next = await api<Page>(`pages/${p.id}/writeup/guidance`, {
          method: "PUT",
          headers: JSON_TYPE,
          body: JSON.stringify({ guidance: box.value }),
        });
        typing.delete(p.id);
        show(next);
        toast(box.value.trim() ? "Saved: the next write-up follows it" : "Guidance removed");
      } catch (err) {
        toast(`Not saved: ${why(err)}`);
      }
    },
    "primary",
  );
  return h(
    "details",
    { className: "claude-text sub", open: typing.has(p.id) },
    h("summary", {}, w.guidance ? "Guidance for Claude (set)" : "Guidance for Claude"),
    h("p", { className: "by" }, "Used by the next write-up, and kept with it."),
    box,
    h("div", { className: "row" }, save),
  );
}

/** Every version, newest first, loaded when opened; an old one can be made current again. */
function versionsFold(p: Page, up: WriteupVersion, show: (p: Page) => void) {
  const list = h("ol", { className: "versions" });
  const fold = h("details", { className: "claude-text sub" }, h("summary", {}, "Versions"), list);
  fold.ontoggle = async () => {
    if (!fold.open || list.childElementCount) return;
    try {
      const all = await api<WriteupVersion[]>(`pages/${p.id}/writeup/versions`);
      list.replaceChildren(
        ...all.map((v) =>
          h(
            "li",
            {},
            h("span", {}, byline(v)),
            v.current
              ? h("em", {}, "current")
              : act(
                  "Restore",
                  async () => {
                    try {
                      show(
                        await api<Page>(`pages/${p.id}/writeup/restore`, {
                          method: "POST",
                          headers: JSON_TYPE,
                          body: JSON.stringify({ version: v.version, base_version: up.version }),
                        }),
                      );
                      toast(`Version ${v.version} restored`);
                    } catch (err) {
                      toast(`Not restored: ${why(err)}`);
                    }
                  },
                  "link",
                ),
            v.summary && h("small", { dir: "auto" }, v.summary),
          ),
        ),
      );
    } catch (err) {
      toast(`Can't list them: ${why(err)}`);
      fold.open = false;
    }
  };
  return fold;
}
