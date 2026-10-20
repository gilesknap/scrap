// Pure helpers for drawings, kept apart from Excalidraw so unit tests need no browser.
//
// A drawing's coordinates are in its frame: the pixels of the JPEG that was sent to Claude
// (data.width x data.height). Fitting that frame, not the drawing's own bounds, to the box it
// is shown in lines the drawing up with the photo beside it, whatever the photo's size.

export interface Frame {
  width: number;
  height: number;
}

export interface Drawing {
  id: number;
  version: number;
  producer: string;
  author: string | null;
  created_at: string;
  current: boolean;
  restored_from: number | null;
  data: {
    format: "skeleton" | "scene";
    width?: number;
    height?: number;
    elements: Record<string, unknown>[];
    appState?: { viewBackgroundColor?: string };
  };
}

export type Version = Omit<Drawing, "data"> & { format: string };

/** The frame of a drawing, if it has a usable one. */
export function frameOf(data: Drawing["data"]): Frame | null {
  const { width: w, height: h } = data;
  return w && h && w > 0 && h > 0 ? { width: w, height: h } : null;
}

type Bind = { id: string; x?: number; y?: number };

/** Workaround for Excalidraw 0.18's convertToExcalidrawElements: an arrow bound (start or
 * end) to free text moves that text next to the arrow's end, unless the binding carries the
 * text's own x and y. */
export function pinTextBindings<T extends Record<string, unknown>>(elements: T[]): T[] {
  const texts = new Map<string, T>();
  for (const e of elements) if (e.type === "text" && typeof e.id === "string") texts.set(e.id, e);
  const pin = (b: unknown) => {
    const t = b ? texts.get((b as Bind).id) : undefined;
    return t ? { ...(b as Bind), x: t.x, y: t.y } : b;
  };
  return elements.map((e) =>
    e.start || e.end
      ? { ...e, ...(e.start ? { start: pin(e.start) } : {}), ...(e.end ? { end: pin(e.end) } : {}) }
      : e,
  );
}

/** Zoom and scroll (Excalidraw's appState) that fit the frame, centred, in a box of w x h
 * CSS pixels with a margin, leaving top and bottom clear (of Excalidraw's own toolbars).
 * Excalidraw draws scene point p at (p + scroll) * zoom. */
export function frameView(frame: Frame, w: number, h: number, margin = 8, top = 0, bottom = 0) {
  const room = h - top - bottom;
  const zoom = Math.max(
    0.1,
    Math.min((w - 2 * margin) / frame.width, (room - 2 * margin) / frame.height, 30),
  );
  return {
    zoom,
    scrollX: (w / zoom - frame.width) / 2,
    scrollY: (top + room / 2) / zoom - frame.height / 2,
  };
}

/** The viewBox that shows exactly the frame of an SVG Excalidraw exported with no padding:
 * its content is shifted so that the drawing's top-left bound (minX, minY) is at 0, 0. */
export const frameViewBox = (frame: Frame, minX: number, minY: number) =>
  `${-minX} ${-minY} ${frame.width} ${frame.height}`;

/** What PUT .../drawing takes: the elements still on the canvas, the frame, the background. */
export function scenePayload(
  elements: readonly { isDeleted?: boolean }[],
  frame: Frame | null,
  background = "#ffffff",
) {
  return {
    elements: elements.filter((e) => !e.isDeleted),
    appState: { viewBackgroundColor: background },
    ...frame,
  };
}

/** Who made a version, in words. */
export function madeBy(v: Pick<Version, "producer" | "author" | "restored_from">): string {
  const who = v.producer === "human" ? `edited by ${v.author ?? "you"}` : `drawn by ${v.producer}`;
  return v.restored_from ? `${who}, restored from v${v.restored_from}` : who;
}
