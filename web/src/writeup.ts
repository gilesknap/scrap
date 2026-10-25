// Claude's write-up of a board page (#256), under its text: a Claude card of its own, shaped as
// a photo's (a state line, then the write-up as a fold, folded until opened and remembered),
// never the page's text. It says who wrote
// it and when, shows its lead and its Markdown (its [[slug]] links as page links), and offers
// Regenerate, the owner's guidance for the next one, and its versions with Restore. Nobody edits
// it. A chunk of its own: the page view loads it for a page with a write-up or a board.
import { ApiError, api, kept, type Page, type Writeup, type WriteupVersion } from "./api";
import { bodyView, h, toast, whenShort } from "./ui";
import "./writeup.css";

const JSON_TYPE = { "Content-Type": "application/json" };
const FOLD = "scrap.fold.writeup";
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

/** Who wrote a version and when: "claude-opus-5-5 · Oct 25, 10:04 · version 2". */
export const byline = (v: WriteupVersion) =>
  [
    v.producer,
    whenShort(v.created_at),
    `version ${v.version}`,
    v.restored_from && `restored from version ${v.restored_from}`,
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
function action(label: string, run: () => Promise<void>, className = "") {
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

/** The section, or null when there is none to show and none can be written. */
export function writeupPanel(p: Page, show: (p: Page) => void): HTMLElement | null {
  const w = p.writeup;
  if (!w || (!w.current && !(w.board && w.on))) return null;
  const up = w.current;
  const said = stateText(w);
  const busy = ["queued", "processing", "paused"].includes(w.state ?? "");
  // Generate the first time, Regenerate after, Retry when it failed: as every Claude card says
  const regenerate =
    w.on &&
    w.board &&
    !busy &&
    action(
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
  // Shaped as a photo's card: its state line (Written by Claude, then Regenerate), then the
  // write-up itself as a fold like Description, folded until opened (remembered)
  const pill = said ?? (up ? "Written by Claude" : null);
  const state = w.state === "failed" || busy ? w.state : "done";
  const head = h("summary", {}, "Write-up");
  const fold =
    up &&
    h(
      "details",
      { className: "claude-text", open: kept(FOLD) === "open" },
      head,
      h(
        "div",
        { className: "card" },
        h("p", { className: "by" }, byline(up)),
        h("p", { className: "summary", dir: "auto" }, up.summary),
        pageLinksOnly(bodyView(up.text, false), up.links ?? []),
        guidanceFold(p, w, show),
        w.versions > 1 ? versionsFold(p, up, show) : "",
      ),
    );
  // Remembered as it is tapped, not on toggle (which comes a task later): the page may be
  // drawn again in between, from what was remembered
  if (fold) head.onclick = () => kept(FOLD, fold.open ? null : "open"); // (about to change)
  return h(
    "section",
    { className: "writeup claude", "aria-label": "Claude's write-up" },
    pill
      ? h(
          "div",
          { className: "ingest" },
          h("span", { className: `state ${state}`, role: "status" }, pill),
          regenerate,
        )
      : h(
          "p",
          { className: "did" },
          "Claude can write up what this board shows: its parts and how they connect.",
        ),
    !pill && regenerate ? h("div", { className: "ask" }, regenerate) : "",
    fold || (w.board ? guidanceFold(p, w, show) : ""),
  );
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
  const save = action(
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
              : action(
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
