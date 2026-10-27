// One page: its text (its images as figures) and other files, edit (pageedit.ts, with conflict handling)
// and delete with undo.
import { ADDED, api, blobUrl, type Page, type Queue, setStatus } from "./api";
import { go } from "./app";
import { remember } from "./crumbs";
import { drafts } from "./db";
import type { Trail } from "./gesture";
import { icon } from "./icons";
import { rendered, renderer, unembedded } from "./md";
import { chipRow, headLines } from "./pagehead";
import { statusOf, ticks } from "./status";
import { deletePage, why } from "./swipe";
import { seenTopic } from "./topicseen";
import { bodyView, download, h, pageLink, share, toast } from "./ui";

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

const busy = (p: Page) =>
  p.captures.some((c) =>
    c.blobs.some((b) => b.ingest && ["queued", "processing"].includes(b.ingest.state)),
  );
const ingestOf = (p: Page) => JSON.stringify(p.captures.map((c) => c.blobs.map((b) => b.ingest)));

const JSON_TYPE = { "Content-Type": "application/json" };

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

export async function page(key: string, signal: AbortSignal): Promise<Node> {
  // signal: this view's, taken before any wait (even the chunk's): Back may come meanwhile
  const state = history.state as { trail?: Trail; edit?: boolean; from?: 1 | -1 } | null;
  // The renderer, a chunk of its own, while the page is fetched (offline without it: as typed)
  // and Share's Pin to Search (pins.ts, a chunk of its own; none offline before it was kept)
  const [p, pinRow] = await Promise.all([
    api<Page>(`pages/${encodeURIComponent(key)}`, { signal }),
    import("./pins").then(
      (m) => ({ slug: m.SLUG, make: (p: Page) => m.pinPageButton(p.slug, p.title) }),
      () => null,
    ),
    renderer(),
  ]);
  signal.throwIfAborted(); // gone meanwhile (Back, or timed out): no poll or listeners
  const root = h("article", { className: "page" });
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
  // Photos added to it (the editor's Add photo, uploaded now or later): shown, and read
  const added = (e: Event) => (e as CustomEvent<Page>).detail.id === p.id;
  addEventListener(ADDED, (e) => added(e) && void refresh(), { signal });
  const schedule = (p: Page) => {
    clearTimeout(poll);
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
  // Its tags being edited in place: kept as they are (what is typed, chips taken off) when
  // the page is drawn again meanwhile, e.g. a photo's reading state changing
  let tagForm: HTMLFormElement | null = null;
  let todoForm: HTMLFormElement | null = null; // its due date and priority, likewise
  const show = (p: Page) => {
    shown = p;
    drawn++;
    // For the top bar's Back: a todo's parent is the Todos screen, a topic's the Topics screen
    root.dataset.kind = p.topic ? "topic" : p.kind;
    // Its name as shown, for Back on the pages its links open (crumbs.ts): renamed in place too
    if (!signal.aborted) remember(p.title);
    // A topic shown, however it was reached: its dot on the Topics screen has done its job
    if (p.topic) seenTopic(p.id, p.writeup?.current?.created_at ?? p.updated_at);
    schedule(p);
    const body = bodyView(untitled(p.body, p.title), false);
    if (p.kind === "consume") rendered()?.cards(body); // a link on its own line: a card
    // Its task boxes: ticked in place (tasks.ts, a chunk of its own)
    if (body.querySelector("[data-line]"))
      import("./tasks").then(
        (m) => m.wire(body, () => shown, show, signal),
        () => {},
      );
    const files = figs ? figs.figures(body, p, queue, () => void refresh()) : links(p);
    const typing = !!tagForm?.contains(document.activeElement);
    const saved = download(`/api/pages/${p.id}/download`); // the page as a file
    const menus = "showPopover" in HTMLElement.prototype; // Share's menu can hold Download
    root.replaceChildren(
      h("h1", { dir: "auto" }, p.title),
      // What it is and when, one quiet line or two; then one row of chips: a todo's due chip
      // (opens the due editor, under the row) and its tags (each a search; + changes them)
      ...headLines(p),
      tagForm ?? chipRow(p, { tags: tagEdit, due: (e) => void todoEdit(e), dueOpen: !!todoForm }),
      todoForm ?? "",
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
      // One Claude card for the page, at its end: its summary, a board's write-up, related pages
      enr?.enrichPanel(p, show, wr?.writeupParts(p, show) ?? null) ?? "",
      h("div", { className: "originals" }, ...files),
      h(
        "div",
        { className: "bar tools" },
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
        // the phone can't share, Download in Share's place, and where it can share but has no
        // menu (no Popover API), Download beside Share
        share(
          () => ({ title: p.title, text: unembedded(p.body) }),
          pageLink(p.slug),
          undefined,
          // (and Pin to Search, from the pins chunk: not on the Pinned page itself)
          menus
            ? [saved, ...(pinRow && p.slug !== pinRow.slug ? [pinRow.make(p)] : [])]
            : undefined,
        ) ?? saved,
        !menus && "share" in navigator && saved,
        h("button", { className: "danger", onclick: () => remove(p) }, icon("trash"), "Delete"),
      ),
    );
    if (typing) tagForm?.querySelector("input")?.focus();
  };

  // The editor, with its draft if one was kept: a chunk of its own (pageedit.ts, with editor.ts)
  async function edit(p: Page) {
    const mod = await import("./pageedit").catch(() => null);
    if (!mod) return toast("Can't open the editor: reload scrap and try again");
    await mod.edit(p, load, show);
  }

  // Its tags edited in place of their line: no new revision (a chunk of its own)
  async function tagEdit(e: Event) {
    const line = (e.currentTarget as HTMLElement).closest(".tags") as HTMLElement;
    const mod = await import("./tagedit").catch(() => null);
    if (!mod) return toast("Can't edit tags offline");
    const p = shown; // as it is now
    const field = mod.tagField(p.tags);
    const save = h("button", { type: "submit", className: "primary" }, "Save");
    // Closed (saved or not): the page as it is now, focus back on its Tags button
    const close = (to: Page) => {
      tagForm = null;
      show(to);
      root.querySelector<HTMLElement>(".tags .add")?.focus();
    };
    const form = h(
      "form",
      {
        className: "tagform",
        onkeydown: (e: KeyboardEvent) => {
          if (e.key === "Escape") close(shown);
        },
        onsubmit: (e: Event) => {
          e.preventDefault();
          save.disabled = true;
          api<Page>(`pages/${p.id}`, {
            method: "PATCH",
            headers: JSON_TYPE,
            // What it was shown: a tag Claude adds meanwhile is kept, not taken off
            body: JSON.stringify({ tags: field.value(), tags_shown: p.tags }),
          }).then(close, (err) => {
            save.disabled = false;
            toast(`Not saved: ${why(err)}`);
          });
        },
      },
      field.el,
      h(
        "div",
        { className: "row" },
        h("button", { type: "button", className: "ghost", onclick: () => close(shown) }, "Cancel"),
        save,
      ),
    );
    tagForm = form;
    // The due chip stays (it is not a tag); the tags and + give way to the form under the row
    const chip = line.querySelector(".duechip");
    if (chip) {
      for (const c of [...line.children]) if (c !== chip) c.remove();
      line.after(form);
    } else line.replaceWith(form);
    field.input.focus();
  }

  // A todo's due date and priority, changed in place of their line: no new revision
  async function todoEdit(e: Event) {
    const chip = e.currentTarget as HTMLElement;
    const row = chip.parentElement as HTMLElement;
    const mod = await import("./todoedit").catch(() => null);
    if (!mod) return toast("Can't change it offline");
    // Saved: the page as saved; cancelled: as it is now (it may have changed meanwhile)
    const { form, focus } = mod.todoForm(shown, (to) => {
      todoForm = null;
      show(to ?? shown);
      // The chip may be gone (a closed todo saved with no date or priority): then the +
      root.querySelector<HTMLElement>(".tags > .duechip, .tags .add")?.focus();
    });
    todoForm = form;
    chip.remove(); // under the row, in the chip's place
    row.after(form);
    focus();
  }

  // Ticked off (or not): its status only, no new revision
  const tick = (p: Page, to: string, b: HTMLButtonElement) => {
    b.disabled = true;
    // Mark done on a todo from the Todos screen: on to the next one (pager.ts), else shown here
    setStatus(p.id, to).then(
      (q) => (to === "done" && pager?.done(q, statusOf(p.kind, p.fields) ?? "open")) || show(q),
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
      () =>
        (history.state?.at ?? 0) > 0 // an entry the app pushed: one of the app's is behind it
          ? new Promise<void>((done) => {
              addEventListener("popstate", () => done(), { once: true }); // after main.ts's
              history.back();
            })
          : import("./back").then(
              (m) => m.up(go),
              () => go("/", true), // the chunk is not here (offline): Capture
            ),
      () => go(`/p/${encodeURIComponent(p.slug)}`),
    );

  show(p);
  if (state?.edit) {
    // Edit from a list's row: straight into the editor (once: not again on Back or reload)
    history.replaceState({ ...state, edit: false }, "");
    void edit(p);
  }
  return root;
}
