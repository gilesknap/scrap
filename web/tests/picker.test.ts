import { beforeEach, expect, it, vi } from "vitest";

// No DOM under vitest here: just enough of one to see the file inputs the pickers make
type El = { tag: string; [k: string]: unknown };
let inputs: El[] = [];
const el = (tag: string): El => {
  const e: El = {
    tag,
    setAttribute(k: string, v: string) {
      e[k] = v;
    },
    append() {},
  };
  if (tag === "input") inputs.push(e);
  return e;
};

// The capture screen's and the editor's other pieces: not under test here
vi.mock("../src/app", () => ({ queue: null, view: {}, rerender: () => {} }));
vi.mock("../src/db", () => ({ drafts: {} }));
vi.mock("../src/fresh", () => ({ DRAFT: "d", recover: () => {} }));
vi.mock("../src/lists", () => ({ pageList: () => null, pendingList: () => null }));
vi.mock("../src/icons", () => ({ icon: () => "", kindIcon: () => "note" }));
const { FILES, picker } = await import("../src/capture");
const { adders } = await import("../src/adders");

beforeEach(() => {
  inputs = [];
  vi.stubGlobal("document", { createElement: el });
});

it("takes photos only, unless told otherwise", () => {
  picker("Camera", true, () => {});
  picker("Gallery", false, () => {});
  picker("Files", false, () => {}, "add", "application/pdf");
  expect(inputs.map((i) => i.accept)).toEqual(["image/*", "image/*", "application/pdf"]);
  expect(inputs[0].capture).toBe("environment");
  expect(inputs.map((i) => i.multiple)).toEqual([false, true, true]);
});

it("gives the editor's Camera and Gallery photos only, and File PDFs, text and Markdown", () => {
  // .md and .txt by name too: a phone's Markdown file often has no type
  expect(FILES).toBe("application/pdf,text/plain,text/markdown,.md,.txt");
  adders({} as HTMLTextAreaElement, {} as Parameters<typeof adders>[1]);
  expect(inputs.map((i) => i.accept)).toEqual(["image/*", "image/*", FILES]);
  expect(inputs.map((i) => i.multiple)).toEqual([false, true, true]);
});
