// One page: its text and originals, edit (with conflict handling) and delete with undo.
import { ApiError, api, blobUrl, type Page } from "./api";
import { go } from "./app";
import { h, linkify, toast, when } from "./ui";

function original(f: Page["captures"][number]["blobs"][number]) {
  const href = blobUrl(f.sha256);
  const link = () => h("a", { href, target: "_blank", className: "file" }, f.filename || f.mime);
  if (!f.mime.startsWith("image/")) return link();
  const img = h("img", { src: href, alt: f.filename || "", loading: "lazy" });
  img.onerror = () => img.replaceWith(link()); // e.g. HEIC, which Chrome cannot show
  return h("a", { href, target: "_blank" }, img);
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
      h("div", { className: "body" }, ...linkify(p.body)),
      h("div", { className: "originals" }, ...p.captures.flatMap((c) => c.blobs.map(original))),
      h(
        "div",
        { className: "bar" },
        h("button", { onclick: () => edit(p) }, "Edit"),
        h("button", { className: "danger", onclick: () => remove(p) }, "Delete"),
      ),
    );

  function edit(p: Page) {
    let base = p.rev;
    const title = h("input", { value: p.title, "aria-label": "Title" });
    const body = h("textarea", { value: p.body, rows: 8, "aria-label": "Body" });
    const conflict = h("div");
    const save = async (e: Event) => {
      e.preventDefault();
      try {
        show(
          await api<Page>(`pages/${p.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ base_rev: base, title: title.value, body: body.value }),
          }),
        );
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) return toast(String(err));
        const theirs = await api<Page>(`pages/${p.id}`);
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
              { type: "button", onclick: () => show(theirs) },
              "Discard mine, show theirs",
            ),
          ),
        );
        conflict.scrollIntoView({ behavior: "smooth" });
      }
    };
    root.replaceChildren(
      h(
        "form",
        { className: "edit", onsubmit: save },
        title,
        body,
        conflict,
        h(
          "div",
          { className: "bar" },
          h("button", { type: "button", onclick: () => show(p) }, "Cancel"),
          h("button", { type: "submit", className: "primary" }, "Save"),
        ),
      ),
    );
  }

  async function remove(p: Page) {
    await api(`pages/${p.id}`, { method: "DELETE" });
    go("/recent");
    toast(
      "Page deleted",
      "Undo",
      async () => {
        await api(`pages/${p.id}/undelete`, { method: "POST" });
        go(`/p/${encodeURIComponent(p.slug)}`);
      },
      8000,
    );
  }

  show(p);
  return root;
}
