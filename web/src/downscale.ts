// Photos are made smaller on the phone before they are queued (#89): a big photo holds the
// one connection while it uploads, and ingest rescales to 2048 px anyway. A lazy chunk, loaded
// by the queue when something is added. Anything it cannot improve goes up as it was.
import { kept } from "./api";
import type { Capture } from "./queue";

export const MAX_EDGE = 2560;
const QUALITY = 0.85;
/** The types that are made smaller: photos, not PNG (screenshots, drawings), GIF or the rest. */
const SHRUNK = new Set(["image/jpeg", "image/heic", "image/heif", "image/webp"]);
export const SHRINK_KEY = "scrap.shrink_photos";

/** Whether photos are made smaller (Settings; on unless turned off). */
export const getShrink = () => kept(SHRINK_KEY) !== "off";
export const setShrink = (on: boolean) => void kept(SHRINK_KEY, on ? null : "off");

/** The size to draw a width x height photo at so its long edge is at most max: null if it
 * already is (or the size is not usable). Never a side under 1 px. */
export function fitEdge(width: number, height: number, max = MAX_EDGE): [number, number] | null {
  if (!(width > 0 && height > 0) || Math.max(width, height) <= max) return null;
  const k = max / Math.max(width, height);
  return [Math.max(1, Math.round(width * k)), Math.max(1, Math.round(height * k))];
}

/** Draw on white: JPEG has no transparency (a PNG's would go black). */
function paint(
  g: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null,
  bitmap: ImageBitmap,
  w: number,
  h: number,
) {
  if (!g) throw new Error("no 2d context");
  g.fillStyle = "#fff";
  g.fillRect(0, 0, w, h);
  g.drawImage(bitmap, 0, 0, w, h);
}

/** The name with a .jpg ending, unless it has one (.jpeg too) already. */
export const jpegName = (name: string) =>
  /\.jpe?g$/i.test(name) ? name : `${name.replace(/\.[A-Za-z0-9]{1,5}$/, "")}.jpg`;

/** The photo as a JPEG (canvas output is sRGB: a wide-gamut profile is not kept). */
async function encode(bitmap: ImageBitmap, w: number, h: number): Promise<Blob | null> {
  if (typeof OffscreenCanvas !== "undefined") {
    const canvas = new OffscreenCanvas(w, h);
    paint(canvas.getContext("2d"), bitmap, w, h);
    return canvas.convertToBlob({ type: "image/jpeg", quality: QUALITY });
  }
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  paint(canvas.getContext("2d"), bitmap, w, h);
  return new Promise((done) => canvas.toBlob(done, "image/jpeg", QUALITY));
}

/** The file made smaller, or the file itself: when it is not a photo type the browser can
 * decode, is within the limit already, would not get smaller, or anything throws. Keeps the
 * name and the last-modified time (the capture time). */
export async function shrink(file: File): Promise<File> {
  if (!SHRUNK.has(file.type) || typeof createImageBitmap === "undefined") return file;
  let bitmap: ImageBitmap | undefined;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const size = fitEdge(bitmap.width, bitmap.height);
    if (!size) return file;
    const out = await encode(bitmap, size[0], size[1]);
    if (!out || out.size >= file.size) return file;
    return new File([out], jpegName(file.name), {
      type: "image/jpeg",
      lastModified: file.lastModified,
    });
  } catch {
    return file;
  } finally {
    bitmap?.close();
  }
}

/** The captures with their photos made smaller (if the setting is on). One photo at a time:
 * a decoded bitmap is big, and is closed before the next is decoded. */
export async function shrinkAll(cs: Capture[]): Promise<Capture[]> {
  if (!getShrink()) return cs;
  const out: Capture[] = [];
  for (const c of cs) {
    const files: Capture["files"] = [];
    for (const f of c.files)
      files.push(f.blob instanceof File ? { ...f, blob: await shrink(f.blob) } : f);
    out.push({ ...c, files });
  }
  return out;
}
