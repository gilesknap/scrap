# 43. Public pages: a static site scrap pushes to

Date: 2026-10-31 (#497)

## Status

Accepted. Replaces the scrap-to-gist skill (#481, #484, #489), which is removed. Keeps the
access model of [](0007-tailscale-serve-for-access-and-identity.md): scrap itself never becomes
public.

## Context

The owner wants to show a page to anyone with its address, read only. The motivating case is a
whiteboard photographed in a meeting, with Claude's write-up of it. Until now the way out was the
scrap-to-gist skill: Claude turned a page into GitHub-flavoured Markdown, worked around what GitHub
cannot draw (`\cancel`, maths alignment), copied the images in, and made a secret gist. It needed
`gh` with a token that can make gists, Chrome for the maths, a second Markdown renderer kept in
step with scrap's by hand, and it published a copy that no longer changed when the page did.

scrap has no login code ([](0007-tailscale-serve-for-access-and-identity.md)). Everything it
serves is behind the tailnet or Cloudflare Access, and its API reaches every page. A public page
must not open any path to that.

The PWA already turns a page into one self-contained HTML file: Share as HTML (#485,
`web/src/pagehtml.ts`). It reads the page's own rendered view, by allow-list, so its output is
the page as scrap shows it, with no script, form or server address, and only its own `<style>`.
It writes maths as its TeX, because KaTeX's markup needs CSS and fonts that the file does not
carry.

## Decision

- **A static site.** Public pages live on a static site, `https://pages.gkcluster.org` for the
  owner, served by nginx from a separate `scrap-public` image. The same image holds a small upload
  **receiver**: internal only, it needs a token, and all it can do is write or delete files in the
  site's folder. The public side has no database, no Python app of scrap's, no login and no
  route to scrap: nobody can ask it for anything that was not deliberately written out.
- **The PWA renders; there is no second renderer.** A public page is the PWA's own view of the
  page, written out by `pagehtml.ts` in a new publish mode as one HTML file. Because it reads the
  rendered page, the public copy cannot drift from what scrap shows: tables, the Claude card, and
  maths too, since the publish mode writes each formula as `katex.renderToString` with the PWA's
  own options (KaTeX's exact markup, not the browser's serialisation) rather than the TeX. The
  page's CSS moves out of the file: it links `/assets/page.css` and `/assets/katex.css`, which
  scrap pushes with KaTeX's fonts from its own static build, and has no `<style>` element. The PWA
  uploads the file to scrap (`PUT /api/pages/{key}/published`, with the `base_rev` it rendered);
  scrap checks it, adds the page's files (below) and pushes the lot to the receiver. The PWA never
  talks to the receiver, and only scrap holds the token.
- **Only the owner's PWA publishes.** The publishing routes are under `/api`, the owner's PWA
  session behind Cloudflare Access or Tailscale. They are not served under `/mcp`, so an MCP
  bearer token cannot publish HTML. `GET /api/public` lists the public pages (and, with
  `?links_to=`, those linking to a page) for the PWA's link decisions and Refresh all, and
  `POST /api/public/rebuild` builds the index units once after a batch. The routes, their bodies
  and their errors are in the contract.
- **Turned down: a renderer in Python on the server.** The first plan had scrap render public
  pages itself, from the Markdown, with the HTML download, the print view, KaTeX and SVG
  sanitising reused (#497's first comments). It would publish without the PWA, after an MCP edit
  or a regenerated write-up. It was turned down because it is a second renderer: Markdown
  extensions, maths, task lists, embeds and the Claude card would have to be rebuilt in Python and
  kept in step with the PWA by hand, which is exactly what made the gist skill fragile. Refresh
  all (below) covers what only a server renderer would have caught.
- **The flag.** `page.public`, 0 or 1 (migration `0020_public_pages.sql`), set by
  `PATCH /api/pages/{key}` or MCP `edit_meta(public=...)` like the other fields, so each change is
  a revision (`page_meta_rev.public_before` and `public_after`) that `revert` can undo. A page is
  made public one at a time (more than one in a request is `422 one_at_a_time`); pages can be
  made private in bulk. Turning it on by either route only sets the flag; turning it off
  unpublishes at once, after the change has committed. If the receiver is down then, the change
  still succeeds with `"unpublish": "pending"` and reconcile finishes the deletion. Undelete and
  revert keep the flag. `published_at` is read from the kept copy (there is no column), and is
  null when there is none: the PWA then shows "Public · not published yet" (a page made public
  over MCP, say), and Refresh all publishes it. That is a null timestamp, not stale tracking.
- **A publish re-checks the flag.** Under scrap's lock a publish reads the page again and is
  refused (`409 not_public`) unless the page is public and not in the trash, so a render that
  raced an unpublish can never put the page back.
- **When a page is published.**
  - Turning Public on, after one OK or Cancel warning that the page's tags and Claude's write-up
    and summary go public too.
  - Saving a public page in the PWA.
  - **Links coming alive.** When a page is made public or private, the PWA also renders and uploads
    again the public pages that refer to it (`GET /api/public?links_to=`, from the `refs` each
    kept copy records: links, Linked from and Related), so a label becomes a link, or a link a
    label, without anyone editing those pages.
  - **Settings, "Refresh all public pages".** One action renders and uploads every public page
    again. It covers what the PWA did not see: edits over MCP, a regenerated write-up, a change in
    scrap's look. There is no stale tracking, no outbox, no trigger and no render on the server:
    the owner presses Refresh all when he wants the site current. If any public page has never
    been published, Refresh all lists them and asks once before they go public for the first time
    (a default the owner may change).
  - **Publishing needs the network.** A save of a public page queued offline is saved but not
    published, with a toast: "Saved. Not published while offline: Refresh all public pages in
    Settings later." Publishes are never queued.
- **Unpublishing is immediate and done by scrap**, however the flag turns off or the page leaves:
  Public turned off in the PWA or over MCP, a `revert`, or the page going to the trash. scrap
  deletes its kept copy of the page first (after the flag change or the trash has committed),
  then the page's unit on the site, then builds the home, tag and search units again, without
  the PWA. A `revert` that turns the flag back on
  publishes nothing by itself: the page goes out the next time the PWA renders it, or on Refresh
  all. Off always takes effect at once; on waits for a render.
- **URLs.** A page is at `/p/<slug>`, the same slug as in scrap. `/` is an index of the public
  pages with their tags, `/tags` lists the tags, and `/t/<key>` lists one tag's pages. A tag's key
  is computed in Python only, by a rule of its own (not `slug_base`, the rule for page slugs): an
  ASCII slug of the tag of at most 60 characters, `-`, and 8 hex digits of the tag's SHA-256, so
  `personal/family` is `personal-family-1a2b3c4d`. scrap's tags may hold spaces, `/` and letters
  outside ASCII, and two tags with the same slug still get different keys. The publish mode writes
  a tag chip's link as `scrap-tag:<tag>` and scrap swaps in `/t/<key>`. Pagefind gives search with
  a static index, so search needs no server either; its start-up script is scrap's own
  `pagefind/scrap-search.js`. The site is `noindex` by default (`X-Robots-Tag: noindex, nofollow`
  and a `robots.txt` of `Disallow: /`); the image's `INDEXING=on` switch lifts it.
- **What a public page holds**, as the contract's "What the publish mode writes" spells out:
  - The body as shown, Claude's write-up and summary, and the tags (as chips linking to their
    tag pages). Mermaid diagrams go out as their source, not rendered.
  - Links to public pages stay links. A link to a private page becomes a plain `<span>` holding
    the label the owner typed, or "a private page" when there is none (a bare `[[slug]]` or
    address): never the slug, which comes from a title and can say more than the label (a
    default the owner may change).
  - Linked from and Related keep an entry only if the other page is public; otherwise the whole
    entry, title included, is dropped.
  - An image's `alt` is the text the owner typed; an alt the PWA filled in from the file name is
    published empty, so file names never go out as alt text (a default the owner may change).
  - Left out: Claude's notes (a photo's description, the read text, the drawing), revisions, the
    extracted text of files, and every `/api` or other private address.
  - **Drawings (Excalidraw) are not published in this version.** The publish mode leaves them
    out, and a photo with a drawing on it is published as the photo alone. Publishing drawings is
    a follow-up.
  - External links (`http:` and `https:`) stay, except those to scrap's own origins (hosts
    compared case-insensitively, a trailing dot removed), any URL whose path starts with
    `/api/`, and any URL with userinfo, which are refused.
