import { expect, it } from "vitest";
import { clean, leading } from "../src/snipclean";

it("takes task boxes out of a snippet, and says a web address in words", () => {
  expect(clean("Release ibek 4.1 [x] Bump the schema version [ ] Rebuild")).toBe(
    "Release ibek 4.1 Bump the schema version Rebuild",
  );
  expect(clean("- [ ] milk")).toBe("milk");
  expect(clean("see a[x]b")).toBe("see a[x]b"); // not a box: part of a word
  expect(clean("https://en.wikipedia.org/wiki/Integrated_information_theory")).toBe(
    "en.wikipedia.org · wiki / Integrated information theory",
  );
  expect(clean("at https://www.example.com/ now")).toBe("at example.com now");
});

it("finds the title leading a snippet, whole words, punctuation aside", () => {
  const s = "Release ibek 4.1 Bump the schema";
  expect(s.slice(leading(s, "Release ibek 4.1"))).toBe("Bump the schema");
  expect(
    leading("Look at sqlite vec 0.2 release notes", "Look at sqlite-vec 0.2 release notes"),
  ).toBe(0); // all of it
  expect(leading("scrap design notes A running list", "scrap design")).toBe(13);
  expect(leading("Great expectations", "Great exp")).toBe(0); // part of a word
  expect(leading("Something else", "Release")).toBe(0);
});
