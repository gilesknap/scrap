import { expect, it } from "vitest";
import { snippetParts } from "../src/snippet";

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
