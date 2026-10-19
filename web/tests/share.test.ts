import { describe, expect, it } from "vitest";
import { shareable } from "../src/api";
import { dispositionName } from "../src/ui";

const SHA = "ab".repeat(32);
const file = (mime: string, size = 1000, filename: string | null = "IMG_1.jpg") => ({
  sha256: SHA,
  mime,
  size,
  filename,
});

describe("sharing", () => {
  it("shares an original other apps can read, else the JPEG preview", () => {
    const blob = `/api/blobs/${SHA}`;
    const preview = `${blob}/preview?size=2048`;
    expect(shareable(file("image/jpeg"))).toEqual([blob, "IMG_1.jpg", "image/jpeg"]);
    expect(shareable(file("image/heic", 1000, "IMG_2.HEIC"))).toEqual([
      preview,
      "IMG_2.jpg",
      "image/jpeg",
    ]);
    expect(shareable(file("image/jpeg", 30 * 2 ** 20))[0]).toBe(preview);
    expect(shareable(file("image/png", 10, null))).toEqual([
      blob,
      `${SHA.slice(0, 12)}.png`,
      "image/png",
    ]);
  });

  it("names a file with its type's extension", () => {
    expect(shareable(file("image/jpeg", 10, "scan"))[1]).toBe("scan.jpg");
    expect(shareable(file("image/jpeg", 10, "a.JPEG"))[1]).toBe("a.JPEG");
    expect(shareable(file("image/png", 10, "photo.jpeg.txt"))[1]).toBe("photo.jpeg.txt.png");
    expect(shareable(file("image/webp", 10, "w.webp"))[1]).toBe("w.webp");
  });

  it("reads the server's file name", () => {
    expect(dispositionName(`attachment; filename="a_b.md"; filename*=UTF-8''a%C3%A9.md`)).toBe(
      "aé.md",
    );
    expect(dispositionName('attachment; filename="x.zip"')).toBe("x.zip");
    expect(dispositionName("")).toBeUndefined();
  });
});
