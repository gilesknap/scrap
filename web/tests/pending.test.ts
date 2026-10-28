// The composer's photos and files as tokens in its text (#403): pending.ts.
import { describe, expect, it } from "vitest";
import { tokenise } from "../src/embeds";
import { pend, placeAt, placed, wire } from "../src/pending";

const photo = (name = "IMG_1.jpg") => new File(["p"], name, { type: "image/jpeg" });
const pdf = (name = "minutes.pdf") => new File(["%PDF"], name, { type: "application/pdf" });
const md = (name = "notes.md") => new File(["# n"], name, { type: "" }); // a phone's, untyped

describe("pend", () => {
  it("numbers images and files apart, as the editor does", () => {
    const a = pend(photo(), [], "");
    const b = pend(pdf(), [a], "");
    const c = pend(photo(), [a, b], "");
    const d = pend(md(), [a, b, c], "");
    expect([a, b, c, d].map((e) => e.token)).toEqual([
      "⟦image 1⟧",
      "⟦file 1: minutes.pdf⟧",
      "⟦image 2⟧",
      "⟦file 2: notes.md⟧",
    ]);
    expect([a.label, b.label, a.image, d.image, a.md]).toEqual([
      "Image 1",
      "minutes.pdf",
      true,
      false,
      "⟦image 1⟧",
    ]);
  });

  it("skips a number the text or a stored embed already has", () => {
    const sha = "a".repeat(64);
    const { text, embeds } = tokenise(`![](/api/blobs/${sha}/preview?size=2048) ⟦image 2⟧`);
    expect(pend(photo(), embeds, text).token).toBe("⟦image 3⟧");
  });

  it("keeps a draft's token, and takes brackets out of a name", () => {
    const e = pend(pdf(), [], "", "⟦file 4: minutes.pdf⟧");
    expect([e.token, e.n]).toEqual(["⟦file 4: minutes.pdf⟧", 4]);
    expect(pend(pdf("a⟦b⟧.pdf"), [], "").token).toBe("⟦file 1: ab.pdf⟧");
  });
});

describe("placeAt", () => {
  const put = (text: string, at: number, tokens: string[], to = at) => {
    const c = placeAt(text, at, to, tokens);
    const out = text.slice(0, c.from) + c.insert + text.slice(c.to);
    return [out, out.slice(0, c.start)];
  };

  it("puts each token in a paragraph of its own, the caret after", () => {
    expect(put("", 0, ["⟦image 1⟧"])).toEqual(["⟦image 1⟧\n\n", "⟦image 1⟧\n\n"]);
    expect(put("abc", 3, ["⟦image 1⟧", "⟦image 2⟧"])).toEqual([
      "abc\n\n⟦image 1⟧\n\n⟦image 2⟧\n\n",
      "abc\n\n⟦image 1⟧\n\n⟦image 2⟧\n\n",
    ]);
    expect(put("abcdef", 3, ["⟦file 1: a.pdf⟧"])[0]).toBe("abc\n\n⟦file 1: a.pdf⟧\n\ndef");
    expect(put("abc\n\ndef", 5, ["⟦image 1⟧"])[0]).toBe("abc\n\n⟦image 1⟧\n\ndef");
    expect(put("abc\ndef", 4, ["⟦image 1⟧"])[0]).toBe("abc\n\n⟦image 1⟧\n\ndef");
    expect(put("abc\n", 4, ["⟦image 1⟧"])[0]).toBe("abc\n\n⟦image 1⟧\n\n");
  });

  it("replaces what is selected", () => {
    expect(put("one TWO three", 4, ["⟦image 1⟧"], 7)[0]).toBe("one \n\n⟦image 1⟧\n\n three");
  });
});

describe("wire", () => {
  it("sends the files in their tokens' order, renumbered as the server reads them", () => {
    const a = pend(photo("a.jpg"), [], "");
    const b = pend(pdf(), [a], "");
    const c = pend(photo("c.jpg"), [a, b], "");
    const unused = pend(md(), [a, b, c], "");
    const text = `Trip\n\n${b.token}\n\n${c.token}\n\nthen ${a.token} and ${c.token} ⟦image 9⟧`;
    const out = wire(text, [a, b, c, unused]);
    expect(out.files.map((f) => f.name)).toEqual(["minutes.pdf", "c.jpg", "a.jpg"]);
    // the unused (its token deleted) is not sent; a token for no file stays as typed
    expect(out.text).toBe(
      "Trip\n\n⟦file 1⟧\n\n⟦image 2⟧\n\nthen ⟦image 3⟧ and ⟦image 2⟧ ⟦image 9⟧",
    );
    expect(placed(text, [a, b, c, unused])).toEqual([b, c, a]);
  });

  it("leaves text with no files as it is", () => {
    expect(wire("just words", [])).toEqual({ text: "just words", files: [] });
  });
});
