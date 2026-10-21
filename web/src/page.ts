// One page: its text (its images as figures) and other files, edit (pageedit.ts, with conflict handling)
// and delete with undo.
import { api, blobUrl, type Page, type Queue, setStatus } from "./api";
import { go, view } from "./app";
import { drafts } from "./db";
import type { Trail } from "./gesture";
import { icon } from "./icons";
import { renderer, unembedded } from "./md";
import { dueOf, statusOf, ticks } from "./status";
import { deletePage, why } from "./swipe";
import { token } from "./terms";
import { bodyView, download, h, pageLink, share, toast, when } from "./ui";

const POLL = 10_000; // while Claude has a photo of this page

/** The page's images as figures, with what Claude made of them: a chunk of its own. */
type Figures = typeof import("./figure");
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

export async function page(key: string): Promise<Node> {
  const signal = view.signal; // this view's, taken before any wait: Back may come meanwhile
  const state = history.state as { trail?: Trail; edit?: boolean; from?: 1 | -1 } | null;
  // The renderer, a chunk of its own, while the page is fetched (offline without it: as typed)
  const [p] = await Promise.all([api<Page>(`pages/${encodeURIComponent(key)}`), renderer()]);
  const root = h("article", { className: "page" });
  // Opened from a list: its pager, swipes and keys (a chunk of its own; none offline)
  const pager = state?.trail
    ? (await import("./pager").catch(() => null))?.pager(state, p.slug, root, signal)
    : null;
  let shown = p;
  let queue: Queue | null = null;
  let poll = 0;
  signal.addEventListener("abort", () => clearTimeout(poll));
  // Fetch the page again and show it if what Claude did changed (a new state or drawing)
  const refresh = async (force = true) => {
    clearTimeout(poll);
    try {
      const [fresh, q] = await Promise.all([
        api<Page>(`pages/${p.id}`),
        api<Queue>("ingest").catch(() => queue),
      ]);
      await load(fresh);
      if (signal.aborted) return;
      const changed = ingestOf(fresh) !== ingestOf(shown) || q?.paused !== queue?.paused;
      queue = q;
      if (force || changed) show(fresh);
      else schedule(fresh);
    } catch {
      if (!signal.aborted) schedule(shown); // offline for now: try again later
    }
  };
  const schedule = (p: Page) => {
    clearTimeout(poll);
    if (busy(p) && queue?.enabled && !queue.paused && !signal.aborted) {
      poll = window.setTimeout(() => {
        if (document.visibilityState === "visible") void refresh(false);
        else schedule(p);
      }, POLL);
    }
  };
  // Figures are a chunk of its own, loaded for pages with files or images
  let figs: Figures | null = null;
  const load = async (p: Page) => {
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
    schedule(p);
    const body = bodyView(p.body, false);
    // Its task boxes: ticked in place (tasks.ts, a chunk of its own)
    if (body.querySelector("[data-line]"))
      import("./tasks").then(
        (m) => m.wire(body, () => shown, show, signal),
        () => {},
      );
    const files = figs ? figs.figures(body, p, queue, () => void refresh()) : links(p);
    const typing = !!tagForm?.contains(document.activeElement);
    const said = dueOf(p);
    root.replaceChildren(
      pager ?? "",
      h("h1", { dir: "auto" }, p.title),
      // Its tags, most used first, in one line that scrolls; each one tapped searches for it
      // (with its children: tag:a finds a/b). First, Tags: tapped, edits them in place
      tagForm ??
        h(
          "p",
          { className: "tags" },
          h(
            "button",
            // Not "Edit tags": the toolbar's Edit stays the only button named Edit
            {
              type: "button",
              "aria-label": p.tags.length ? "Change tags" : "Add tags",
              onclick: (e: Event) => tagEdit(e),
            },
            icon("tag"),
            p.tags.length ? "Tags" : "Add tags",
          ),
          ...p.tags.map((t) =>
            h("a", { href: `/search?q=${encodeURIComponent(token("tag", t))}` }, `#${t}`),
          ),
        ),
      // A todo's due date and priority: tapped, changed in place
      p.kind !== "todo"
        ? ""
        : (todoForm ??
            h(
              "p",
              { className: "todoline" },
              h(
                "button",
                {
                  type: "button",
                  title: "Due date and priority",
                  onclick: (e: Event) => void todoEdit(e),
                },
                icon("todo"),
                h("span", { className: said?.[1] ? "late" : "" }, said ? said[0] : "Add due date"),
              ),
            )),
      h(
        "p",
        { className: "meta" },
        `Created ${when(p.created_at)}`,
        p.updated_at !== p.created_at && ` · edited ${when(p.updated_at)}`,
        // Written over MCP: a badge, its origin as the tooltip; tapped, finds them all
        p.captures[0]?.source === "mcp" &&
          h(
            "a",
            {
              className: "badge",
              href: "/search?q=is%3Aclaude",
              title: String(p.fields.origin ?? "Written by Claude over MCP"),
            },
            "Written by Claude",
          ),
      ),
      body,
      h("div", { className: "originals" }, ...files),
      h(
        "div",
        { className: "bar tools" },
        editButton(p),
        // A todo or a Read: Done, Reopen (done or cancelled), or both (cancelled)
        ...ticks(statusOf(p.kind, p.fields)).map(([label, to]) =>
          h(
            "button",
            { onclick: (e: Event) => tick(p, to, e.currentTarget as HTMLButtonElement) },
            icon(to === "done" ? "todo" : "retry"),
            label,
          ),
        ),
        download(`/api/pages/${p.id}/download`),
        // Its link, or its text as typed (no link to scrap in it)
        share(() => ({ title: p.title, text: unembedded(p.body) }), pageLink(p.slug)),
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
    const line = (e.currentTarget as HTMLElement).parentElement as HTMLElement;
    const mod = await import("./tagedit").catch(() => null);
    if (!mod) return toast("Can't edit tags offline");
    const p = shown; // as it is now
    const field = mod.tagField(p.tags);
    const save = h("button", { type: "submit", className: "primary" }, "Save");
    // Closed (saved or not): the page as it is now, focus back on its Tags button
    const close = (to: Page) => {
      tagForm = null;
      show(to);
      root.querySelector<HTMLElement>(".tags > button")?.focus();
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
            body: JSON.stringify({ tags: field.value() }),
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
    line.replaceWith(form);
    field.input.focus();
  }

  // A todo's due date and priority, changed in place of their line: no new revision
  async function todoEdit(e: Event) {
    const line = (e.currentTarget as HTMLElement).parentElement as HTMLElement;
    const mod = await import("./todoedit").catch(() => null);
    if (!mod) return toast("Can't change it offline");
    // Saved: the page as saved; cancelled: as it is now (it may have changed meanwhile)
    const { form, focus } = mod.todoForm(shown, (to) => {
      todoForm = null;
      show(to ?? shown);
      root.querySelector<HTMLElement>(".todoline > button")?.focus();
    });
    todoForm = form;
    line.replaceWith(form);
    focus();
  }

  // Ticked off (or not): its status only, no new revision
  const tick = (p: Page, to: string, b: HTMLButtonElement) => {
    b.disabled = true;
    setStatus(p.id, to).then(show, (err) => {
      b.disabled = false;
      toast(`Not changed: ${why(err)}`);
    });
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

  // Deleted: back to the list it was opened from (its query, filters and scroll: the entry
  // before this one), else to the newest-first list
  const remove = (p: Page) =>
    deletePage(
      p.id,
      () =>
        state?.trail
          ? new Promise<void>((done) => {
              addEventListener("popstate", () => done(), { once: true }); // after main.ts's
              history.back();
            })
          : go("/search", true),
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
