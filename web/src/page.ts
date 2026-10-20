// One page: its text (its images as figures) and other files, edit (with conflict handling)
// and delete with undo.
import { ApiError, api, blobUrl, type Page, type Queue, setStatus } from "./api";
import { go, view } from "./app";
import { drafts } from "./db";
import type { Trail } from "./gesture";
import { icon } from "./icons";
import { renderer, unembedded } from "./md";
import { statusOf, ticks } from "./status";
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

interface Draft {
  title: string;
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  base: number; // the revision it was made on
}
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
  const show = (p: Page) => {
    shown = p;
    schedule(p);
    const body = bodyView(p.body, false);
    const files = figs ? figs.figures(body, p, queue, () => void refresh()) : links(p);
    root.replaceChildren(
      pager ?? "",
      h("h1", { dir: "auto" }, p.title),
      // Its tags, most used first, in one line that scrolls; each one tapped searches for it
      // (with its children: tag:a finds a/b)
      p.tags?.length
        ? h(
            "p",
            { className: "tags" },
            ...p.tags.map((t) =>
              h("a", { href: `/search?q=${encodeURIComponent(token("tag", t))}` }, `#${t}`),
            ),
          )
        : "",
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
  };

  async function edit(p: Page) {
    // An unsaved edit comes back, on the revision it was made on: if the page has changed
    // since, saving it shows the conflict rather than overwriting.
    const key = `page:${p.id}`;
    const [kept, mod] = await Promise.all([
      drafts.get<Draft>(key).catch(() => undefined),
      import("./editor").catch(() => null), // a chunk of its own, with the composer
    ]);
    if (!mod) return toast("Can't open the editor: reload scrap and try again");
    const { editor, kindPicker, suggested, toSend, confirmRemoval } = mod;
    // Its kind. A note nobody filed yet gets one suggested from its text (a link alone: Read),
    // as in the composer, until the user picks one; a draft's kind only if the user picked it
    const unfiled = !p.kind_fixed && p.kind === "note";
    const was = unfiled ? suggested(p.body) : p.kind;
    const initial = unfiled ? suggested(kept?.text ?? p.body) : p.kind;
    const kind = kindPicker(kept?.picked ? (kept.kind ?? initial) : initial, !!kept?.picked);
    let base = kept?.base ?? p.rev;
    let over = p.body; // the text a save replaces: its deleted embeds are warned about
    const title = h("input", { value: kept?.title ?? p.title, "aria-label": "Title", dir: "auto" });
    const text = h("textarea", { value: kept?.text ?? p.body, rows: 8, "aria-label": "Body" });
    if (unfiled) text.addEventListener("input", () => kind.suggest(suggested(text.value)));
    const conflict = h("div");
    const save = async () => {
      if (!(await confirmRemoval(p, over, text.value))) return; // still editing, as it was
      try {
        const saved = await api<Page>(`pages/${p.id}`, {
          method: "PATCH",
          headers: JSON_TYPE,
          // The title only if changed: ingest may rename a provisional title meanwhile
          body: JSON.stringify({
            base_rev: base,
            body: text.value,
            ...(title.value !== p.title && { title: title.value }),
            kind: toSend(kind.value(), kind.picked(), p.kind),
          }),
        });
        await ed.done();
        await load(saved); // its first image: the figures
        show(saved);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) return toast(String(err));
        const theirs = await api<Page>(`pages/${p.id}`).catch(() => null);
        if (!theirs) return toast("Changed elsewhere, and the server can't be reached to show it");
        base = theirs.rev; // saving again now overwrites their version with yours
        over = theirs.body;
        conflict.replaceChildren(
          h(
            "div",
            { className: "conflict" },
            h(
              "p",
              {},
              "This page was changed elsewhere. Merge their text below into yours and save again, or discard yours.",
            ),
            h(
              "blockquote",
              { dir: "auto" },
              h("strong", {}, theirs.title),
              h("pre", {}, theirs.body),
            ),
            h(
              "button",
              {
                type: "button",
                onclick: async () => {
                  await ed.done();
                  await load(theirs);
                  show(theirs);
                },
              },
              "Discard mine, show theirs",
            ),
          ),
        );
        conflict.scrollIntoView({ behavior: "smooth" });
      }
    };
    const ed = editor({
      text,
      before: [kind.el, title],
      after: [conflict],
      key,
      draft: (): Draft => ({
        title: title.value,
        text: text.value,
        kind: kind.value(),
        picked: kind.picked(),
        base,
      }),
      dirty: () => title.value !== p.title || text.value !== p.body || kind.value() !== was,
      restored: !!kept,
      ondiscard: () => {
        title.value = p.title;
        text.value = p.body;
        kind.reset(was);
        base = p.rev;
        over = p.body;
      },
      onsave: () => void save(),
    });
    text.focus();
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
