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
the page as scrap shows it, with no script, form, style or server address.

## Decision

- **A static site.** Public pages live on a static site, `https://pages.gkcluster.org` for the
  owner, served by nginx from a separate `scrap-public` image. The same image holds a small upload
  **receiver**: internal only, it needs a token, and all it can do is write or delete files in the
  site's directory. The public side has no database, no Python app of scrap's, no login and no
  route to scrap: nobody can ask it for anything that was not deliberately written out.
- **The PWA renders; there is no second renderer.** A public page is the PWA's own view of the page,
  written out by `pagehtml.ts` (in a publish mode) as one HTML file. Because it reads the
  rendered page, the public copy cannot drift from what scrap shows (KaTeX, tables, the Claude
  card). The PWA uploads the file to scrap on a new authenticated endpoint; scrap checks it, adds
  the page's files (below) and pushes the lot to the receiver.
  The PWA never talks to the receiver, and only scrap holds the token. scrap renders no
  Markdown for this.
- **The flag.** `page.public`, 0 or 1 (migration `0020_public_pages.sql`), set through
  `edit_meta(public=...)` like the other fields, so each change is a revision
  (`page_meta_rev.public_before` and `public_after`) that `revert` can undo. A page is made public
  one at a time; pages can be made private in bulk. The PWA shows a Public badge.
- **When a page is published.**
  - Turning Public on, after one OK or Cancel warning that the page's tags and Claude's write-up
    and summary go public too.
  - Saving a public page in the PWA.
  - **Links coming alive.** When a page is made public or private, the PWA also renders and uploads
    again the public pages that link to it (from its backlinks), so a label becomes a link, or a
    link a label, without anyone editing those pages.
  - **Settings, "Refresh all public pages".** One action renders and uploads every public page
    again. It covers what the PWA did not see: edits over MCP, a regenerated write-up, a change in
    scrap's look. There is no stale tracking, no outbox, no trigger and no render on the server:
    the owner presses Refresh all when he wants the site current.
  - **Publishing needs the network.** A save of a public page queued offline is saved but not
    published, with a toast: "Saved. Not published while offline: Refresh all public pages in
    Settings later." Publishes are never queued.
- **Unpublishing is immediate and done by scrap**, however the flag turns off or the page leaves:
  Public turned off in the PWA or over MCP, a `revert`, or the page going to the trash. scrap
  deletes the page's unit and its stored copy, then builds the home, tag and search units again,
  without the PWA. A `revert` that turns the flag back on publishes nothing by itself: the page
  goes out the next time the PWA renders it, or on Refresh all. Off always takes effect at once;
  on waits for a render.
- **URLs.** A page is at `/p/<slug>`, the same slug as in scrap. `/` is an index of the public
  pages with their tags, and `/t/<key>` lists one tag's pages. A tag's key is an ASCII slug of
  the tag (at most 60 characters), `-`, and 8 hex digits of the tag's SHA-256, so
  `personal/family` is `personal-family-1a2b3c4d`: scrap's tags may hold spaces, `/` and letters
  outside ASCII, and two tags with the same slug still get different keys. Pagefind gives search
  with a static index, so search needs no server either. Everything is `noindex`: an
  `X-Robots-Tag: noindex, nofollow` header on every response and a `robots.txt` of `Disallow: /`.
- **What a public page holds.**
  - The body as shown, Claude's write-up and summary, and the tags.
  - Links to public pages stay links; a link to a private page shows its label only, with no
    address (a slug comes from a title and can say more than the label).
  - The links scrap adds itself (Linked from, Related) only where the other page is public.
  - Left out: Claude's notes (a photo's description, the read text, the drawing), revisions, the
    extracted text of files, and every `/api` or other private address.
- **Images and attached files are files of the page, not inlined.** The PWA's publish mode
  writes each `<img src>` and file link as a placeholder naming the stored file's sha
  (`scrap-blob:<sha>`). scrap swaps each one for an absolute path, `/p/<slug>/<name>`, under a
  new name: `img-<n>-<hex>.jpg`, `.png` or `.svg` for an image and `file-<n>-<hex>.<ext>` for
  another file (a PDF, a `.md`), where `<hex>` is the first 10 hex digits of the SHA-256 of the
  bytes published. Neither the sha nor the uploaded file name is used (a link's label may still
  show the name). scrap copies the bytes itself: a photo's 2048-pixel preview (EXIF and GPS
  already stripped by `preview._make`), an SVG as the sanitised copy it stores
  ([](0042-mcp-clients-add-svg-and-files.md)), and other files as stored. `pagehtml.ts` drops
  `svg` elements today, so its publish mode must keep SVG embeds, as images. The HTML stays small,
  well inside the receiver's 20 MiB a file. In this first version a page publishes at most 20
  images and files; over that the publish is refused, saying why.
