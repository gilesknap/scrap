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
const { picker } = await import("../src/capture");
const { GALLERY, noun, photoAdder } = await import("../src/addphoto");

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

it("lets the editor's Gallery take PDFs, and its Camera photos only", () => {
  expect(GALLERY).toBe("image/*,application/pdf");
  photoAdder({ id: "P1", title: "Board" });
  expect(inputs.map((i) => i.accept)).toEqual(["image/*", GALLERY]);
});

it("names what was added as photos, files (PDFs), or both", () => {
  const f = (type: string) => ({ type });
  expect(noun([f("image/jpeg")])).toBe("Photo");
  expect(noun([f("image/jpeg"), f("image/png")])).toBe("Photos");
  expect(noun([f("application/pdf")])).toBe("File");
  expect(noun([f("application/pdf"), f("application/pdf")])).toBe("Files");
  expect(noun([f("image/jpeg"), f("application/pdf")])).toBe("Photo and file");
  expect(noun([f("image/jpeg"), f("image/png"), f("application/pdf")])).toBe("Photos and file");
});
