// One page: its text (its images as figures) and other files, edit (pageedit.ts, with conflict handling)
// and delete with undo.
import { ADDED, api, blobUrl, type Page, type Queue, setStatus } from "./api";
import { go, plain } from "./app";
import { remember } from "./crumbs";
import { drafts } from "./db";
import type { Trail } from "./gesture";
import { icon } from "./icons";
import { rendered, renderer } from "./md";
import { chipRow, globe, headLines } from "./pagehead";
import { download, share } from "./sharebuttons";
import { unembedded } from "./sharetext";
import { statusOf, ticks } from "./status";
import { deletePage, why } from "./swipe";
import { seenTopic } from "./topicseen";
import { bodyView, h, pageHref, pageLink, toast } from "./ui";

const POLL = 10_000; // while Claude has a photo of this page

/** The page's images as figures, with what Claude made of them: a chunk of its own. */
type Figures = typeof import("./figure");
/** What Claude added to its text (summary, related pages): a chunk of its own. */
type Enrich = typeof import("./enrich");
/** Claude's write-up of a board page: a chunk of its own. */
type Writeups = typeof import("./writeup");
const hasFiles = (p: Page) =>
  p.captures.some((c) => c.blobs.length) || p.body.includes("](/api/blobs/");
/** Without that chunk (offline): its files as links, the text's images as they are. */
const links = (p: Page) =>
  p.captures.flatMap((c) =>
    c.blobs.map((f) => {
      const href = blobUrl(f.sha256);
      const name = h("span", {}, f.filename || f.mime);
      return h("a", { href, target: "_blank", className: "file" }, icon("file"), name);
    }),
  );

/** In Android's home-screen app (as installed from Chrome), not a browser tab. */
const android = () =>
  /Android/.test(navigator.userAgent) && matchMedia("(display-mode: standalone)").matches;

const busy = (p: Page) =>
  p.captures.some((c) =>
    c.blobs.some((b) => b.ingest && ["queued", "processing"].includes(b.ingest.state)),
  );
const ingestOf = (p: Page) => JSON.stringify(p.captures.map((c) => c.blobs.map((b) => b.ingest)));

/** The text as the page shows it: its first line left blank when it only says the title
 * again (a short todo's text, or a "# Heading" that became the title), so it isn't said
 * twice. Blank, not cut: task boxes are found by their line (tasks.ts), so lines keep their
 * numbers. */
