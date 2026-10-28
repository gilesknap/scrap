// One wording for what a capture holds (#403): Capture's draft row, the queue's rows and
// Add photo's toasts all use says.ts.
import { expect, it } from "vitest";
import { holds, says } from "../src/says";

const f = (type: string) => ({ type });

it("counts photos and files", () => {
  expect(holds([])).toBe("");
  expect(holds([f("image/jpeg")])).toBe("1 photo");
  expect(holds([f("image/jpeg"), f("image/png")])).toBe("2 photos");
  expect(holds([f("application/pdf")])).toBe("1 file");
  expect(holds([f("image/jpeg"), f("image/png"), f("application/pdf")])).toBe("2 photos, 1 file");
  expect(holds([f("text/markdown"), f(""), f("image/heic")])).toBe("1 photo, 2 files");
});

it("says the first line of words, without tokens or list marks, then the count", () => {
  expect(says("Trip\nmore", [])).toBe("Trip");
  expect(says("⟦image 1⟧\n\n- [ ] Pack the tent ⟦file 1: kit.pdf⟧\n", [f("image/jpeg")])).toBe(
    "Pack the tent · 1 photo",
  );
  expect(says("⟦image 1⟧\n⟦image 2⟧", [f("image/jpeg"), f("image/jpeg")])).toBe("2 photos");
  expect(says(undefined, [f("application/pdf")])).toBe("1 file");
  expect(says("", [])).toBe("");
  expect(says("https://example.com", [])).toBe("https://example.com");
});
