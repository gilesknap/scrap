// Zoom and pan maths for the photo viewer: a screen point is (x + s * px, y + s * py)
// for an image pixel (px, py). Pure functions, so they are tested without a browser.
export interface View {
  s: number;
  x: number;
  y: number;
}
export interface Size {
  w: number;
  h: number;
}

/** The scale that shows the whole image, centred. */
export function fitView(img: Size, box: Size): View {
  const s = Math.min(box.w / img.w, box.h / img.h);
  return { s, x: (box.w - img.w * s) / 2, y: (box.h - img.h * s) / 2 };
}

/** Keep the image on screen: centred along an axis where it is smaller than the box,
 * else with no gap at either edge; and the scale between min and max. */
export function clamp(v: View, img: Size, box: Size, min: number, max: number): View {
  const s = Math.min(Math.max(v.s, min), max);
  const axis = (pos: number, len: number, room: number) =>
    len <= room ? (room - len) / 2 : Math.min(0, Math.max(room - len, pos));
  return { s, x: axis(v.x, img.w * s, box.w), y: axis(v.y, img.h * s, box.h) };
}

/** Scale to s, keeping the image point under (px, py) where it is. */
export function zoomTo(v: View, s: number, px: number, py: number): View {
  const k = s / v.s;
  return { s, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
}

export interface Fingers {
  x: number; // their midpoint
  y: number;
  d: number; // the distance between them
}

/** One step of a pinch from a to b: scale by the change in spread (kept between min
 * and max) about the old midpoint, then move with the midpoint. */
export function pinch(v: View, a: Fingers, b: Fingers, min: number, max: number): View {
  const s = Math.min(Math.max((v.s * b.d) / a.d, min), max);
  const z = zoomTo(v, s, a.x, a.y);
  return { s, x: z.x + b.x - a.x, y: z.y + b.y - a.y };
}
