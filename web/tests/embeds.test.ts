import { describe, expect, it } from "vitest";
import { expand, found, tokenise } from "../src/embeds";

const sha = (c: string) => c.repeat(64);
const img = (c: string, alt = "") => `![${alt}](/api/blobs/${sha(c)}/preview?size=2048)`;
const file = (c: string, name: string) => `[${name}](/api/blobs/${sha(c)})`;

/** tokenise, then expand what it gave: the body again, byte for byte. */
const round = (body: string) => {
  const { text, embeds } = tokenise(body);
  return expand(text, embeds);
};

describe("the editor's embed tokens", () => {
  it("shows an image as a token, and gives its Markdown back", () => {
    const body = img("a");
    const { text, embeds } = tokenise(body);
    expect(text).toBe("⟦image 1⟧");
    expect(embeds).toMatchObject([{ token: "⟦image 1⟧", md: body, sha: sha("a"), image: true }]);
    expect(embeds[0].label).toBe("Image 1"); // no alt text
    expect(round(body)).toBe(body);
  });

  it("numbers images and files apart, among text, and round-trips them", () => {
    const body = `Trip notes\n\n${img("a", "beach")}\n\nsee ${file("b", "scan.pdf")} and ${file("c", "bill.pdf")}\n`;
    const { text, embeds } = tokenise(body);
    expect(text).toBe("Trip notes\n\n⟦image 1⟧\n\nsee ⟦file 1: scan.pdf⟧ and ⟦file 2: bill.pdf⟧\n");
    expect(embeds.map((e) => [e.image, e.n, e.label])).toEqual([
      [true, 1, "beach"],
      [false, 1, "scan.pdf"],
      [false, 2, "bill.pdf"],
    ]);
    expect(round(body)).toBe(body);
  });

  it("gives two images two tokens, even of the same file", () => {
    const body = `${img("a")}\n${img("a")}\n${img("d")}`;
    const { text, embeds } = tokenise(body);
    expect(text).toBe("⟦image 1⟧\n⟦image 2⟧\n⟦image 3⟧");
    expect(embeds).toHaveLength(3);
    expect(round(body)).toBe(body);
  });

  it("keeps an image in a list item where it is", () => {
    const body = `- [ ] print this\n  ${img("a", "map")}\n- done`;
    expect(tokenise(body).text).toBe("- [ ] print this\n  ⟦image 1⟧\n- done");
    expect(round(body)).toBe(body);
  });

  it("keeps a file's download link and a short preview size, byte for byte", () => {
    const body = `[a.zip](/api/blobs/${sha("e")}?download=1) ![x](/api/blobs/${sha("f")}/preview?size=512)`;
    expect(round(body)).toBe(body);
  });

  it("leaves a token already typed in the page as text, and numbers past it", () => {
    const body = `I wrote ⟦image 1⟧ myself\n${img("a")}`;
    const { text, embeds } = tokenise(body);
    expect(text).toBe("I wrote ⟦image 1⟧ myself\n⟦image 2⟧");
    expect(embeds.map((e) => e.token)).toEqual(["⟦image 2⟧"]);
    expect(expand(text, embeds)).toBe(body);
  });

  it("drops brackets from a file's name and shortens a long one", () => {
    const long = `${"a".repeat(40)}.pdf`;
    const { text } = tokenise(`${file("a", "x⟦y⟧.pdf")} ${file("b", long)}`);
    expect(text).toBe(`⟦file 1: xy.pdf⟧ ⟦file 2: ${"a".repeat(31)}…⟧`);
  });

  it("removes exactly the embed whose token was deleted", () => {
    const body = `a ${img("a")} b ${img("b")} c ${file("c", "f.pdf")}`;
    const { text, embeds } = tokenise(body);
    const cut = text.replace("⟦image 2⟧", "");
    expect(expand(cut, embeds)).toBe(`a ${img("a")} b  c ${file("c", "f.pdf")}`);
    expect(found(cut, embeds).map((f) => f.embed.token)).toEqual(["⟦image 1⟧", "⟦file 1: f.pdf⟧"]);
  });

  it("does not expand a mangled token: what is left stays as typed", () => {
    const { text, embeds } = tokenise(`x ${img("a")} y`);
    for (const bad of ["⟦image 1", "⟦imag 1⟧", "⟦image 12⟧", "⟦ image 1⟧", "image 1⟧"]) {
      const mangled = text.replace("⟦image 1⟧", bad);
      expect(expand(mangled, embeds)).toBe(`x ${bad} y`);
    }
  });

  it("finds tokens in order, a pasted one twice, with where they are", () => {
    const { text, embeds } = tokenise(`${img("a")} ${file("b", "f.pdf")}`);
    const twice = `${text} ⟦image 1⟧`;
    expect(found(twice, embeds).map((f) => [f.embed.token, f.at])).toEqual([
      ["⟦image 1⟧", 0],
      ["⟦file 1: f.pdf⟧", 10],
      ["⟦image 1⟧", 26],
    ]);
  });

  it("leaves text without scrap's own files alone", () => {
    const body = "![ext](https://example.com/a.png) [doc](/api/blobs/short)";
    expect(tokenise(body)).toEqual({ text: body, embeds: [] });
  });
});
