// Helpers shared by the specs: ids, dates, pages made and cleaned up, and PNG bytes.
import { deflateSync } from "node:zlib";
import { type APIRequestContext, type Page, test } from "@playwright/test";

/** A random capture id: 26 characters of Crockford base 32, the first "0" (a valid ULID's
 * first character is 0 to 7). Random, not counted: a capture's id is idempotent, so a worker
 * started again after a failure, or a repeat of a spec, must not reuse one. */
export const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

/** A day n days from today on this machine's calendar (the server's too), as YYYY-MM-DD. */
export const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

/** Capture a page of this text (and extra capture fields, such as kind) with a fresh id: its
 * slug and id. It checks nothing, so a spec asserts what it needs on the answer. */
export async function capture(page: Page, text: string, extra: Record<string, unknown> = {}) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, ...extra } });
  return (await r.json()) as { page_id: string; slug: string };
}

/** Delete these pages (by id or slug, to the trash), in order, and empty the list. */
export async function deletePages(request: APIRequestContext, ids: string[]) {
  for (const id of ids.splice(0)) await request.delete(`/api/pages/${id}`);
}

/** A list of page ids deleted after each test of the file: push the id of every page a test
 * makes, so other specs' counts of the store's pages hold. Call it once, at the top level. */
export function deletedAfterEach(): string[] {
  const made: string[] = [];
  test.afterEach(({ request }) => deletePages(request, made));
  return made;
}

/** A page as the store's list (/api/pages) gives it. */
export type Listed = { id: string; slug: string; title: string; kind: string; thumb: unknown };

/** Every page each test of the file makes, however it makes it (the composer, a share, the
 * queue, the API), deleted after the test: the pages in the store as it starts are noted
 * (the 500 last changed: a page made since is among them), and any page not among them is
 * the test's. The function returned lists those so far, newest change first, so a test can
 * check its own pages whatever else the store holds. Call it once, at the top level. */
export function madeEachTest(): (request: APIRequestContext) => Promise<Listed[]> {
  const list = async (request: APIRequestContext) =>
    (await (await request.get("/api/pages?limit=500")).json()) as Listed[];
  let before = new Set<string>();
  const made = async (request: APIRequestContext) =>
    (await list(request)).filter((p) => !before.has(p.id));
  test.beforeEach(async ({ request }) => {
    before = new Set((await list(request)).map((p) => p.id));
  });
  test.afterEach(async ({ request }) =>
    deletePages(
      request,
      (await made(request)).map((p) => p.id),
    ),
  );
  return made;
}

/** A greyscale w x h PNG, every pixel of this shade. Each row starts with its filter byte, 0
 * (none), unless filterBytes is false: then that byte is the shade too, as z-csp.spec.ts has
 * always sent it. */
export function png(w: number, h: number, shade = 128, { filterBytes = true } = {}): Buffer {
  const crc = (b: Buffer) => {
    let c = ~0;
    for (const x of b) {
      c ^= x;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return ~c >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const out = Buffer.alloc(body.length + 8);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc(body), body.length + 4);
    return out;
  };
  const head = Buffer.alloc(13);
  head.writeUInt32BE(w, 0);
  head.writeUInt32BE(h, 4);
  head.set([8, 0, 0, 0, 0], 8); // 8-bit greyscale
  const rows = Buffer.alloc((w + 1) * h, shade);
  if (filterBytes) for (let y = 0; y < h; y++) rows[y * (w + 1)] = 0; // no filter
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", head),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
