import { afterEach, expect, it, vi } from "vitest";
import type { Page } from "../src/api";
import { blobRefs, confirmRemoval, removalWarning } from "../src/unembed";

const A = "a".repeat(64);
const B = "b".repeat(64);
const C = "c".repeat(64);
const embed = (sha: string, alt = "") => `![${alt}](/api/blobs/${sha}/preview?size=2048)`;
const page = {
  id: "P1",
  captures: [
    {
      id: "C1",
      url: null,
      blobs: [
        { sha256: A, mime: "image/jpeg", size: 1, filename: "IMG_1.jpg" },
        { sha256: B, mime: "image/jpeg", size: 1, filename: null },
      ],
    },
  ],
} as unknown as Page;

// The server: how many other pages show each file (absent: not a stored file)
function serve(uses: Record<string, number>) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    calls.push(url);
    const sha = url.match(/blobs\/([0-9a-f]{64})\/uses\?page=P1$/)?.[1] ?? "";
    return sha in uses
      ? new Response(JSON.stringify({ pages: uses[sha] }))
      : new Response("{}", { status: 404 });
  });
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

it("reads every mention of a file's address, as the server does", () => {
  expect(
    blobRefs(`${embed(A)} [x](/api/blobs/${B}?download=1) /api/blobs/${"c".repeat(63)}`),
  ).toEqual(new Set([A, B]));
});

it("says nothing when no embed goes, without asking the server", async () => {
  const calls = serve({});
  const text = `Hello\n\n${embed(A)}`;
  expect(await removalWarning(page, text, `${text}\nmore`)).toBeNull();
  expect(await removalWarning(page, text, `moved up ${embed(A)}`)).toBeNull();
  expect(calls).toEqual([]);
});

it("names the image whose line went", async () => {
  serve({ [A]: 0, [B]: 0 });
  const w = await removalWarning(page, `x\n\n${embed(A)}\n${embed(B)}`, `x\n\n${embed(B)}`);
  expect(w).toContain("Saving removes an image from this page, because you deleted its line:");
  expect(w).toContain("• IMG_1.jpg: no longer shown on any page");
  expect(w).not.toContain(B.slice(0, 8));
  // Kept: gathered onto the month's review page, not deleted (#124)
  expect(w).toContain("the nightly scrap gc gathers it onto this month's Orphaned assets page");
});

it("counts each image and falls back to its alt text, then its start", async () => {
  serve({ [A]: 0, [B]: 0, [C]: 0 });
  const w = await removalWarning(page, `${embed(A)}\n${embed(B, "whiteboard")}\n${embed(C)}`, "");
  expect(w).toContain("Saving removes 3 images from this page, because you deleted their lines:");
  expect(w).toContain("• whiteboard: no longer shown on any page");
  expect(w).toContain(`• image ${C.slice(0, 8)}: no longer shown on any page`);
});

it("says a shared image stays on the other pages", async () => {
  serve({ [A]: 2, [B]: 1 });
  const w = await removalWarning(page, `${embed(A)}\n${embed(B)}`, "");
  expect(w).toContain("• IMG_1.jpg: still shown on 2 other pages");
  expect(w).toContain(`• image ${B.slice(0, 8)}: still shown on 1 other page`);
});

it("leaves out a file the server doesn't hold, and hedges when offline", async () => {
  serve({ [A]: 0 });
  expect(await removalWarning(page, embed(C), "")).toBeNull();
  vi.stubGlobal("fetch", async () => {
    throw new TypeError("offline");
  });
  expect(await removalWarning(page, embed(A), "")).toContain(
    "• IMG_1.jpg: no longer shown here (other pages may still show it)",
  );
});

it("asks, and only when something goes", async () => {
  serve({ [A]: 0 });
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  expect(await confirmRemoval(page, embed(A), embed(A))).toBe(true);
  expect(ask).not.toHaveBeenCalled();
  expect(await confirmRemoval(page, embed(A), "")).toBe(false);
  ask.mockReturnValue(true);
  expect(await confirmRemoval(page, embed(A), "")).toBe(true);
  expect(ask).toHaveBeenCalledTimes(2);
});