- **Images and attached files are files of the page, not inlined.** The publish mode writes each
  `<img src>` and file link as a placeholder, `scrap-blob:<sha>` (the regex
  `scrap-blob:[0-9a-f]{64}`), and scrap replaces it only where it is the whole value of an `img`'s
  `src` or an `a`'s `href`; anywhere else a placeholder refuses the publish. **An image's
  original is never published:** whichever element names it, it goes out as its 2048-pixel
  preview or sanitised SVG, and an `a` naming it links to that same file. Only files that are not
  images go out as stored. Each one becomes an absolute path, `/p/<slug>/<name>`, under a new
  name: `img-<n>-<hex>.jpg`, `.png` or `.svg` for an image and `file-<n>-<hex>.<ext>` for another
  file, where `<hex>` is 10 hex digits of the SHA-256 of the
  bytes published. Neither the stored sha nor the uploaded file name is published (a link's label
  may still show the name). scrap copies the bytes itself: a photo's 2048-pixel preview (EXIF and
  GPS already stripped by `preview._make`), other files as stored, and every SVG run through the
  sanitiser of [](0042-mcp-clients-add-svg-and-files.md) again at publish, since SVGs stored
  before #480 were never sanitised. An attachment is never published as HTML, script, CSS or SVG:
  an SVG attachment goes out as an image, and an unlisted type as `bin`. `pagehtml.ts` drops `svg`
  elements today, so its publish mode must keep SVG embeds, as images.
