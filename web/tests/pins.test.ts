import { expect, it, vi } from "vitest";
import { adding, change, nameOf, parse, removing, searchHref } from "../src/pins";

(globalThis as { location?: { origin: string } }).location = { origin: "https://scrap.example" };

const BODY = `# Pinned

- [People A–Z](/search?q=tag:person%20group:letter)
- [Contacts](/p/contacts)
`;

it("reads the links in order, keyed by what they point at", () => {
  expect(parse(BODY)).toEqual([
    {
      name: "People A–Z",
      href: "/search?q=tag:person%20group:letter",
      key: "s:tag:person group:letter",
    },
    { name: "Contacts", href: "/p/contacts", key: "p:contacts" },
  ]);
  expect(parse("Some words\n- not a link\n- [x](https://example.com)")[0].key).toBe("");
});

it("writes a search's address readably, safe in a Markdown link", () => {
  expect(searchHref("tag:person  group:letter")).toBe("/search?q=tag:person%20group:letter");
  expect(searchHref("a (b)")).toBe("/search?q=a%20%28b%29");
});

it("adds at the end, and takes out every line for the same thing", () => {
  const more = adding(BODY, "Work [team]", searchHref("tag:person/work"));
  expect(more.trimEnd().split("\n").at(-1)).toBe("- [Work \\[team\\]](/search?q=tag:person/work)");
  expect(parse(more).at(-1)?.name).toBe("Work [team]");
  const [rest, at] = removing(more, "s:tag:person group:letter");
  expect(at).toBe(2);
  expect(parse(rest).map((p) => p.name)).toEqual(["Contacts", "Work [team]"]);
  expect(parse(adding(rest, "Back", "/p/x", at))[0].name).toBe("Back");
  expect(adding("", "One", "/p/one")).toBe("- [One](/p/one)\n");
});

it("names a search by its query, as the chips say it", () => {
  expect(nameOf("tag:person group:letter")).toBe("#person · grouped A–Z");
  expect(nameOf("kind:later later:watch")).toBe("Later · to watch");
  expect(nameOf("boiler -tag:home sort:title")).toBe("boiler · not #home · A–Z");
  expect(nameOf("kind:todo after:1w")).toBe("Todos · past week");
});

// ---- the page on the server: made by POST /api/pinned, edited with base_rev, a 409 read again

function server(pages: { id: string; body: string; rev: number }[]) {
  const calls: string[] = [];
  const bodies: string[] = [];
  const reply = (status: number, data: unknown) =>
    new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal("addEventListener", () => {});
  vi.stubGlobal("dispatchEvent", () => true);
  vi.stubGlobal("document", { addEventListener: () => {}, dispatchEvent: () => true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = `${init?.method ?? "GET"} ${url}`;
      calls.push(call);
      const page = pages[0];
      if (call === "GET /api/pinned") return page ? reply(200, page) : reply(200, null);
      if (call === "POST /api/pinned") {
        pages.push({ id: "P1", body: "# Pinned\n\n", rev: 1 });
        return reply(200, pages[0]);
      }
      const sent = JSON.parse(String(init?.body));
      bodies.push(sent.body);
      if (sent.base_rev !== page.rev) return reply(409, { detail: "stale" });
      page.body = sent.body;
      page.rev++;
      return reply(200, page);
    }),
  );
  return { calls, bodies };
}

it("makes the page through the server on the first pin, once", async () => {
  const pages: { id: string; body: string; rev: number }[] = [];
  const { calls } = server(pages);
  await change((b) => adding(b, "One", "/p/one"));
  expect(calls).toEqual(["GET /api/pinned", "POST /api/pinned", "PATCH /api/pages/P1"]);
  expect(pages[0].body).toBe("# Pinned\n- [One](/p/one)\n");
  const none: { id: string; body: string; rev: number }[] = [];
  const again = server(none);
  await change((b) => removing(b, "p:one")[0]); // nothing there to take out: nothing made
  expect(again.calls).toEqual(["GET /api/pinned"]);
});

it("reads again and retries on a 409, three tries at most", async () => {
  const pages = [{ id: "P1", body: "- [A](/p/a)\n", rev: 1 }];
  const { bodies } = server(pages);
  // Another device edits between our read and our PATCH: the first PATCH carries a stale rev
  let first = true;
  const edit = (b: string) => {
    if (first) {
      first = false;
      pages[0].rev++; // the other device's edit
    }
    return adding(b, "B", "/p/b");
  };
  await change(edit);
  expect(bodies.length).toBe(2);
  expect(pages[0].body).toContain("[B](/p/b)");
  const stale = [{ id: "P1", body: "", rev: 1 }];
  server(stale);
  await expect(
    change((b) => {
      stale[0].rev++;
      return b;
    }),
  ).rejects.toThrow();
});
