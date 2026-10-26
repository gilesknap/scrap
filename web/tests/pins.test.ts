import { expect, it } from "vitest";
import { adding, nameOf, parse, removing, searchHref } from "../src/pins";

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
