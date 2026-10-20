// One page: its text and originals, edit (with conflict handling) and delete with undo.
import {
  ApiError,
  api,
  blobUrl,
  type FileRef,
  type Ingest,
  type Page,
  previewUrl,
  type Queue,
  shareable,
} from "./api";
import { go, view } from "./app";
import { drafts } from "./db";
import type { Trail } from "./gesture";
import { icon } from "./icons";
import { deletePage } from "./swipe";
import { bodyView, download, h, settle, share, toast, when } from "./ui";
import { type Photo, viewer } from "./viewer";

const isImage = (f: FileRef) => f.mime.startsWith("image/");
type Placed = FileRef & { cid: string };
const POLL = 10_000; // while Claude has a photo of this page

/** The page's files: photos open the viewer (at photo n), other files a new tab. A photo
 * Claude has seen (or will) gets its panel: state, text, description and drawing. */
type Panels = typeof import("./ingest");

function originals(p: Page, queue: Queue | null, panels: Panels | null, refresh: () => void) {
  const files: Placed[] = p.captures.flatMap((c) => c.blobs.map((b) => ({ ...b, cid: c.id })));
  const photos: Photo[] = files.filter(isImage).map((f) => ({
    src: previewUrl(f.sha256, 2048),
    save: `${blobUrl(f.sha256)}?download=1`,
    name: f.filename || "",
    share: shareable(f),
  }));
  let n = 0;
  return files.map((f) => {
    const href = blobUrl(f.sha256);
    const save = download(`${href}?download=1`, "save");
    const name = f.filename || f.mime;
    const link = () =>
      h("a", { href, target: "_blank", className: "file" }, icon("file"), h("span", {}, name));
    if (!isImage(f)) return h("div", { className: "orig" }, link(), save);
    const at = n++;
    const img = settle(h("img", { src: photos[at].src, alt: f.filename || "", loading: "lazy" }));
    const open = (e: Event) => {
      e.preventDefault();
      viewer(photos, at);
    };
    const shown = h("a", { href, onclick: open }, img);
    const fig = h(
      "figure",
      { className: "orig" },
      shown,
      h("figcaption", {}, h("span", {}, f.filename ?? ""), save),
    );
    img.onerror = () => fig.replaceWith(h("div", { className: "orig" }, link(), save)); // no preview
    if (!f.ingest || !panels) return fig;
    const blob = f as Placed & { ingest: Ingest };
    const photo = photos[at].src;
    return panels.photoPanel({
      cid: f.cid,
      blob,
      figure: fig,
      photo,
      slug: p.slug,
      queue,
      refresh,
    });
  });
}

const busy = (p: Page) =>
  p.captures.some((c) =>
    c.blobs.some((b) => b.ingest && ["queued", "processing"].includes(b.ingest.state)),
  );
const ingestOf = (p: Page) => JSON.stringify(p.captures.map((c) => c.blobs.map((b) => b.ingest)));

interface Draft {
  title: string;
  text: string;
  kind?: string;
  base: number; // the revision it was made on
}
const JSON_TYPE = { "Content-Type": "application/json" };
const done = (p: Page) => p.fields.status === "done";

export async function page(key: string): Promise<Node> {
  const signal = view.signal; // this view's, taken before any wait: Back may come meanwhile
  const state = history.state as { trail?: Trail; edit?: boolean; from?: 1 | -1 } | null;
  const p = await api<Page>(`pages/${encodeURIComponent(key)}`);
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
  // What Claude made of photos is a chunk of its own, loaded for pages that have some
  let panels: Panels | null = null;
  const hasIngest = (p: Page) => p.captures.some((c) => c.blobs.some((b) => b.ingest));
  const load = async (p: Page) => {
    if (!hasIngest(p) || panels) return;
    [panels, queue] = await Promise.all([
      import("./ingest").catch(() => null), // offline: the photos still show
      api<Queue>("ingest").catch(() => queue),
    ]);
  };
  await load(p);
  const show = (p: Page) => {
    shown = p;
    schedule(p);
    root.replaceChildren(
      pager ?? "",
      h("h1", { dir: "auto" }, p.title),
      h(
        "p",
        { className: "meta" },
        `Created ${when(p.created_at)}`,
        p.updated_at !== p.created_at && ` · edited ${when(p.updated_at)}`,
      ),
      bodyView(p.body, false),
      h("div", { className: "originals" }, ...originals(p, queue, panels, () => void refresh())),
      h(
        "div",
        { className: "bar tools" },
        editButton(p),
        p.kind === "todo" &&
          h("button", { onclick: () => tick(p) }, icon("todo"), done(p) ? "Reopen" : "Done"),
        download(`/api/pages/${p.id}/download`),
        share(() => ({ title: p.title, text: p.body })), // its text as typed, no link here
        h("button", { className: "danger", onclick: () => remove(p) }, icon("trash"), "Delete"),
      ),
    );
  };

  async function edit(p: Page) {
    // An unsaved edit comes back, on the revision it was made on: if the page has changed
    // since, saving it shows the conflict rather than overwriting.
    const key = `page:${p.id}`;
    const [kept, { editor, kindPicker, BARE_URL }] = await Promise.all([
      drafts.get<Draft>(key).catch(() => undefined),
      import("./editor"), // a chunk of its own, with the composer
    ]);
    // Its kind; a link nobody filed yet suggests Read
    const unfiled = !p.kind_fixed && p.kind === "note" && BARE_URL.test(p.body.trim());
    const was = unfiled ? "consume" : p.kind;
    const kind = kindPicker(kept?.kind ?? was);
    let base = kept?.base ?? p.rev;
    const title = h("input", { value: kept?.title ?? p.title, "aria-label": "Title", dir: "auto" });
    const text = h("textarea", { value: kept?.text ?? p.body, rows: 8, "aria-label": "Body" });
    const conflict = h("div");
    const save = async () => {
      try {
        const saved = await api<Page>(`pages/${p.id}`, {
          method: "PATCH",
          headers: JSON_TYPE,
          // The title only if changed: ingest may rename a provisional title meanwhile
          body: JSON.stringify({
            base_rev: base,
            body: text.value,
            ...(title.value !== p.title && { title: title.value }),
            ...(kind.value() !== p.kind && { kind: kind.value() }),
          }),
        });
        await ed.done();
        show(saved);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) return toast(String(err));
        const theirs = await api<Page>(`pages/${p.id}`).catch(() => null);
        if (!theirs) return toast("Changed elsewhere, and the server can't be reached to show it");
        base = theirs.rev; // saving again now overwrites their version with yours
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
      draft: (): Draft => ({ title: title.value, text: text.value, kind: kind.value(), base }),
      dirty: () => title.value !== p.title || text.value !== p.body || kind.value() !== was,
      restored: !!kept,
      ondiscard: () => {
        title.value = p.title;
        text.value = p.body;
        kind.reset(was);
        base = p.rev;
      },
      onsave: () => void save(),
    });
    text.focus();
  }

  // A todo ticked off (or not): its fields only, no new revision
  const tick = (p: Page) =>
    api<Page>(`pages/${p.id}`, {
      method: "PATCH",
      headers: JSON_TYPE,
      body: JSON.stringify({ fields: { status: done(p) ? "open" : "done" } }),
    }).then(show, (err) => toast(`Not changed: ${err}`));

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

  const remove = (p: Page) =>
    deletePage(
      p.id,
      () => go("/recent"),
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
