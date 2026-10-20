// A page's images as figures (a chunk of its own, with what Claude made of them): each image
// its text embeds, where it is, and below the text the files it doesn't (a PDF, or a photo of
// a page made before photos were embedded; not one whose embed was deleted). A figure opens the
// photo viewer (every image of the page, in order), and its caption has the file's name,
// Download and Ask Claude; once Claude has (or will have) seen it, its panel instead (ingest.ts).
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
import { plain } from "./app";
import { icon } from "./icons";
import { photoPanel } from "./ingest";
import { download, h, pageLink, settle, toast } from "./ui";
import { type Photo, viewer } from "./viewer";

type Placed = FileRef & { cid: string };
const isImage = (f: FileRef) => f.mime.startsWith("image/");
const SHA = /^[0-9a-f]{64}$/;

/** Upgrade the images in body (rendered by md.ts) to figures; returns what goes below it. */
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
  // Only md.ts's own images (this server's files, by their sha), in a paragraph of images
  // alone, one or more lines of them: each becomes a figure. One in a link, a heading, a list,
  // a quote or beside text stays as it is (a figure there is not valid HTML), and its file is
  // listed below the text too, so every file of the page has its Download and Claude.
  const own = (n: Node): n is HTMLImageElement =>
    n instanceof HTMLImageElement && SHA.test(n.dataset.sha ?? "");
  const runs = [...body.children].filter(
    (el) =>
      el.tagName === "P" &&
      [...el.childNodes].some(own) &&
      [...el.childNodes].every((n) => own(n) || n.nodeName === "BR" || !n.textContent?.trim()),
  );
  const shown = new Set(
    runs.flatMap((el) => [...el.children].filter(own).map((i) => i.dataset.sha)),
  );
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
    const caption = h("figcaption", {}, h("span", {}, name), save);
    const fig = h("figure", { className: "orig" }, h("a", { href, onclick: open }, img), caption);
    img.onerror = () => fig.replaceWith(fileRow(href, name || "file", save)); // no preview
    if (!f) return fig; // another page's file: Claude's results are that page's
    if (f.ingest) {
      const blob = f as Placed & { ingest: Ingest };
      return photoPanel({
        cid: f.cid,
        blob,
        figure: fig,
        photo: photos[at - 1].src,
        slug: p.slug,
        queue,
        refresh,
      });
    }
    caption.append(askClaude(f.cid, sha, refresh));
    return fig;
  };

  for (const para of runs) {
    const figs = [...para.children].filter(own).map((img) => {
      const sha = img.dataset.sha as string;
      const f = files.get(sha);
      return figure(sha, f?.filename || img.alt || `Image ${sha.slice(0, 8)}`, f);
    });
    para.replaceWith(...figs);
  }
  return rest.map((f) => {
    const name = f.filename || f.mime;
    if (isImage(f)) return figure(f.sha256, f.filename || "", f);
    const href = blobUrl(f.sha256);
    return fileRow(href, name, download(`${href}?download=1`, "save"));
  });
}

const fileRow = (href: string, name: string, save: HTMLElement) =>
  h(
    "div",
    { className: "orig" },
    h("a", { href, target: "_blank", className: "file" }, icon("file"), h("span", {}, name)),
    save,
  );

/** Send one image to Claude; the page, shown again, then has its panel with the queue state. */
function askClaude(cid: string, sha: string, refresh: () => void) {
  const b = h("button", { type: "button", className: "save" }, "Ask Claude");
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
