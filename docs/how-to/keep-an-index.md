# Keep an index of your pages

scrap has no bookmarks feature, and doesn't need one. A bookmark list is an ordinary page of
links, tagged so you can find it, and pinned so it is a tap away from Search. Claude can build
and maintain it over MCP. This guide sets one up; the same steps make any page of links
(an index per project, say).

## 1. Make the page

Make a normal note titled *Index* (a Note is the right kind: an index is text you and Claude
both edit, so not a board, doc or todo). Group its links under headings, one `[[slug|title]]`
link per line:

```markdown
## Projects

- [[garden-plan|Garden plan]]
- [[kitchen-rebuild|Kitchen rebuild]]

## Reference

- [[wifi-and-router|Wi-Fi and router]]
```

A slug is the last part of a page's address (`/p/garden-plan` is `garden-plan`), and it never
changes when a page is retitled, so the links survive renames. Only lower-case letters, digits
and hyphens make a link: `[[Garden plan]]` stays as typed. The label after `|` is what shows.
See [](use-the-pwa.md) (Linking pages).

Tag the page `index`: tap **+ Tag** under its title. Tags are lower case, at
most 64 characters. If only this page carries the tag, a search for `tag:index` finds it at once. Use `index/projects`, `index/people` and so on for a page per topic: a search
for `tag:index` finds them all.

## 2. Pin it

Open the page, tap **Share**, then **Pin to Search**. Or run the search `tag:index` and tap the
pin in the results header, which pins the search instead of the page (useful with several index
pages; it lists them, one more tap to open one). Either way the pin goes on the **Pinned**
page, an ordinary page of links, described in [](make-your-own-lists.md).

**Pins do not show on launch.** The app opens on the capture screen, and pins appear only in
the Search view: tap **Search**, then tap the empty search box, and **Pinned** is listed above
Recent. So the index is two taps from launch, and one tap from the search view.

## 3. Let Claude maintain it

Over [MCP](../reference/mcp.md), ask Claude in plain words: *add this page to the Index under
Projects*. It reads the page, then adds a `[[slug|title]]` line under the right heading (or
makes the heading). Claude can edit the text of a page you ask it to change with `edit_page`,
and each edit is a revision you can undo with `revert`. A server run with
`SCRAP_MCP_CONTENT_EDIT=0` cannot do this: Claude can then only append to a page it wrote
itself, so let it write the Index (*make me an Index page*) and it can append to it afterwards (an append lands at the end of the page, not under a chosen
heading, so you move the lines yourself).

To see what an index links to, and what links back, open the page and look under **Related**:
every page in the index lists the Index among its backlinks.
