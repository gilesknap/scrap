// A page's images as figures (a chunk of its own, with what Claude made of them): each image
// its text embeds, where it is, and below the text the files it doesn't (a PDF, or a photo of
// a page made before photos were embedded; not one whose embed was deleted). A figure opens the
// photo viewer (every image of the page, in order), and its caption has the file's name,
// Download and Ask Claude; once Claude has (or will have) seen it, its panel instead (ingest.ts).
// Any other file is a plain row (filerow.ts).
import {
  ApiError,
  api,
  blobUrl,
  type FileRef,
  type Page,
  photoIngest,
  previewUrl,
  type Queue,
  shareable,
} from "./api";
import { plain } from "./app";
import { fileRow } from "./filerow";
import { PHOTO, photoPanel } from "./ingest";
import { download, h, pageLink, settle, toast } from "./ui";
import { type Photo, viewer } from "./viewer";

type Placed = FileRef & { cid: string };
const isImage = (f: FileRef) => f.mime.startsWith("image/");
const SHA = /^[0-9a-f]{64}$/;

/** Upgrade the images in body (rendered by render.ts) to figures; returns what goes below it. */
export function figures(
  body: HTMLElement,
  p: Page,
  queue: Queue | null,
  refresh: () => void,
): HTMLElement[] {
  // Each file of the page once, from the capture that has Claude's results for it, if any
  const files = new Map<string, Placed>();
  for (const c of p.captures)
    for (const b of c.blobs) {
      const had = files.get(b.sha256);
      if (!had || (!had.ingest && b.ingest)) files.set(b.sha256, { ...b, cid: c.id });
    }
  // Only render.ts's own images (this server's files, by their sha), in a paragraph of images
  // alone, one or more lines of them: each becomes a figure. One in a link, a heading, a list,
  // a quote or beside text stays as it is (a figure there is not valid HTML), and its file is
  // listed below the text too, so every file of the page has its Download and Claude.
  const own = (n: Node): n is HTMLImageElement =>
    n instanceof HTMLImageElement && SHA.test(n.dataset.sha ?? "");
  const runs = [...body.children].filter(
    (el) =>
      el.tagName === "P" &&
      [...el.childNodes].some(own) &&
      // and nothing else: one in a link or in emphasis is not one of them (#82)
      [...el.childNodes].every(
        (n) => own(n) || n.nodeName === "BR" || (n instanceof Text && !n.data.trim()),
      ),
  );
  const shown = new Set(
    runs.flatMap((el) => [...el.children].filter(own).map((i) => i.dataset.sha)),
  );
  // A file of the page (a PDF, a .md) the text links to where it goes (the composer puts them
  // there, #403): a link, or its row in place on a line of its own; not listed below as well
  const inPlace: [HTMLElement, Placed][] = [];
  for (const a of body.querySelectorAll<HTMLAnchorElement>("a[data-sha]")) {
    const f = files.get(a.dataset.sha ?? "");
    if (!f || isImage(f)) continue;
    shown.add(f.sha256);
    const para = a.parentElement;
    if (para?.tagName === "P" && para.textContent?.trim() === a.textContent?.trim())
      inPlace.push([para, f]);
  }
  // Not an image whose embed was deleted from the text: it went with its line
  const removed = new Set(p.removed);
  const rest = [...files.values()].filter((f) => !shown.has(f.sha256) && !removed.has(f.sha256));
  const photos: Photo[] = [];

  const figure = (sha: string, name: string, f?: Placed) => {
    const at = photos.push({
      src: previewUrl(sha, 2048),
      save: `${blobUrl(sha)}?download=1`,
      name,
      share: f ? shareable(f) : [previewUrl(sha, 2048), `${sha.slice(0, 12)}.jpg`, "image/jpeg"],
    });
    const href = blobUrl(sha);
    const save = download(`${href}?download=1`, "save");
    const img = settle(h("img", { src: photos[at - 1].src, alt: name, loading: "lazy" }));
    const open = (e: MouseEvent) => {
      if (!plain(e)) return; // Ctrl-click, middle click: the file in a new tab
      e.preventDefault();
      viewer(photos, at - 1, pageLink(p.slug));
    };
    // No caption: its name and Download are the viewer's, a tap away
    const fig = h("figure", { className: "orig" }, h("a", { href, onclick: open }, img));
    img.onerror = () => fig.replaceWith(fileRow(href, name || "file", save)); // no preview
    // Another page's file (Claude's results are that page's), or not an image (a PDF's sha in an
    // image embed): no panel and no Ask Claude
    if (!f || !isImage(f)) return fig;
    const ingest = photoIngest(f);
    if (ingest) {
      return photoPanel({
        cid: f.cid,
        blob: { ...f, ingest },
        figure: fig,
        photo: photos[at - 1].src,
        slug: p.slug,
        queue,
        refresh,
      });
    }
    // Not read by Claude: what asking would do, in Claude's card under it
    return h(
      "section",
      { className: "photo-panel" },
      fig,
      h(
        "div",
        { className: "claude" },
        h(
          "div",
          { className: "ingest" },
          h("h3", { className: "ctitle" }, PHOTO),
          askClaude(f.cid, sha, refresh),
        ),
        h("p", { className: "did" }, "Claude can describe it and read any text in it."),
      ),
    );
  };

  for (const para of runs) {
    const figs = [...para.children].filter(own).map((img) => {
      const sha = img.dataset.sha as string;
      const f = files.get(sha);
      return figure(sha, f?.filename || img.alt || `Image ${sha.slice(0, 8)}`, f);
    });
    para.replaceWith(...figs);
  }
  const row = (f: Placed) => {
    const href = blobUrl(f.sha256);
    return fileRow(href, f.filename || f.mime, download(`${href}?download=1`, "save"), f.ingest);
  };
  for (const [para, f] of inPlace) para.replaceWith(row(f));
  return rest.map((f) => (isImage(f) ? figure(f.sha256, f.filename || "", f) : row(f)));
}

/** Send one image to Claude; the page, shown again, then has its panel with the queue state. */
function askClaude(cid: string, sha: string, refresh: () => void) {
  const b = h("button", { type: "button" }, "Generate"); // as every Claude card's first time
  b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api<{ queued: number; already: number }>(`captures/${cid}/reprocess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo: sha }),
      });
      if (!r.queued && !r.already) toast("Claude can't read this file");
      refresh();
    } catch (err) {
      b.disabled = false;
      toast(`Not sent: ${err instanceof ApiError ? err.message : "can't reach the server"}`);
    }
  };
  return b;
}