- **scrap keeps what it pushed.** The last HTML uploaded for each public page is kept at
  `<data>/cache/publish/p/<slug>/index.html`: derived data, not backed up. From these copies
  scrap builds the home page, the tag pages and the Pagefind index (the `pagefind[bin]` Python
  package, at a pinned version), and **reconciles** the site: at startup and every 10 minutes it
  reads the receiver's manifest and pushes or deletes units until the site matches the copies
  (a page's files are copied from its store again). Nothing is rendered for that, so a site that lost its files is refilled without the PWA.
- **Index pages and search are built by scrap**, from its kept copies, with plain Python templates
  (no Markdown), and each is pushed as a unit of its own.
- **The receiver contract** is fixed in [](../../reference/public-site.md). In short: HTTP/1.1
  with a bearer token of at least 32 characters; the site is made of **units** (a page
  `p/<slug>`, a tag `t/<key>`, `home` and `pagefind`), each replaced whole by a `PUT` of a tar
  and swapped in atomically, or removed by an idempotent `DELETE`; `POST /v1/sync` deletes every
  unit not in a list; `GET /v1/manifest` says what is there. Paths, file names, sizes and the
  site's total are checked strictly, and a digest over the files catches a damaged upload.
- **Kubernetes first.** The chart gets a `public` section, off by default:
  - a `scrap-public` namespace under Pod Security `restricted`;
  - a NetworkPolicy that lets only scrap's pod reach the receiver, and no egress at all from the
    public pods;
  - the token in a Secret the chart names but never creates (as for scrap's other secrets);
  - nginx alone behind an Ingress; the receiver has a cluster-internal Service only;
  - the site in an `emptyDir` shared by nginx (read only) and the receiver: a restarted pod comes
    back empty and scrap's reconcile fills it again, with no Refresh all.

  The single-server install (a second rootless podman service under its own user, the receiver on
  a Unix socket, the ADR 18 pattern) is later work in a follow-up issue.
- **Unpublishing and caches.** A delete removes the page from the site, from the home and tag pages
  and from the search index. HTML is served `no-cache`, so a browser or proxy asks again before
  showing it; other files are `max-age=300`, so a copy can live up to five minutes more. Nothing
  can reach copies people saved, or caches outside the site's control. The docs say so plainly.
- **Headers.** HTML gets a strict CSP that allows only Pagefind's script, from the site, with
  `connect-src 'self'` for the index it fetches; there is no inline script. A page's files get the
  headers ADR 42 gives stored files: a sandboxing CSP that loads nothing, and for a PDF `sandbox`
  alone, so a browser's PDF viewer works.
- **The scrap-to-gist skill is removed** from the repo: `skills/scrap-to-gist/`, its tests, its
  `install.sh` entry and its docs. `install.sh` does not delete a copy already installed in
  `~/.claude/skills/scrap-to-gist`: it is the owner's to remove.

## Consequences

- A page can be shown to anyone without scrap being reachable: the internet reaches only nginx
  serving files, and the receiver accepts only scrap. A bug in scrap's API cannot leak through
  the public site, which holds only what was pushed to it.
- A public page looks exactly as it does in scrap, with no second renderer to keep in step.
- The site is only as current as the last render. A page edited over MCP, or whose write-up was
  regenerated, keeps its old public copy until it is saved in the PWA or Refresh all is pressed.
  Unpublishing never waits.
- Publishing needs the PWA open on the owner's device; MCP can set the flag, but not render.
- Tags, Claude's write-up and the summary are public with the page.
- A public page that links to a page unpublished without the PWA's re-render (over MCP, by a
  revert or by the trash) keeps a live link to a 404 until Refresh all, the PWA's re-render of
  linking pages, or that page's next save. That is accepted: there is no stale tracking.
- A public page's photos are its 2048-pixel previews, and at most 20 images and files go with it.
- The site can be lost and rebuilt at any time; scrap's data folder holds the copy that matters.
- scrap gains settings for the push (`SCRAP_PUBLISH_TO`, `SCRAP_PUBLISH_SITE`,
  `SCRAP_PUBLISH_TOKEN` or `SCRAP_PUBLISH_TOKEN_FILE`); without them the feature is off.
- CI builds and publishes a second image, `scrap-public`, beside scrap's, and scrap gains the
  `pagefind[bin]` dependency.
- The gist workflow goes: no `gh` token with the `gist` scope, no headless Chrome, no second
  Markdown renderer. Gists already made stay as they are.
