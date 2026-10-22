import { expect, it } from "vitest";
import { echoes, snippetParts } from "../src/snippet";

it("splits marks from escaped text", () => {
  expect(snippetParts("buy <mark>milk</mark> &amp; eggs")).toEqual([
    { text: "buy ", mark: false },
    { text: "milk", mark: true },
    { text: " & eggs", mark: false },
  ]);
});

it("unescapes markup to text, never to tags", () => {
  // What the API sends for a page containing <script> and <img onerror>.
  const parts = snippetParts(
    "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; <mark>&lt;img src=x onerror=&quot;y&quot;&gt;</mark>",
  );
  expect(parts).toEqual([
    { text: "<script>alert('x')</script> ", mark: false },
    { text: '<img src=x onerror="y">', mark: true },
  ]);
});

it("leaves anything else as literal text", () => {
  // Even unescaped tags (which the API never sends) stay text: the caller makes text nodes.
  expect(snippetParts("<b>x</b> &amp;lt;")).toEqual([{ text: "<b>x</b> &lt;", mark: false }]);
});

it("knows a snippet that only says its title again, by its words alone", () => {
  expect(echoes("Review PR #125: page cap", "review PR 125 — page cap")).toBe(true);
  expect(echoes("Review PR #125: page cap", "page cap")).toBe(true); // part of the title
  expect(echoes("Buy milk", "BUY MILK!")).toBe(true);
  expect(echoes("Café list", "café")).toBe(true); // letters of any script count
  expect(echoes("Buy milk", "buy milk and eggs")).toBe(false); // says more
  expect(echoes("Buy milk", "eggs")).toBe(false);
});
