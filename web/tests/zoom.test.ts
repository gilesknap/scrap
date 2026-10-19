import { describe, expect, it } from "vitest";
import { clamp, fitView, pinch, zoomTo } from "../src/zoom";

const box = { w: 400, h: 800 };
const img = { w: 4000, h: 3000 }; // landscape photo on a portrait phone

describe("zoom maths", () => {
  it("fits the whole image, centred", () => {
    expect(fitView(img, box)).toEqual({ s: 0.1, x: 0, y: 250 });
    expect(fitView({ w: 100, h: 100 }, box)).toEqual({ s: 4, x: 0, y: 200 }); // small: scaled up
  });

  it("zooms about a point, which stays put", () => {
    const v = zoomTo({ s: 0.1, x: 0, y: 250 }, 0.5, 200, 400);
    // the image pixel that was under (200, 400) is still there
    expect((200 - v.x) / v.s).toBeCloseTo((200 - 0) / 0.1);
    expect((400 - v.y) / v.s).toBeCloseTo((400 - 250) / 0.1);
  });

  it("clamps scale and keeps the image on screen", () => {
    expect(clamp({ s: 0.01, x: 50, y: 0 }, img, box, 0.1, 1)).toEqual({ s: 0.1, x: 0, y: 250 });
    expect(clamp({ s: 5, x: 0, y: 0 }, img, box, 0.1, 1).s).toBe(1);
    // zoomed in: no gap at any edge
    const v = clamp({ s: 1, x: 100, y: -9999 }, img, box, 0.1, 1);
    expect(v).toEqual({ s: 1, x: 0, y: 800 - 3000 });
    expect(clamp({ s: 1, x: -9999, y: 10 }, img, box, 0.1, 1).x).toBe(400 - 4000);
  });

  it("pinches: spread scales, midpoint pans, within limits", () => {
    const v = { s: 0.1, x: 0, y: 250 };
    const a = { x: 200, y: 400, d: 100 };
    const b = { x: 210, y: 400, d: 200 };
    const out = pinch(v, a, b, 0.1, 1);
    expect(out.s).toBeCloseTo(0.2);
    expect(out.x).toBeCloseTo(200 - (200 - 0) * 2 + 10);
    expect(pinch(v, a, { ...a, d: 10_000 }, 0.1, 1).s).toBe(1);
    expect(pinch(v, a, { ...a, d: 1 }, 0.1, 1).s).toBe(0.1);
  });
});
