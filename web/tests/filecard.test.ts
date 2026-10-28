import { describe, expect, it, vi } from "vitest";
import type { FileIngest } from "../src/api";

vi.mock("../src/app", () => ({ rerender: () => {} }));
vi.mock("../src/icons", () => ({ icon: () => "" }));
const { FILE, fileSays, fileStateText } = await import("../src/filecard");
const { RETRY, UNREAD } = await import("../src/filerow");

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

describe("the file card", () => {
  it("is titled as the photo card is, for a file", () => {
    expect(FILE).toBe("What's in the file");
  });

  it("says where the reading is up to without naming Claude (scrap reads it)", () => {
    expect(fileStateText(pdf({ state: "queued" }))).toBe("Waiting to be read");
    expect(fileStateText(pdf({ state: "processing" }))).toBe("Reading the text…");
    expect(fileStateText(pdf({ state: "failed", error: "timeout: 60 s" }))).toBe(
      "Couldn't read it: timeout: 60 s",
    );
    for (const s of ["queued", "processing", "done", "failed"] as const)
      expect(fileStateText(pdf({ state: s }))).not.toMatch(/Claude/);
  });

  it("says what was found once read: pages, and whether search finds it", () => {
    expect(fileSays(pdf({}))).toBe("12 pages · Searchable");
    expect(fileSays(pdf({ pages: 1 }))).toBe("1 page · Searchable");
    expect(fileSays(pdf({ kind: "text", pages: null }))).toBe("Searchable");
    expect(fileSays(pdf({ searchable: false }))).toBe(`12 pages · ${UNREAD}`);
    expect(fileSays(pdf({ state: "failed", error: "timeout: x", pages: null }))).toBe(RETRY);
    expect(fileSays(pdf({ state: "queued", pages: null }))).toBeNull();
    expect(fileSays(null)).toBeNull();
  });

  it("points a failure that may not repeat at the card's own button", () => {
    expect(RETRY).toMatch(/Retry$/);
  });
});
