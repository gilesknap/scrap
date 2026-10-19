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
    expect(shareable(file("image/jpeg"))).toEqual([`/api/blobs/${SHA}`, "IMG_1.jpg"]);
    expect(shareable(file("image/heic", 1000, "IMG_2.HEIC"))).toEqual([
      `/api/blobs/${SHA}/preview?size=2048`,
      "IMG_2.jpg",
    ]);
    expect(shareable(file("image/jpeg", 30 * 2 ** 20))[0]).toContain("/preview");
    expect(shareable(file("image/png", 10, null))).toEqual([
      `/api/blobs/${SHA}`,
      `${SHA.slice(0, 12)}.png`,
    ]);
  });

  it("reads the server's file name", () => {
    expect(dispositionName(`attachment; filename="a_b.md"; filename*=UTF-8''a%C3%A9.md`)).toBe(
      "aé.md",
    );
    expect(dispositionName('attachment; filename="x.zip"')).toBe("x.zip");
    expect(dispositionName("")).toBeUndefined();
  });
});