export function untitled(body: string, title: string): string {
  const end = body.indexOf("\n");
  const first = end < 0 ? body : body.slice(0, end);
  if (/^(?: {4}|\t)/.test(first)) return body; // indented code, not a title's line
  const said = first.replace(/^ {0,3}#{1,6}(?:[ \t]+|$)/, "").trim();
  return said && said === title.trim() ? body.slice(first.length) : body;
}

/** The page each view was last drawn with, by its article: what a public page is published
 * from (publicpages.ts), on the screen or off it. */
export const pages = new WeakMap<Element, Page>();

/** A page's view and what it shows, for publicpages.ts: show() draws it again. */
export interface View {
  root: HTMLElement;
  shown: () => Page;
  show: (p: Page) => void;
}
/** What publicpages.ts does, a chunk of its own, loaded when it is first needed. */
const publics = () => import("./publicpages");
/** Whether publishing is on on the server (/healthz), asked once: off, no Make public. */
let publishOn: Promise<boolean> | null = null;
const publishing = () =>
  (publishOn ??= fetch("/healthz")
    .then((r) => r.json())
    .then((j) => j?.publish?.enabled !== false)
    .catch(() => {
      publishOn = null; // asked again by the next view
      return true; // offline or unreadable: as if on (publishing says why not when tried)
    }));

/** A page's view. quiet: drawn off the screen, to publish it (publicpages.ts): not opened,
 * no history, no polling, nothing told to the server or kept as seen. */
export async function page(key: string, signal: AbortSignal, quiet = false): Promise<Node> {
  // signal: this view's, taken before any wait (even the chunk's): Back may come meanwhile
  const state = quiet
    ? null
    : (history.state as { trail?: Trail; edit?: boolean; from?: 1 | -1 } | null);
  // The renderer, a chunk of its own, while the page is fetched (offline without it: as typed)
  // and Share's Pin to Search (pins.ts, a chunk of its own; none offline before it was kept)
  const [p, pinRow, , canPublish] = await Promise.all([
    api<Page>(`pages/${encodeURIComponent(key)}`, { signal }),
    import("./pins").then(
      (m) => ({ slug: m.SLUG, make: (p: Page) => m.pinPageButton(p.slug, p.title) }),
      () => null,
    ),
    renderer(),
    publishing(),
  ]);
  signal.throwIfAborted(); // gone meanwhile (Back, or timed out): no poll or listeners
  // Tell the server this page is the one open (MCP current_page, #452); no reply awaited,
  // and offline or refused is no matter
  if (!quiet)
    fetch(`/api/pages/${encodeURIComponent(p.id)}/viewed`, { method: "POST" }).catch(() => {});
  const root = h("article", { className: "page" });
  // A file opens in a new window, but in Android's home-screen app that window has no Back to
  // this page: the back gesture closed the app (#443). There it opens in this window, one step
  // Back returns from. Elsewhere (a tab, a computer, an iPhone) the new window is right.
  root.addEventListener(
    "click",
    (e) => {
      const a = (e.target as Element).closest<HTMLAnchorElement>('a[target][href^="/api/blobs/"]');
      if (a && plain(e) && !a.hasAttribute("download") && android()) {
        e.preventDefault();
        location.assign(a.href);
      }
    },
    { signal },
  );
  // Opened from a list: its pager, swipes and keys (a chunk of its own; none offline)
  const pager = state?.trail
    ? (await import("./pager").catch(() => null))?.pager(state, p.slug, root, signal)
    : null;
  // In the top bar, beside Back (main.ts empties it when the view changes)
  if (pager && !signal.aborted) document.getElementById("pos")?.replaceChildren(pager);
  let shown = p;
  let queue: Queue | null = null;
  let poll = 0;
  signal.addEventListener("abort", () => clearTimeout(poll));
  // Fetch the page again and show it if what Claude did changed (a new state or drawing)
  let drawn = 0; // how many times the page has been drawn
  const refresh = async (force = true) => {
    clearTimeout(poll);
    const was = drawn;
    try {
      const [fresh, q] = await Promise.all([
        api<Page>(`pages/${p.id}`),
        api<Queue>("ingest").catch(() => queue),
      ]);
      await load(fresh);
      // A poll that a save or tick has drawn over meanwhile is stale: not drawn over it
      if (signal.aborted || (!force && drawn !== was)) return;
      const changed =
        ingestOf(fresh) !== ingestOf(shown) ||
        q?.paused !== queue?.paused ||
        JSON.stringify([fresh.enrich, fresh.writeup, fresh.tags, fresh.title, fresh.kind]) !==
          JSON.stringify([shown.enrich, shown.writeup, shown.tags, shown.title, shown.kind]);
      queue = q;
      if (force || changed) show(fresh);
      else schedule(fresh);
    } catch {
      if (!signal.aborted) schedule(shown); // offline for now: try again later
    }
  };
  // Photos added to it (an older build's Add photo, still queued on the phone): shown, and read
  const added = (e: Event) => (e as CustomEvent<Page>).detail.id === p.id;
  addEventListener(ADDED, (e) => added(e) && void refresh(), { signal });
  const schedule = (p: Page) => {
    clearTimeout(poll);
    if (quiet) return;
    const photos = busy(p) && queue?.enabled && !queue.paused;
    if ((photos || enr?.reading(p) || wr?.writing(p)) && !signal.aborted) {
      poll = window.setTimeout(() => {
        if (document.visibilityState === "visible") void refresh(false);
        else schedule(p);
      }, POLL);
    }
  };
  // Figures are a chunk of its own, loaded for pages with files or images
  let figs: Figures | null = null;
  let enr: Enrich | null = null;
  let wr: Writeups | null = null;
  const load = async (p: Page) => {
    // offline: none of it
    if (!enr && (p.enrich || p.related?.length || p.writeup || p.topics?.length || p.topic))
      enr = await import("./enrich").catch(() => null);
    if (!wr && p.writeup) wr = await import("./writeup").catch(() => null);
    if (!hasFiles(p) || figs) return;
    [figs, queue] = await Promise.all([
      import("./figure").catch(() => null), // offline: the photos still show
      api<Queue>("ingest").catch(() => queue),
    ]);
  };
  await load(p);
  const show = (p: Page) => {
    shown = p;
    drawn++;
    pages.set(root, p);
    // For the top bar's Back: a todo's parent is the Todos screen, a topic's the Topics screen
    root.dataset.kind = p.topic ? "topic" : p.kind;
    // Its name as shown, for Back on the pages its links open (crumbs.ts): renamed in place too
    if (!signal.aborted && !quiet) remember(p.title);
    // A topic shown, however it was reached: its dot on the Topics screen has done its job
    if (p.topic && !quiet) seenTopic(p.id, p.writeup?.current?.created_at ?? p.updated_at);
    schedule(p);
    const body = bodyView(untitled(p.body, p.title), false, p.titles);
    if (p.kind === "consume") rendered()?.cards(body); // a link on its own line: a card
    // Its task boxes: ticked in place (tasks.ts, a chunk of its own)
    if (body.querySelector("[data-line]") && !quiet)
      import("./tasks").then(
        (m) => m.wire(body, () => shown, changed, signal),
        () => {},
      );
    const files = figs ? figs.figures(body, p, queue, () => void refresh()) : links(p);
    const saved = download(`/api/pages/${p.id}/download`); // the page as a file
    const menus = "showPopover" in HTMLElement.prototype; // Share's menu can hold Download
    root.replaceChildren(
      h("h1", { dir: "auto" }, p.title),
      // What it is and when, one quiet line or two; then one row of chips: a todo's due chip
      // (a tap opens the editor at its Due fold) and its tags (each a search). Read only: its
      // tags and due date are changed in the editor (Edit)
      ...headLines(p),
      chipRow(p, () => void edit(p, false, true)) ?? "",
      // The header's end: one hairline between it and the body
      h("hr", { className: "headend", "aria-hidden": "true" }),
      body,
      // A topic's notes are the owner's, empty at first: where they go, said once
      p.topic && !p.body.trim()
        ? h(
            "p",
            { className: "notes" },
            "Your notes on this topic go here: Edit to add them. Claude never writes in them.",
          )
        : // The Pinned page (pins.ts): what it is for, said once
          p.slug === pinRow?.slug
          ? h(
              "p",
              { className: "notes" },
              "Shown under the empty search box. Edit to rename, reorder or take out a pin.",
            )
          : "",
      // The page's files (the owner's own), then one Claude card for the page, at its end:
      // its summary, a board's write-up, related pages
      h("div", { className: "originals" }, ...files),
      enr?.enrichPanel(p, show, wr?.writeupParts(p, show) ?? null) ?? "",
      h("div", { className: "bar tools" }, ...tools(p, saved, menus)),
    );
  };

  // The page's actions
  const tools = (p: Page, saved: HTMLElement, menus: boolean) => [
    // A todo or a Later leads with Mark done (the page's hero), or Reopen once done or
    // cancelled
    ...ticks(statusOf(p.kind, p.fields)).map(([label, to]) =>
      h(
        "button",
        {
          className: to === "done" ? "primary" : "",
          onclick: (e: Event) => tick(p, to, e.currentTarget as HTMLButtonElement),
        },
        icon(to === "done" ? "done" : "retry"),
        label,
      ),
    ),
    editButton(p),
    // Its link, its text as typed (no link to scrap in it), or the page as a file; where
    // the phone can't share, Download in Share's place (a computer has the menu, to copy),
    // and where it can share but has no menu (no Popover API), Download beside Share
    share(
      () => ({ title: p.title, text: unembedded(p.body) }),
      pageLink(p.slug),
      undefined,
      // (and Pin to Search, from the pins chunk: not on the Pinned page itself)
      // and, last, Make public… or Make private (publicpages.ts)
      menus
        ? [
            saved,
            ...(pinRow && p.slug !== pinRow.slug ? [pinRow.make(p)] : []),
            ...(canPublish ? [publicRow(p)] : []),
          ]
        : undefined,
    ) ?? saved,
    !menus && "share" in navigator && saved,
    h("button", { className: "danger", onclick: () => remove(p) }, icon("trash"), "Delete"),
  ];

  // Share's last row: Make public… (it asks first) or Make private (at once, with Undo)
  const view: View = { root, shown: () => shown, show };
  const publicRow = (p: Page) =>
    h(
      "button",
      {
        type: "button",
        onclick: () =>
          void publics().then(
            (m) => (p.public ? m.makePrivate(view) : m.makePublic(view)),
            () => toast("Can't do that offline: reload scrap and try again"),
          ),
      },
      globe(),
      p.public ? "Make private" : "Make public…",
    );
  // Saved here (an edit, a tick, a task box): a public page is published again
  const changed = (p: Page) => {
    show(p);
    if (p.public)
      void publics().then(
        (m) => m.republish(view),
        () => {},
      );
  };

  // The editor, with its draft if one was kept: a chunk of its own (pageedit.ts, with editor.ts)
  // row: from a list's row (not where the view is read); due: from the due chip, its Due fold
  // open and focused
  async function edit(p: Page, row = false, due = false) {
    const mod = await import("./pageedit").catch(() => null);
    if (!mod) return toast("Can't open the editor: reload scrap and try again");
    await mod.edit(p, load, show, row, due, changed);
  }

  // Ticked off (or not): its status only, no new revision
  const tick = (p: Page, to: string, b: HTMLButtonElement) => {
    b.disabled = true;
    // Mark done on a todo from the Todos screen: on to the next one (pager.ts), else shown here
    setStatus(p.id, to).then(
      (q) => {
        if (!(to === "done" && pager?.done(q, statusOf(p.kind, p.fields) ?? "open"))) changed(q);
        // on to the next one: this one is published off the screen
        else if (q.public)
          void publics().then(
            (m) => m.republishOff(q.slug),
            () => {},
          );
      },
      (err) => {
        b.disabled = false;
        toast(`Not changed: ${why(err)}`);
      },
    );
  };

  function editButton(p: Page) {
    const b = h("button", { onclick: () => void edit(p) }, icon("edit"), "Edit");
    drafts
      .get(`page:${p.id}`)
      .then((d) => {
        if (!d) return;
        b.setAttribute("aria-label", "Edit draft (unsaved)"); // starts with what it shows
        b.classList.add("dot"); // a mark on the icon says there is a draft
        b.lastChild?.replaceWith("Edit draft");
      })
      .catch(() => {});
    return b;
  }

  // Deleted: back one step to what it was opened from (a list with its query, filters and
  // scroll, or the page that linked to it), as Back goes; opened cold, where Back goes up to
  const remove = (p: Page) =>
    deletePage(
      p.id,
      () => {
        // Gone from the public pages that showed its title too (S5: as Make private does)
        if (canPublish)
          void publics().then(
            (m) => m.deleted(p),
            () => {},
          );
        return (history.state?.at ?? 0) > 0 // an entry the app pushed: one of the app's is behind it
          ? new Promise<void>((done) => {
              addEventListener("popstate", () => done(), { once: true }); // after main.ts's
              history.back();
            })
          : import("./back").then(
              (m) => m.up(go),
              () => go("/", true), // the chunk is not here (offline): Capture
            );
      },
      () => go(pageHref(p.slug)),
    );

  show(p);
  if (state?.edit && !quiet) {
    // Edit from a list's row: straight into the editor (once: not again on Back or reload)
    history.replaceState({ ...state, edit: false }, "");
    void edit(p, true);
  }
  return root;
}
