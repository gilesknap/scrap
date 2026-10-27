import { beforeEach, describe, expect, it, vi } from "vitest";
import { type FileIngest, type FileRef, photoIngest } from "../src/api";

// No DOM under vitest here: just enough of one for h() to build the row
type El = { tag: string; kids: (El | string)[]; [k: string]: unknown };
const el = (tag: string): El => ({
  tag,
  kids: [],
  setAttribute(k: string, v: string) {
    this[k] = v;
  },
  append(...k: (El | string)[]) {
    this.kids.push(...k);
  },
});
const text = (e: El | string): string =>
  typeof e === "string" ? e : e.kids.map(text).join(" ");
const find = (e: El | string, cls: string): El | undefined => {
  if (typeof e === "string") return undefined;
  if (
    String(e.className ?? "")
      .split(" ")
      .includes(cls)
  )
    return e;
  for (const k of e.kids) {
    const got = find(k, cls);
    if (got) return got;
  }
};

vi.mock("../src/app", () => ({ rerender: () => {} }));
vi.mock("../src/icons", () => ({ icon: () => "" }));
const { fileFacts, fileRow, UNREAD, RETRY } = await import("../src/filerow");

const pdf = (o: Partial<FileIngest>): FileIngest => ({
  state: "done",
  failures: 0,
  error: null,
  kind: "pdf",
  pages: 12,
  pages_read: 12,
  truncated: false,
  text_chars: 900,
  searchable: true,
  ...o,
});

describe("fileFacts: what a file's row says", () => {
  it("gives a read PDF's page count, and no hint", () => {
    expect(fileFacts(pdf({}))).toEqual({ pages: "12 pages", hint: null });
    expect(fileFacts(pdf({ pages: 1, pages_read: 1 }))).toEqual({
      pages: "1 page",
      hint: null,
    });
  });

  it("says its text couldn't be read when reading failed or found none", () => {
    const failed = pdf({
      state: "failed",
      pages: null,
      error: "content: the PDF could not be read",
    });
    expect(fileFacts(failed)).toEqual({ pages: null, hint: UNREAD });
    expect(fileFacts(pdf({ searchable: false, text_chars: 0 }))).toEqual({
      pages: "12 pages",
      hint: UNREAD,
    });
    expect(UNREAD).toBe("Text couldn't be read; not searchable");
  });

  it("does not blame the file for a failure that may not repeat", () => {
    for (const error of [
      "timeout: reading the PDF took over 60 s",
      "internal: OSError",
    ])
      expect(fileFacts(pdf({ state: "failed", pages: null, error })).hint).toBe(
        RETRY,
      );
    expect(
      fileFacts(pdf({ state: "failed", pages: null, error: "content: x" }))
        .hint,
    ).toBe(UNREAD);
  });

  it("says nothing while it waits or is read, nor for a file never queued", () => {
    for (const state of ["queued", "processing"] as const)
      expect(fileFacts(pdf({ state, pages: null, searchable: false }))).toEqual(
        {
          pages: null,
          hint: null,
        },
      );
    expect(fileFacts(null)).toEqual({ pages: null, hint: null });
    expect(fileFacts(undefined)).toEqual({ pages: null, hint: null });
  });

  it("gives a text file no page count", () => {
    expect(
      fileFacts(pdf({ kind: "text", pages: null, pages_read: null })),
    ).toEqual({
      pages: null,
      hint: null,
    });
  });

  it("says nothing for a photo's ingest (an image the server couldn't preview)", () => {
    const photo = {
      state: "failed" as const,
      failures: 3,
      error: "x",
      text: null,
      description: null,
      image_kind: null,
      drawing: null,
    };
    expect(fileFacts(photo)).toEqual({ pages: null, hint: null });
  });
});

describe("fileRow", () => {
  beforeEach(() => vi.stubGlobal("document", { createElement: el }));

  const row = (i?: FileIngest | null) =>
    fileRow(
      "/api/blobs/ab",
      "report.pdf",
      el("a") as never,
      i,
    ) as unknown as El;

  it("is the file's name, opening it, with its pages, then Download", () => {
    const r = row(pdf({}));
    const link = r.kids[0] as El;
    expect(link).toMatchObject({
      tag: "a",
      href: "/api/blobs/ab",
      target: "_blank",
    });
    expect(text(link)).toContain("report.pdf");
    expect(text(link)).toContain("12 pages");
    expect(find(r, "hint")).toBeUndefined();
    expect(r.kids).toHaveLength(2); // the link and Download
  });

  it("has the hint on failure only", () => {
    expect(
      text(find(row(pdf({ state: "failed", pages: null })), "hint") as El),
    ).toBe(UNREAD);
    expect(text(find(row(pdf({ searchable: false })), "hint") as El)).toBe(
      UNREAD,
    );
    expect(
      find(row(pdf({ state: "queued", pages: null })), "hint"),
    ).toBeUndefined();
    expect(find(row(null), "hint")).toBeUndefined();
    expect(text(row(null))).not.toMatch(/page/);
  });
});

describe("photoIngest", () => {
  const ref = (mime: string, ingest: unknown) =>
    ({ sha256: "ab", mime, size: 1, filename: null, ingest }) as FileRef;
  const photo = {
    state: "done",
    failures: 0,
    error: null,
    text: null,
    description: "a cat",
    image_kind: null,
    drawing: null,
  };

  it("is an image's photo ingest", () => {
    expect(photoIngest(ref("image/jpeg", photo))).toBe(photo);
  });

  it("is never a file's, so a PDF never gets a photo panel", () => {
    expect(photoIngest(ref("application/pdf", pdf({})))).toBeNull();
    expect(photoIngest(ref("application/pdf", photo))).toBeNull(); // not an image
    expect(photoIngest(ref("image/png", pdf({})))).toBeNull(); // not a photo's shape
    expect(photoIngest(ref("image/png", null))).toBeNull();
    expect(photoIngest(ref("image/png", undefined))).toBeNull();
  });
});