- **Caps.** A page publishes at most 20 images and files, each at most 20 MiB, and at most 200 MiB
  in all (under the receiver's 256 MiB body). Over any of them scrap refuses the publish, saying
  why, before pushing anything. The receiver allows 30 s to receive a request, so a unit must
  also be small enough to upload in that time.
- **No script on a page, checked twice.** The publish mode writes a fixed meta CSP into the page,
  `default-src 'none'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline';
  font-src 'self'`, with no `script-src` (inline styles only as attributes, for KaTeX), and scrap
  checks it is there. scrap parses the upload with a WHATWG-conformant parser (html5lib), matches
  elements and attributes by namespace and name, and checks it against pagehtml's allow-list
  (elements, attributes, `href` and `src` values, no `<style>` element, and `style` attributes
  only inside KaTeX's markup, limited to the attributes and properties KaTeX itself writes, taken
  from `katex.mjs`). A mismatch is refused with `422`; scrap never cleans the HTML. The `katex`
  class gate is visual hygiene, not a security boundary: the boundary is the CSP with
  `script-src 'none'`, the allow-list, and an upload reachable only from the owner's PWA
  session. nginx sends `script-src 'none'` on everything under `/p/` and `/t/`; only the home
  page may run a script, Pagefind's. The receiver limits what each unit may hold: a page only its
  `index.html`, `img-*` and `file-*`; `.js` and `.wasm` only in `pagefind`; CSS and fonts only in
  `assets`; a tag unit only its `index.html`, and `home` only one-segment HTML files.
- **scrap keeps what it pushed.** For each public page scrap keeps the unit as last pushed under
  `<data>/cache/publish/p/<slug>/`: `index.html`, its `img-*` and `file-*`, and `meta.json` (the
  page's id, title, tags at publish time, `published_at`, and `refs`, the slugs it refers to). It
  is derived data, not backed up; a copy is damaged when its files' digest no longer matches the
  digest scrap last pushed. From these copies, and nothing else, scrap builds the
  home page (newest `published_at` first), the tag pages and the Pagefind index (the
  `pagefind[bin]` Python package, at a pinned version), with plain Python templates and no
  Markdown. Pagefind indexes each page with its KaTeX markup removed and the formula's TeX in its
  place. Builds are deterministic (sorted order, no timestamps), so an unchanged unit keeps its
  digest.
- **Reconciling**, at startup and every 10 minutes, in this order: **prune** the kept copies (and
  their units) of pages that are not public or are in the trash, and of damaged copies; **build**
  every derived unit (home, the tag pages, search, assets) fresh from the copies that remain,
  which also picks up a new KaTeX, new templates or a new Pagefind after an upgrade; **push**
  every unit that is missing from the receiver's manifest or differs (page units from their kept
  bytes, compared with the digest scrap stored; derived units from the fresh build); then
  **sync**, deleting any stray. Nothing is rendered, so a site that lost its files is refilled
  without the PWA or a restart. A page whose damaged copy was pruned comes back on the next
  Refresh all.
- **One lock in scrap.** Every publish, unpublish and reconcile step runs under a single lock,
  and reconcile reads the kept copies again under it before each push, so an unpublish can never
  be undone by a reconcile that read the copy just before it was deleted. The receiver has its
  own lock over its writes.
- **The receiver contract** is fixed in [](../../reference/public-site.md), the one source of
  truth for both sides. In short: HTTP/1.1 with a bearer token of at least 32 characters; the
  site is made of **units** (a page `p/<slug>`, a tag `t/<key>`, `home`, `pagefind` and `assets`),
  each replaced whole by a `PUT` of a tar and swapped in atomically, or removed by an idempotent
  `DELETE`; `POST /v1/sync` deletes every unit not in a list; `GET /v1/manifest` says what is
  there. Paths, file names, sizes and the site's total are checked strictly, and a digest over
  the files catches a damaged upload.
- **Kubernetes first.** The chart gets a `public` section, off by default:
  - a `scrap-public` namespace under Pod Security `restricted`;
  - a NetworkPolicy per port: nginx's port (8080) takes traffic from the chart's
    `public.networkPolicy.webFrom`, the receiver's port (8081) only from scrap's pods, and the
    public pods have no egress at all. `webFrom` defaults to `[]`, which admits anyone to nginx's
    port (it is the public side); set it to narrow that to the ingress controller;
  - the token in a Secret the chart names but never creates (as for scrap's other secrets),
    mounted as a file in both scrap and the receiver;
  - nginx alone behind an Ingress; the receiver has a cluster-internal Service only,
    `<fullname>-receiver` (`http://scrap-receiver.scrap-public.svc:8081` for a release named
    `scrap`);
  - the site in an `emptyDir` shared by nginx (read only) and the receiver: a restarted pod comes
    back empty and scrap's reconcile fills it again, with no Refresh all.

  The single-server install (a second rootless podman service under its own user, the receiver on
  a Unix socket, the pattern of [](0018-unix-socket-for-single-server-installs.md)) is later
  work in a follow-up issue.
- **Unpublishing and caches.** A delete removes the page from the site, from the home and tag pages
  and from the search index. HTML is served `no-cache`, so a browser or proxy asks again before
  showing it; other files are `public, max-age=300`, so a copy can live up to five minutes more.
  Nothing can reach copies people saved, or caches outside the site's control. The docs say so
  plainly.
- **Headers.** The home page's HTML gets a strict CSP that allows only scripts from the site
  (Pagefind's and `scrap-search.js`; there is no inline script), with `connect-src 'self'` for the
  index Pagefind fetches. Pages and tag pages get `script-src 'none'`, and styles only from
  `/assets/` plus KaTeX's style attributes (`style-src 'self'; style-src-attr 'unsafe-inline'`).
  A page's images and files get the headers ADR 42 gives stored files: a sandboxing CSP that
  loads nothing, and for a PDF `sandbox` alone, so a browser's PDF viewer works.
- **The scrap-to-gist skill is removed** from the repo: `skills/scrap-to-gist/`, its tests, its
  `install.sh` entry and its docs. `install.sh` does not delete a copy already installed in
  `~/.claude/skills/scrap-to-gist`: it is the owner's to remove.

## Consequences

- A page can be shown to anyone without scrap being reachable: the internet reaches only nginx
  serving files, and the receiver accepts only scrap. A bug in scrap's API cannot leak through
  the public site, which holds only what was pushed to it.
- A public page looks as it does in scrap, maths included, with no second renderer to keep in
  step.
- The site is only as current as the last render. A page edited over MCP, or whose write-up was
  regenerated, keeps its old public copy until it is saved in the PWA or Refresh all is pressed.
  Unpublishing never waits.
- Publishing needs the PWA open on the owner's device; MCP can set the flag, but not render.
- Tags, Claude's write-up and the summary are public with the page.
- A public page that links to a page unpublished without the PWA's re-render (over MCP, by a
  revert or by the trash) keeps a live link to a 404 until Refresh all, the PWA's re-render of
  linking pages, or that page's next save. That is accepted: there is no stale tracking.
- A public page's photos are its 2048-pixel previews, and at most 20 images and files go with it.
  Drawings stay private until the follow-up that publishes them.
- Any change to what `pagehtml.ts` writes in publish mode must keep to the allow-list scrap
  checks, or publishing fails with `422`: the two change together.
- The site can be lost and rebuilt at any time; scrap's data folder holds the copy that matters.
- scrap gains settings for the push (`SCRAP_PUBLISH_TO`, `SCRAP_PUBLISH_SITE`,
  `SCRAP_PUBLISH_TOKEN` or `SCRAP_PUBLISH_TOKEN_FILE`); without them the feature is off.
- CI builds and publishes a second image, `scrap-public`, beside scrap's, and scrap gains the
  `pagefind[bin]` dependency.
- The gist workflow goes: no `gh` token with the `gist` scope, no headless Chrome, no second
  Markdown renderer. Gists already made stay as they are.
