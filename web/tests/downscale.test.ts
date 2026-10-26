import { afterEach, describe, expect, it, vi } from "vitest";
import { fitEdge, getShrink, jpegName, SHRINK_KEY, shrink, shrinkAll } from "../src/downscale";

describe("fitEdge: the size to draw at", () => {
  it("scales a landscape photo by its width", () => {
    expect(fitEdge(4000, 3000)).toEqual([2560, 1920]);
  });
  it("scales a portrait photo by its height", () => {
    expect(fitEdge(3000, 4000)).toEqual([1920, 2560]);
  });
  it("scales a square one", () => {
    expect(fitEdge(3000, 3000)).toEqual([2560, 2560]);
  });
  it("leaves one at exactly 2560, or under, alone", () => {
    expect(fitEdge(2560, 1440)).toBeNull();
    expect(fitEdge(1440, 2560)).toBeNull();
    expect(fitEdge(2000, 1000)).toBeNull();
  });
  it("never makes a side less than a pixel, and refuses nonsense", () => {
    expect(fitEdge(100_000, 10)).toEqual([2560, 1]);
    expect(fitEdge(0, 5000)).toBeNull();
    expect(fitEdge(Number.NaN, 5000)).toBeNull();
  });
});

it("names a made-smaller photo .jpg unless it is one already", () => {
  expect(jpegName("IMG_1.jpg")).toBe("IMG_1.jpg");
  expect(jpegName("IMG_1.JPEG")).toBe("IMG_1.JPEG");
  expect(jpegName("IMG_1.heic")).toBe("IMG_1.jpg");
  expect(jpegName("shot")).toBe("shot.jpg");
});

describe("shrink", () => {
  const close = vi.fn();
  const photo = (size = 5000, type = "image/jpeg") =>
    new File([new Uint8Array(size)], "a.jpg", { type, lastModified: 1234 });
  /** A browser with a w x h decoder and an encoder giving `out` bytes (or throwing). */
  function browser(w: number, h: number, out: number | Error) {
    const draw = vi.fn();
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(async () => ({ width: w, height: h, close })),
    );
    class Off {
      constructor(
        public width: number,
        public height: number,
      ) {}
      getContext = () => ({ drawImage: draw, fillRect() {}, fillStyle: "" });
      convertToBlob = async () => {
        if (out instanceof Error) throw out;
        return new Blob([new Uint8Array(out)], { type: "image/jpeg" });
      };
    }
    vi.stubGlobal("OffscreenCanvas", Off);
    return draw;
  }
  afterEach(() => {
    vi.unstubAllGlobals();
    close.mockClear();
  });

  it("encodes a big photo smaller, keeping its name and time", async () => {
    const draw = browser(4000, 3000, 900);
    const f = photo();
    const out = await shrink(f);
    expect(out).not.toBe(f);
    expect(out.size).toBe(900);
    expect(out.type).toBe("image/jpeg");
    expect(out.name).toBe("a.jpg");
    expect(out.lastModified).toBe(1234);
    expect(draw).toHaveBeenCalledWith(expect.anything(), 0, 0, 2560, 1920);
    expect(createImageBitmap).toHaveBeenCalledWith(f, { imageOrientation: "from-image" });
    expect(close).toHaveBeenCalled();
  });

  it("keeps the original at or under 2560 px", async () => {
    browser(2560, 1000, 10);
    const f = photo();
    expect(await shrink(f)).toBe(f);
  });

  it("keeps the original that the browser cannot decode", async () => {
    browser(4000, 3000, 10);
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new Error("undecodable")));
    const f = photo(5000, "image/heic");
    expect(await shrink(f)).toBe(f);
  });

  it("keeps PNG, GIF and other types, without decoding them", async () => {
    browser(4000, 3000, 10);
    for (const type of ["image/png", "image/gif", "image/svg+xml"]) {
      const f = photo(5000, type);
      expect(await shrink(f)).toBe(f);
    }
    expect(createImageBitmap).not.toHaveBeenCalled();
    for (const type of ["image/jpeg", "image/heic", "image/heif", "image/webp"])
      expect((await shrink(photo(5000, type))).size).toBe(10);
  });

  it("keeps a file that is not an image, without decoding it", async () => {
    browser(4000, 3000, 10);
    const f = photo(5000, "application/pdf");
    expect(await shrink(f)).toBe(f);
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  it("keeps the original if encoding throws", async () => {
    browser(4000, 3000, new Error("no memory"));
    const f = photo();
    expect(await shrink(f)).toBe(f);
    expect(close).toHaveBeenCalled();
  });

  it("keeps the original if the result is not smaller", async () => {
    browser(4000, 3000, 5000);
    const f = photo(5000);
    expect(await shrink(f)).toBe(f);
  });

  it("keeps the original in a browser with no createImageBitmap", async () => {
    vi.stubGlobal("createImageBitmap", undefined);
    const f = photo();
    expect(await shrink(f)).toBe(f);
  });
});

describe("shrinkAll and the setting", () => {
  afterEach(() => vi.unstubAllGlobals());
  const store = (v: string | null) =>
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => (k === SHRINK_KEY ? v : null),
      setItem() {},
      removeItem() {},
    });
  const capture = (blob: Blob) => ({ source: "pwa" as const, files: [{ name: "a.jpg", blob }] });

  it("is on unless turned off", () => {
    store(null);
    expect(getShrink()).toBe(true);
    store("off");
    expect(getShrink()).toBe(false);
  });

  it("leaves everything alone when off", async () => {
    store("off");
    const cs = [capture(new File([new Uint8Array(9)], "a.jpg", { type: "image/jpeg" }))];
    expect(await shrinkAll(cs)).toBe(cs);
  });

  it("decodes one photo at a time, closing each bitmap before the next", async () => {
    store(null);
    let open = 0;
    let most = 0;
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(async () => {
        open++;
        most = Math.max(most, open);
        await new Promise((r) => setTimeout(r, 5));
        return { width: 4000, height: 3000, close: () => void open-- };
      }),
    );
    vi.stubGlobal(
      "OffscreenCanvas",
      class {
        getContext = () => ({ drawImage() {}, fillRect() {}, fillStyle: "" });
        convertToBlob = async () => new Blob([new Uint8Array(10)]);
      },
    );
    const f = () => new File([new Uint8Array(5000)], "a.jpg", { type: "image/jpeg" });
    const out = await shrinkAll([
      {
        source: "pwa",
        files: [
          { name: "a", blob: f() },
          { name: "b", blob: f() },
        ],
      },
      { source: "pwa", files: [{ name: "c", blob: f() }] },
    ]);
    expect(most).toBe(1);
    expect(out.flatMap((c) => c.files.map((x) => x.blob.size))).toEqual([10, 10, 10]);
  });

  it("passes on what is not a File, and text-only captures", async () => {
    store(null);
    const blob = new Blob([new Uint8Array(9)]);
    const [c, t] = await shrinkAll([capture(blob), { source: "pwa", text: "hi", files: [] }]);
    expect(c.files[0].blob).toBe(blob);
    expect(t.files).toEqual([]);
  });
});
