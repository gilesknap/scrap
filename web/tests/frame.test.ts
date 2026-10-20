import { describe, expect, it } from "vitest";
import {
  frameOf,
  frameView,
  frameViewBox,
  madeBy,
  pinTextBindings,
  scenePayload,
} from "../src/board/frame";

describe("pinTextBindings", () => {
  it("gives a binding to free text that text's own position", () => {
    const els = [
      { type: "text", id: "t", x: 100, y: 200, text: "note" },
      { type: "rectangle", id: "r", x: 0, y: 0, width: 10, height: 10 },
      { type: "arrow", x: 5, y: 5, points: [], start: { id: "r" }, end: { id: "t" } },
    ];
    const out = pinTextBindings(els);
    expect(out[2].start).toEqual({ id: "r" }); // a shape: left alone
    expect(out[2].end).toEqual({ id: "t", x: 100, y: 200 });
    expect(out[0]).toBe(els[0]); // nothing else is copied or changed
    expect(els[2].end).toEqual({ id: "t" });
  });

  it("leaves arrows to nothing as they are", () => {
    const els = [{ type: "arrow", x: 0, y: 0, start: { id: "gone" } }];
    expect(pinTextBindings(els)[0].start).toEqual({ id: "gone" });
  });
});

describe("frameView", () => {
  it("fits a 4:3 frame in a portrait box, centred", () => {
    const v = frameView({ width: 2048, height: 1536 }, 390, 700, 0);
    expect(v.zoom).toBeCloseTo(390 / 2048);
    expect(v.scrollX).toBeCloseTo(0);
    // the frame's middle is the box's middle: (1536 / 2 + scrollY) * zoom = 350
    expect((768 + v.scrollY) * v.zoom).toBeCloseTo(350);
  });

  it("keeps a margin and sane zoom limits", () => {
    const v = frameView({ width: 100, height: 100 }, 116, 116, 8);
    expect(v.zoom).toBeCloseTo(1);
    expect(frameView({ width: 1, height: 1 }, 5000, 5000).zoom).toBe(30);
    expect(frameView({ width: 1e6, height: 1e6 }, 10, 10).zoom).toBe(0.1);
  });

  it("leaves room for tool bars above and below", () => {
    const v = frameView({ width: 400, height: 300 }, 1000, 472, 0, 72, 100);
    expect(v.zoom).toBeCloseTo(1); // 300 px of room
    expect(v.scrollY * v.zoom).toBeCloseTo(72); // the frame's top just below the top bar
  });
});

describe("frames and payloads", () => {
  it("knows a usable frame", () => {
    expect(frameOf({ format: "skeleton", width: 800, height: 600, elements: [] })).toEqual({
      width: 800,
      height: 600,
    });
    expect(frameOf({ format: "scene", elements: [] })).toBeNull();
    expect(frameOf({ format: "scene", width: 0, height: 5, elements: [] })).toBeNull();
  });

  it("shows exactly the frame of an unpadded export", () => {
    expect(frameViewBox({ width: 800, height: 600 }, 120, -30)).toBe("-120 30 800 600");
  });

  it("saves the elements still on the canvas, with the frame", () => {
    const out = scenePayload([{ isDeleted: true }, { isDeleted: false }, {}], {
      width: 8,
      height: 6,
    });
    expect(out).toEqual({
      elements: [{ isDeleted: false }, {}],
      appState: { viewBackgroundColor: "#ffffff" },
      width: 8,
      height: 6,
    });
    expect(scenePayload([], null, "#000")).toEqual({
      elements: [],
      appState: { viewBackgroundColor: "#000" },
    });
  });

  it("says who made a version", () => {
    const by = (producer: string, author: string | null, restored_from: number | null = null) =>
      madeBy({ producer, author, restored_from });
    expect(by("claude-opus-5-5", null)).toBe("drawn by claude-opus-5-5");
    expect(by("human", "me@example.com")).toBe("edited by me@example.com");
    expect(by("human", null, 2)).toBe("edited by you, restored from v2");
  });
});
