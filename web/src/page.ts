// One page: its text and originals, edit (with conflict handling) and delete with undo.
import { ApiError, api, blobUrl, type FileRef, type Page, previewUrl } from "./api";
import { go } from "./app";
import { editor } from "./editor";
import { bodyView, download, h, toast, when } from "./ui";
import { type Photo, viewer } from "./viewer";

const isImage = (f: FileRef) => f.mime.startsWith("image/");

/** The page's files: photos open the viewer (at photo n), other files a new tab. */
function originals(files: FileRef[]) {
  const photos: Photo[] = files.filter(isImage).map((f) => ({
    src: previewUrl(f.sha256, 2048),
    save: `${blobUrl(f.sha256)}?download=1`,
    name: f.filename || "",
  }));
  let n = 0;
  return files.map((f) => {
    const href = blobUrl(f.sha256);
    const save = download(`${href}?download=1`, "save");
    const link = () => h("a", { href, target: "_blank", className: "file" }, f.filename || f.mime);
    if (!isImage(f)) return h("div", { className: "orig" }, link(), save);
    const at = n++;
    const img = h("img", { src: photos[at].src, alt: f.filename || "", loading: "lazy" });
    img.onerror = () => img.replaceWith(link()); // no preview: a file the server can't read
    const open = (e: Event) => {
      e.preventDefault();
      viewer(photos, at);
    };
    return h("figure", { className: "orig" }, h("a", { href, onclick: open }, img), save);
  });
}

const RAW = "scrap.raw"; // show page text as typed, not formatted

/** The page text, formatted, with a switch to the text as typed (remembered). */
function body(text: string) {
  const box = h("div");
  const draw = () => {
    const raw = localStorage.getItem(RAW) === "1";
    const flip = () => {
      localStorage.setItem(RAW, raw ? "0" : "1");
      draw();
    };
    box.replaceChildren(
      bodyView(text, raw),
      h(
        "button",
        { type: "button", className: "link", onclick: flip },
        raw ? "Formatted" : "Raw text",
      ),
    );
  };
  draw();
  return box;
}

export async function page(key: string): Promise<Node> {
  const p = await api<Page>(`pages/${encodeURIComponent(key)}`);
  const root = h("article", { className: "page" });
  const show = (p: Page) =>
    root.replaceChildren(
      h("h1", {}, p.title),
      h(
        "p",
        { className: "meta" },
        `Created ${when(p.created_at)}`,
        p.updated_at !== p.created_at && ` · edited ${when(p.updated_at)}`,
      ),
      body(p.body),
      h("div", { className: "originals" }, ...originals(p.captures.flatMap((c) => c.blobs))),
      h(
        "div",
        { className: "bar" },
        h("button", { onclick: () => edit(p) }, "Edit"),
        download(`/api/pages/${p.id}/download`),
        h("button", { className: "danger", onclick: () => remove(p) }, "Delete"),
      ),
    );

  function edit(p: Page) {
    let base = p.rev;
    const title = h("input", { value: p.title, "aria-label": "Title" });
    const text = h("textarea", { value: p.body, rows: 8, "aria-label": "Body" });
    const conflict = h("div");
    const save = async () => {
      try {
        const saved = await api<Page>(`pages/${p.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          // The title only if changed: ingest may rename a provisional title meanwhile
          body: JSON.stringify({
            base_rev: base,
            body: text.value,
            ...(title.value !== p.title && { title: title.value }),
          }),
        });
        ed.close();
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
            h("strong", {}, theirs.title),
            h("pre", {}, theirs.body),
            h(
              "button",
              {
                type: "button",
                onclick: () => {
                  ed.close();
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
    const ed = editor({ text, before: [title], after: [conflict], onsave: () => void save() });
    text.focus();
  }

  const why = (err: unknown) => (err instanceof ApiError ? err.message : "can't reach the server");

  async function remove(p: Page) {
    try {
      await api(`pages/${p.id}`, { method: "DELETE" });
    } catch (err) {
      return toast(`Not deleted: ${why(err)}`);
    }
    go("/recent");
    const undo = async () => {
      try {
        await api(`pages/${p.id}/undelete`, { method: "POST" });
        go(`/p/${encodeURIComponent(p.slug)}`);
      } catch (err) {
        toast(`Undo failed: ${why(err)}`, "Try again", undo, 8000);
      }
    };
    toast("Page deleted", "Undo", undo, 8000);
  }

  show(p);
  return root;
}
