// A photo's Excalidraw drawing on the page: a static preview that behaves like an image (it
// scrolls with the page and takes no gestures). Tapping it opens the full-screen viewer, where
// it can be zoomed, panned and edited (board/viewer.ts). Excalidraw and React are in that
// separate chunk, fetched only when a preview comes into view or the viewer opens.
import { ApiError, api } from "./api";
import type { Drawing, Frame } from "./board/frame";
import { h, toast } from "./ui";

type Chunk = typeof import("./board/excalidraw");
let chunk: Promise<Chunk> | null = null;

/** The viewer's chunk, fetched once; a failure (offline) is retried on the next call. */
export function loadBoard(): Promise<Chunk> {
  // Fonts come from scrap, not Excalidraw's CDN (see vite.config.ts)
  (window as unknown as { EXCALIDRAW_ASSET_PATH: string }).EXCALIDRAW_ASSET_PATH = "/excalidraw/";
  chunk ??= import("./board/excalidraw").catch((e) => {
    chunk = null;
    throw e;
  });
  return chunk;
}

export interface Target {
  cid: string; // capture
  sha: string; // photo
  name: string; // to label it
  photo: string; // URL of the photo's preview
  slug: string; // for export file names
}

const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;

// Rendered previews by drawing version and theme, kept while the app is open
const previews = new Map<string, SVGSVGElement>();

/** The preview: framed like the photo (frame known from the page, so no layout shift),
 * rendered when it nears the screen. A tap opens the viewer. */
export function drawingCard(
  t: Target,
  d: { id: number; frame: Frame | null },
  open: () => void,
): HTMLElement {
  const status = h("span", { className: "drawing-status" }, "Loading drawing…");
  const card = h(
    "button",
    {
      type: "button",
      className: "drawing-card",
      "aria-label": `Open the drawing of ${t.name || "this photo"}`,
      onclick: open,
    },
    status,
  );
  if (d.frame) card.style.aspectRatio = `${d.frame.width} / ${d.frame.height}`;
  const key = `${d.id}:${dark() ? "dark" : "light"}`;
  const show = (svg: SVGSVGElement) => {
    card.replaceChildren(svg.cloneNode(true));
    card.classList.add("ready");
  };
  const render = async () => {
    status.textContent = "Loading drawing…";
    card.classList.remove("failed");
    try {
      const board = await loadBoard();
      const drawing = await api<Drawing>(`captures/${t.cid}/photos/${t.sha}/drawing`);
      const svg = await board.preview(drawing.data);
      previews.set(key, svg);
      show(svg);
    } catch {
      card.classList.add("failed");
      status.textContent = navigator.onLine
        ? "Can't show the drawing here: tap to open it"
        : "Offline: the drawing needs the server";
    }
  };
  const kept = previews.get(key);
  if (kept) show(kept);
  else if ("IntersectionObserver" in window) {
    const seen = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        seen.disconnect();
        void render();
      },
      { rootMargin: "300px" },
    );
    seen.observe(card);
  } else void render();
  return card;
}

/** Open the full-screen viewer. onSaved is told of a new current version (a save or a
 * Restore), to refresh the page. */
export async function openDrawing(t: Target, onSaved: () => void) {
  try {
    (await loadBoard()).openDrawing(t, onSaved);
  } catch (err) {
    toast(
      err instanceof ApiError
        ? err.message
        : "Can't open the drawing: the viewer needs the server (offline?)",
    );
  }
}
