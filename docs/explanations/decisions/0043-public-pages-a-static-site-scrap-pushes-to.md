# 43. Public pages: a static site scrap pushes to

Date: 2026-10-31 (#497)

## Status

Accepted. Replaces the scrap-to-gist skill (#481, #484, #489), which is removed. Keeps the
access model of [](0007-tailscale-serve-for-access-and-identity.md): scrap itself never becomes
public.

Amended 2026-11-01 (1.3.1): a reader's theme and column width, by one script of the site's
own (#519), and drawings published, downloadable and opened in excalidraw.com (#520). See
[](#amendment-reader-preferences-and-drawings) at the end.

Amended 2026-11-01 (1.3.2): a drawing replaces its photo, with no photo in it (#524); an SVG
served as exactly `image/svg+xml`, so excalidraw.com opens it (#526); the site's icons and
header mark, scrap's own (#527); and tables shown as the app shows them (#530). See [](#amendment-drawings-without-the-photo-and-the-sites-icon) at the end.

Amended 2026-11-01 (1.3.3): Mermaid diagrams drawn, light and dark, rather than as their source
(#525), and code left as written but for scrap's own addresses (#529). See
[](#amendment-mermaid-diagrams-drawn) at the end.

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
  made public one at a time (a request matching more than one is `422 one_at_a_time`); pages can be
  made private in bulk. Turning it on by either route only sets the flag; turning it off
  unpublishes at once, after the change has committed. If the receiver is down then, the change
  still succeeds with `"unpublish": "pending"` and reconcile finishes the deletion. Undelete and
  revert keep the flag. `published_at` is read from the kept copy (there is no column), and is
  null when there is none: the PWA then shows "Public · not published yet" (a page made public
  over MCP, by a revert or an undelete), and Refresh all publishes it, after asking. That is a
  null timestamp, not stale tracking.
- **A first publish needs the owner's yes in the PWA.** The flag can be set without the PWA
  (MCP, a revert, an undelete), but such a page reaches the site only once the owner has
  confirmed it there: Make public's warning, or Refresh all's question. Those alone send
  `"confirmed": true`, and scrap refuses a publish of a page with no kept copy without it
  (`409 unconfirmed`). A save, a tick and links coming alive pass such a page by. Without this,
  a page flagged over MCP would have gone public at its next save with no warning at all.
- **A publish re-checks the flag.** Under scrap's lock a publish reads the page again and is
  refused (`409 not_public`) unless the page is public and not in the trash, so a render that
  raced an unpublish can never put the page back.
- **When a page is published.**
  - Making a page public, after a warning shown every time (Cancel or Make public) listing
    what goes public with it: its tags, Claude's write-up and summary, its attached files by
    name (on a topic, its synthesis, which draws on its source pages), and "Links to private
    pages show their titles as plain text."
  - Saving a public page in the PWA, once it has been published.
  - **Links coming alive.** When a page is made public or private, the PWA also renders and uploads
    again the public pages that refer to it (`GET /api/public?links_to=`, from scrap's own link
    data: pages whose text or write-up links to it, and pages related to it either way; not
    the published HTML, where a link to a private page is only a label), so a label becomes a
    link, or a link a label, without anyone editing those pages.
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
    tag pages). Mermaid diagrams went out as their source, not rendered (drawn since 1.3.3:
    [](#amendment-mermaid-diagrams-drawn)).
  - Links to public pages stay links. A link to a private page becomes a plain `<span>` holding
    the label the owner typed, or, when there is none (a bare `[[slug]]` or address), that
    page's title as plain text. The owner chose the title over a neutral "a private page": it
    reads naturally, and the warning on making a page public says so.
  - Linked from and Related keep an entry only if the other page is public; otherwise the
    entry is left out of those lists.
  - No address of scrap's own, and no `/api/` path, in a page's text: the publish mode writes
    "a private link" in its place, and scrap's check refuses text that still holds one.
  - **Private titles.** A private page's title shows, as words, on the public pages that link
    to it. When a page is made private or deleted in the PWA, the PWA publishes those pages
    again. When it happens elsewhere (over MCP, by a revert, or trashed from another device), the
    title stays on them until Refresh all or their next save in the PWA: accepted, since there
    is no stale tracking. The contract says so.
  - An image's `alt` is published as the app has it, a file name the PWA filled in included
    (the owner's choice; a link's label may show a file's name too).
  - Left out: Claude's notes (a photo's description, the read text), revisions, the
    extracted text of files, and every `/api` or other private address.
  - **Drawings (Excalidraw)** were left out in the first version (a photo with a drawing
    published as the photo alone); 1.3.1 publishes them ([](#amendment-reader-preferences-and-drawings)).
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
  bytes published, keyed with the page's slug (SHA-256 of slug, NUL, bytes) so a name never reveals the stored sha. Neither the stored sha nor the uploaded file name is published (a link's label
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
- **No script on a page, checked twice.** (1.3.1 allows one, the site's own `prefs.js`:
  [](#amendment-reader-preferences-and-drawings).) The publish mode writes a fixed meta CSP into the page,
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
  page's id, title, tags at publish time and `published_at`). It
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
  revert or by the trash) keeps a live link to a 404, and a page's title stays on the public
  pages linking to it after it is made private or trashed that way, until Refresh all, the
  PWA's re-render of linking pages, or that page's next save. That is accepted: there is no
  stale tracking. Make private, and deleting a page, in the PWA re-render them at once.
- If the receiver can't be told at once, Make private says the page comes off "shortly"
  (`"unpublish": "pending"`), and reconcile finishes it.
- A public page's photos are its 2048-pixel previews, and at most 20 images, drawings and files
  go with it.
- Any change to what `pagehtml.ts` writes in publish mode must keep to the allow-list scrap
  checks, or publishing fails with `422`: the two change together.
- The site can be lost and rebuilt at any time; scrap's data folder holds the copy that matters.
- scrap gains settings for the push (`SCRAP_PUBLISH_TO`, `SCRAP_PUBLISH_SITE`,
  `SCRAP_PUBLISH_TOKEN_FILE`: the token only from a file); without them the feature is off.
- CI builds and publishes a second image, `scrap-public`, beside scrap's, and scrap gains the
  `pagefind[bin]` dependency.
- The gist workflow goes: no `gh` token with the `gist` scope, no headless Chrome, no second
  Markdown renderer. Gists already made stay as they are.

(amendment-reader-preferences-and-drawings)=
## Amendment: reader preferences and drawings (1.3.1, #519, #520)

Public pages went live at `pages.gkcluster.org`, and two things were missing: readers could not
choose a theme (a phone in dark mode always got dark pages), and drawings, the point of a
whiteboard page, were left out. The owner decided both on 1 Nov 2026.

### Reader preferences: one script of the site's own (#519)

- **Light by default.** A public page is light, whatever the device's `prefers-color-scheme`
  (the build leaves that default out of the site's `page.css`); dark only when the reader chose
  it. With JavaScript off, a page is light.
- **One static script, `/assets/prefs.js`,** built with the PWA and pushed by scrap in the
  `assets` unit. It sets the kept theme (`data-theme="dark"`) and column width (`--column`, the
  app's four widths, 720 to 960 px, 800 by default) on `<html>`, and adds two quiet buttons to the
  site's header: a sun or moon ("Dark theme", pressed while dark) and the width, cycling. Every
  page, tag page, home and the 404 load it from `<head>` as `<script src="/assets/prefs.js" defer
  blocking="render">`: deferred, and render-blocking where the browser supports it (Chromium
  today), so a kept dark theme is on before the first paint, with no flash; elsewhere a reader
  who chose dark may see one light frame. The owner chose `defer` (or `async`) over a
  parser-blocking script. The buttons are made by the script, so
  without it there are none.
- **The CSP relaxation.** Pages and tag pages go from `script-src 'none'` to `script-src
  'self'`, in nginx's header and the page's meta CSP. That is what it costs, and why it is
  bounded: there is still no inline script anywhere (no `'unsafe-inline'`), so markup that slipped
  into a page could not run; scrap's check still refuses every `<script>` but exactly `prefs.js`
  (`defer` or `async`, `blocking="render"`, nothing else); the receiver still refuses `.js` in
  page, tag and home units, and allows it in `assets` for `prefs.js` alone, so the only scripts
  `'self'` can name are that file and Pagefind's, all built by scrap. A `sha256-` hash of
  `prefs.js` was considered on top and not added: a hash source allows an external script only
  with an `integrity` attribute and only in some browsers, `'self'` allows it anyway, and the
  hash would tie the image's nginx configuration to each scrap build.
- **Turned down:** an inline script (needs `'unsafe-inline'` or a per-page hash), and a theme in
  CSS alone (no memory across pages).

### Drawings: an SVG that is also the scene (#520)

- **The PWA draws them.** scrap has no renderer of drawings: the PWA's publish mode draws each
  drawing on the page with Excalidraw's `exportToSvg`, as the page view does, on white with its
  fonts inlined and `exportEmbedScene` on, so the one SVG is both the picture and the editable
  scene. A drawing of a photo has the photo under it (its 2048-pixel preview), so the file opens
  as the drawing over its whiteboard. Excalidraw's chunk loads only when publishing a page that
  has drawings; the app shell does not grow. The PWA reads each SVG back with Excalidraw's own
  `loadFromBlob` before sending it.
- **The upload carries them:** `PUT /api/pages/{key}/published` gains `drawings: [{key, svg}]`,
  and the HTML names each as `scrap-drawing:<id>` (its `img`, and a download link) and
  `scrap-excalidraw:<id>` (Open in Excalidraw).
- **scrap cleans every one**, never trusting it: exactly one Excalidraw scene block, in
  Excalidraw's own markers and encoding, decoded and kept by an allow-list; every embedded image
  only if its bytes are one of the page's photos, and then as that photo's 2048-pixel preview
  (no original bytes, no EXIF or GPS), else dropped; every text, and every link, by the page
  text's and links' rules (no address of scrap's own, no `/api/`, no private page); then the SVG
  through the SVG sanitiser of [](0042-mcp-clients-add-svg-and-files.md), its drawn images and
  text cleaned the same way, and the cleaned scene put back. It goes out as `img-<n>-<hex>.svg`,
  under the image CSP that runs and loads nothing, and counts toward the 20 files and 200 MiB.
- **No separate `.excalidraw` file** (the issue's first design): the SVG already carries the
  scene, so the receiver needs no new type and there is one file to clean, not two.
- **Photo | Drawing tabs in CSS alone**, as the app's: two radio inputs and their labels, which
  scrap's check allows in exactly that form (`type="radio"`, names and ids `pair-<n>…`, a
  `role="radiogroup"` div) and nothing else form-like. Without `:has()` both show.
- **Open in Excalidraw.** The page links each drawing to
  `https://excalidraw.com/#url=<the SVG's address on the site>` (in a new tab), which
  excalidraw.com fetches in the reader's browser and opens as a file: nothing is uploaded to
  Excalidraw. nginx sends `Access-Control-Allow-Origin: https://excalidraw.com` on a page's SVG
  images only, for that fetch. scrap writes the link itself from the site's `https` address, so it
  can name nothing but the drawing. `#url=` is undocumented on Excalidraw's side and could change;
  **Download** ("Download, then open in excalidraw.com to edit" where there is no Open link)
  stays as the fallback.
- **The warning** on Make public lists "its N drawings, downloadable" when the page has any.

### Consequences of the amendment

- Pages and tag pages run one script, the site's own; the attack surface is that file and the
  receiver's refusal of any other.
- A reader's theme and width are kept per browser; there is no account and nothing is sent.
- A whiteboard page shows its drawing, and anyone can download it, or open it on excalidraw.com,
  as an editable scene with the photo at preview size. Drawing elements' text and links are
  published as cleaned, like the page's own text.
- Publishing a page with drawings loads Excalidraw in the PWA and takes longer; a drawing that
  cannot be drawn fails the publish rather than going out half made.

(amendment-drawings-without-the-photo-and-the-sites-icon)=
## Amendment: drawings without the photo, and the site's icon (1.3.2, #524, #526, #527, #530)

Date: 2026-11-01

### A drawing replaces its photo (#524)

- **The drawing alone.** In the app a photo's drawing replaces the photo in its Drawing tab; it
  is not an overlay. 1.3.1 published the drawing over the photo's preview, which made it hard to
  read. The PWA now draws it as the app's Drawing tab does, framed as the photo is, with no photo
  under it. The Photo tab still shows the photo.
- **No photo in the scene either** (the owner's decision, 1 Nov 2026): the scene opened in
  Excalidraw is the drawing, as in the app, not the drawing on its whiteboard. So the one SVG is
  right for showing, opening and downloading, and no second file is needed.
- **scrap keeps no image in a drawing.** The cleaner drops every image element and file from the
  scene, and every `<image>`, `<feImage>` and image symbol from the picture, whatever they are:
  a drawing sent by 1.3.1's PWA, the photo under it, comes out as the drawing alone. Matching
  images to the page's photos by their bytes is no longer needed, so it is gone, and no photo
  bytes, original or preview, can go out in a drawing.

### An SVG is exactly `image/svg+xml` (#526)

- **The cause.** excalidraw.com opens `#url=` with `loadFromBlob`, which takes a file as an SVG
  only if the Blob's type is exactly `image/svg+xml`. nginx sent `image/svg+xml; charset=utf-8`,
  so the browser's Blob type had the parameter, Excalidraw read the SVG as JSON, and refused it
  ("doesn't contain valid Excalidraw JSON data"). The test in 1.3.1 built its Blob by hand, with
  the exact type, so it passed.
- **The fix.** nginx adds no `charset` to SVG (an SVG is XML, UTF-8 unless it says otherwise).
  The e2e test now fetches the published SVG from the site in the browser, as excalidraw.com
  does, and opens that Blob with `loadFromBlob`.
- **Turned down:** a sibling `.excalidraw` file for Open in Excalidraw. With the type fixed the
  SVG opens as it is, and without the photo there is nothing the SVG cannot carry.

### The site's icon (#527)

- **scrap's own icons**, `icon.svg` and `icon-192.png` from the PWA, are in the `assets` unit,
  and every page the site serves names them in `<head>`:
  `<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">` and
  `<link rel="apple-touch-icon" href="/assets/icon-192.png">`. scrap's check allows exactly
  these two links; the receiver allows exactly these two files, at the top of `assets` only, so
  `icon.svg` is the only SVG there, and it goes out under the image CSP.
- **`/favicon.ico`**, which browsers ask for on their own, is a `302` to `/assets/icon.svg`
  rather than a `404`, so an image or PDF opened alone has the icon too.
- **The scrap mark in the header** (the owner chose "mark + name" from a mock): `icon.svg` at
  about the line's height, left of the site's name on a page and of "Pages · Tags" on the
  site's own pages. It is `page.css` alone (a `::before` background, `img-src 'self'`), so no
  markup, check or receiver change. A long name is cut with "…" rather than wrapping under the
  switches.

### Tables as the app's (#530)

- A published table looked unlike the app's and broke words ("Dem/o" even at an 880 px
  column): the page's `overflow-wrap: anywhere` reached into it, so its first column could
  shrink to a letter while the long cells filled the column. `page.css` now has the app's table rules: the table in its own box that scrolls sideways
  (the page never does), sized to its content, a shaded header row, the app's smaller text and
  padding, and words kept whole. The markup was already the app's (`<div class="table">`), so
  nothing else changes.

### Consequences of the 1.3.2 amendment

- A published drawing shows and opens as the app shows it, without its whiteboard: a reader who
  wants the photo has the Photo tab. Pages published by 1.3.1 keep the overlay until the owner
  presses Refresh all after the deploy.
- The scrap-public image changes (nginx's types, the receiver's `assets` rule), so both images
  ship together, as before.

(amendment-mermaid-diagrams-drawn)=
## Amendment: Mermaid diagrams drawn (1.3.3, #525, #529)

A public page should look like the private one, and the app draws Mermaid diagrams. The owner
approved the design on a mock, 1 Nov 2026.

- **The PWA draws them, as drawings (#520).** The publish mode draws each diagram with the
  app's own Mermaid (its lazy chunk, loaded only for a page with one) and options, plus SVG
  labels (`htmlLabels: false`: no `foreignObject`, so the sanitiser keeps the words), the font
  stack named and a size from the `viewBox`, and sends the SVGs beside the page as
  `diagrams: [{key, light, dark}]`. The app shell does not grow.
- **Light and dark, by CSS.** Mermaid bakes its colours in, so each diagram is drawn twice
  (Mermaid's `neutral` and `dark` themes, as the app) and the page holds both `img`s
  (`scrap-diagram:<n>-light`, `-dark`) in a `figure.diagram`; `page.css` shows the one for the
  page's theme, light by default and with no script. The hidden one costs a download of about
  20 kB. Each counts toward the 20-file cap as an image.
- **scrap trusts neither SVG**: each goes through the SVG sanitiser, its text and attributes
  are scrubbed of scrap's own addresses, and a `<style>` naming one is refused. The page CSP,
  the image CSP and the receiver are unchanged (`img-*.svg` files, as drawings).
- **No Source fold** (the owner's choice, as the app has none). Search reads the diagram's
  words from its light SVG instead, so a node's label is found, and nothing shows twice.
- **A diagram Mermaid cannot draw so** goes out as its source, as before.
- **Code is left as written (#529).** In a code block and in a diagram, only scrap's own
  addresses (its hosts, `/api/blobs/`) become "a private link"; other `/api/...` paths are the
  code's own text (`API[/api/captures/]` stays, so a diagram's source still parses). scrap's
  check, which refuses only those addresses, is unchanged.
