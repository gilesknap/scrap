import { expect, test } from "vitest";
import { OFFLINE } from "../vite.config";

// A lazy chunk missing from OFFLINE is not precached, so after a deploy an old app shell
// asks for a hashed file that is gone (#35).
test("the page's lazy chunks are precached", () => {
  expect(OFFLINE).toContain("figure");
});
