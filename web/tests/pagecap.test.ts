import { describe, expect, it } from "vitest";
import { embedBytes, tooLong } from "../src/pagecap";

const MAX = 1_000_000;

describe("the page size check", () => {
  it("allows exactly the limit and refuses a byte more, in bytes", () => {
    expect(tooLong("x".repeat(MAX))).toBeNull();
    expect(tooLong("x".repeat(MAX + 1))).toBe(
      "Not saved: the text is 1,000,001 bytes, and a page holds at most 1,000,000 (1 MB)",
    );
  });

  it("counts bytes, not characters", () => {
    expect(tooLong("é".repeat(MAX / 2 + 1))).toContain("1,000,002 bytes");
  });

  it("lets an unchanged oversized body through", () => {
    expect(tooLong("x".repeat(MAX + 10), 0, true)).toBeNull();
  });

  it("counts the embeds the server adds for photos, and the links for files (#403)", () => {
    const image = { type: "image/jpeg" };
    const pdf = { type: "application/pdf", name: "minutes.pdf" }; // [minutes.pdf](/api/blobs/<64>)
    expect(embedBytes([image, image, pdf])).toBe(200 + 90);
    expect(embedBytes([{ type: "" }])).toBe(100);
    expect(embedBytes([{ type: "text/plain", name: "é".repeat(30) }])).toBe(79 + 60);
    const text = "x".repeat(MAX - 150);
    expect(tooLong(text)).toBeNull();
    expect(tooLong(text, embedBytes([image, image]))).toContain("bytes");
  });
});
