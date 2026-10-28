// The page editor's Add photo (#260): photos from the camera or the gallery, added to the end
// of a page that exists; and File's PDFs, text and Markdown (#234, #380), listed below the
// page's text. They go through the capture queue (queue.ts), so they wait on the phone while
// offline, and the server reads them as it reads any capture's photos. Part of the editor's
// chunk.
import { overLimit } from "./api";
import { queue } from "./app";
import { FILES, picker } from "./capture";
import type { Capture } from "./queue";
import { holds } from "./says";
import { h, toast } from "./ui";

/** The editor's text once the server added photos onto the revision it holds: over is that
 * revision's text, saved the page's text now (over, then the images' embeds), text what the
 * editor holds. Its own text, then the embeds; null if saved is not over plus embeds. */
export function adopt(text: string, over: string, saved: string): string | null {
  const start = over.trimEnd();
  if (!saved.startsWith(start)) return null;
  const added = saved.slice(start.length).trimStart();
  return [text.trimEnd(), added].filter(Boolean).join("\n\n");
}

/** What to queue for photos picked for a page (its id and title): one upload, or one per
 * photo if together they are over the server's limit; a reason instead if one photo is over
 * it alone. */
export function uploads(files: File[], page: { id: string; title: string }): Capture[] | string {
  if (files.some((f) => overLimit(f.size)))
    return "That file is over the server's upload limit, so it can't be added.";
  const one = (fs: File[]): Capture => ({
    source: "pwa",
    files: fs.map((f) => ({ name: f.name, blob: f })),
    page: page.id,
    to: page.title,
  });
  const size = files.reduce((n, f) => n + f.size, 0);
  return overLimit(size) ? files.map((f) => one([f])) : [one(files)];
}

/** Whether the editor offers Add photo: not on a topic page, whose synthesis is its write-up
 * (a board photo would queue one over it; the server refuses them too). */
export const takesPhotos = (page: { topic?: unknown }) => !page.topic;

/** Add photo, for the page editor: Camera, Gallery and File, named as the composer's are
 * (short enough to share a row at large text sizes). */
export function photoAdder(page: { id: string; title: string }) {
  const add = async (files: File[]) => {
    const queued = uploads(files, page);
    if (typeof queued === "string") return toast(queued, "", undefined, 10000);
    try {
      await queue.addAll(queued);
    } catch (err) {
      return toast(`Not added: the phone refused to store it (${(err as Error).name}).`);
    }
    const n = holds(files); // as Capture and its queue say it (says.ts)
    toast(
      navigator.onLine
        ? `${n} added to the end of the page`
        : `${n} kept on the phone: added to the page when online`,
    );
  };
  return h(
    "div",
    { className: "bar", role: "group", "aria-label": "Add photo" },
    picker("Camera", true, (f) => void add(f), "add"),
    picker("Gallery", false, (f) => void add(f), "add"),
    picker("File", false, (f) => void add(f), "add", FILES),
  );
}
