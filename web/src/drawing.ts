// A photo's Excalidraw drawing on the page: a static preview that behaves like an image (it
// scrolls with the page and takes no gestures). Tapping it opens the full-screen viewer, where
// it can be zoomed, panned and edited (board/viewer.ts). Excalidraw and React are in that
// separate chunk, fetched only when a preview comes into view or the viewer opens.
import { ApiError, api } from "./api";
import type { Drawing, Frame } from "./board/frame";
import { currentDrawings, onTheme } from "./theme";
import { h, toast } from "./ui";

// Fonts come from scrap, not Excalidraw's CDN (see vite.config.ts). Set when this module loads,
// before any Excalidraw code can.
(window as unknown as { EXCALIDRAW_ASSET_PATH: string }).EXCALIDRAW_ASSET_PATH = "/excalidraw/";

type Chunk = typeof import("./board/excalidraw");
let chunk: Promise<Chunk> | null = null;

/** The viewer's chunk, fetched once; a failure (offline) is retried on the next call. */
function loadBoard(): Promise<Chunk> {
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
  if (d.frame) {
    card.style.aspectRatio = `${d.frame.width} / ${d.frame.height}`;
    card.style.setProperty("--ratio", String(d.frame.width / d.frame.height)); // for the height cap
  }
  let key = "";
  const show = (svg: SVGSVGElement) => {
    card.replaceChildren(svg.cloneNode(true));
    card.classList.remove("failed");
    card.classList.add("ready");
  };
  // Back to the loading state: the old variant must not sit on the new paper
  const loading = () => {
    status.textContent = "Loading drawing…";
    card.replaceChildren(status);
    card.classList.remove("ready", "failed");
  };
  const render = async () => {
    const mine = key;
    const theme = currentDrawings();
    loading();
    try {
      const board = await loadBoard();
      const drawing = await api<Drawing>(`captures/${t.cid}/photos/${t.sha}/drawing`);
      const svg = await board.preview(drawing.data, theme);
      previews.set(mine, svg);
      if (mine === key) show(svg);
    } catch {
      if (mine !== key) return;
      card.classList.add("failed");
      status.textContent = navigator.onLine
        ? "Can't show the drawing here: tap to open it"
        : "Offline: the drawing needs the server";
    }
  };
  let seen: IntersectionObserver | null = null;
  const update = () => {
    const theme = currentDrawings();
    card.dataset.scheme = theme;
    key = `${d.id}:${theme}`;
    seen?.disconnect();
    const kept = previews.get(key);
    if (kept) show(kept);
    else {
      loading();
      watch();
    }
  };
  const watch = () => {
    if (!("IntersectionObserver" in window)) void render();
    else {
      seen = new IntersectionObserver(
        (entries) => {
          if (!entries.some((e) => e.isIntersecting)) return;
          seen?.disconnect();
          void render();
        },
        { rootMargin: "300px" },
      );
      seen.observe(card);
    }
  };
  update();
  // A theme change draws it again, until the page it is on is gone
  const off = onTheme(() => (card.isConnected ? update() : off()));
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
