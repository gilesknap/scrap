// An SVG shared as a PNG (#486): many share targets (messaging apps) refuse SVG, so Share draws
// it on a canvas first. Part of the sharing chunk (sharing.ts imports it).
export const SVG = "image/svg+xml";
const MAX = 2048; // the longest side, as the JPEG previews
const MIN = 1024; // a small diagram is drawn larger: it is vector, so it stays sharp

/** The size to draw a width x height SVG at: its longest side within MIN..MAX px, never a side
 * under 1 px. null if the size is not usable. */
export function pngSize(width: number, height: number): [number, number] | null {
  if (!(width > 0 && height > 0)) return null;
  const long = Math.max(width, height);
  const k = Math.min(MAX, Math.max(MIN, long)) / long;
  return [Math.max(1, Math.round(width * k)), Math.max(1, Math.round(height * k))];
}

/** The name with its extension (if any) replaced by ext. */
export const withExt = (name: string, ext: string) => `${name.replace(/\.[^./]*$/, "")}.${ext}`;

/** The SVG's own size: its width and height in px, else its viewBox's. */
function ownSize(text: string, img: HTMLImageElement): [number, number] {
  const root = new DOMParser().parseFromString(text, SVG).documentElement;
  const px = (a: string) => {
    const v = root.getAttribute(a)?.trim() ?? "";
    return /^[\d.]+(px)?$/.test(v) ? Number.parseFloat(v) : 0;
  };
  const box = (root.getAttribute("viewBox") ?? "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  const w = px("width") || box[2] || img.naturalWidth;
  const h = px("height") || box[3] || img.naturalHeight;
  return [w, h];
}

/** Draw the SVG on white (a transparent diagram stays legible on a dark chat) as a PNG. */
async function draw(svg: Blob): Promise<Blob> {
  const url = URL.createObjectURL(svg);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const size = pngSize(...ownSize(await svg.text(), img));
    if (!size) throw new Error("no size");
    const [w, h] = size;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const g = canvas.getContext("2d");
    if (!g) throw new Error("no 2d context");
    g.fillStyle = "#fff";
    g.fillRect(0, 0, w, h);
    g.drawImage(img, 0, 0, w, h);
    const png = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/png"));
    if (!png) throw new Error("no PNG");
    return png;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** An SVG file as a PNG named <base>.png; if it can't be drawn, the SVG named <base>.svg. */
export async function svgAsPng(file: File): Promise<File> {
  try {
    return new File([await draw(file)], withExt(file.name, "png"), { type: "image/png" });
  } catch {
    return new File([file], withExt(file.name, "svg"), { type: SVG });
  }
}
