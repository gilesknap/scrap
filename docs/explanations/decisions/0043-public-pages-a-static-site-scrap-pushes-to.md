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
  written out by `pagehtml.ts` as one HTML file. Because it reads the rendered page, the public
  copy cannot drift from what scrap shows (KaTeX, tables, the Claude card). The PWA uploads the
  file to scrap on a new authenticated endpoint; scrap checks it and pushes it to the receiver.
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
- **Unpublishing is immediate and done by scrap.** Turning Public off, or the page going to the
  trash, deletes it from the site at once, without the PWA. A `revert` that turns the flag off
  does too. A `revert` that turns it back on does not publish anything by itself: the page goes
  out the next time the PWA renders it, or on Refresh all. Off always takes effect at once; on
  waits for a render.
- **URLs.** A page is at `/p/<slug>`, the same slug as in scrap. `/` is an index of the public
  pages with their tags, and `/t/<key>` lists one tag's pages. Pagefind gives search with a static
  index, so search needs no server either. Everything is `noindex`: an
  `X-Robots-Tag: noindex, nofollow` header on every response and a `robots.txt` of `Disallow: /`.
- **What a public page holds.**
  - The body as shown, Claude's write-up and summary, and the tags.
  - Links to public pages stay links; a link to a private page shows its label only, with no
    address (a slug comes from a title and can say more than the label).
  - The links scrap adds itself (Linked from, Related) only where the other page is public.
  - Left out: Claude's notes (a photo's description, the read text, the drawing), revisions, the
    extracted text of files, and every `/api` or other private address.
- **Images** are inlined in the HTML file. A photo is its 2048-pixel preview (EXIF and GPS already
  stripped by `preview._make`), not the 480-pixel one Share as HTML uses. An SVG is the sanitised
  copy scrap stores ([](0042-mcp-clients-add-svg-and-files.md)); `pagehtml.ts` drops `svg`
  elements today, so the public render must keep SVG embeds (as images).
- **Attached files that are not images** (a PDF, a `.md`) are published too: uploaded with the
  page as separate files, under new names (neither the sha nor the uploaded file name, though the
  link's label may show the name), and the page links to them.
- **Index pages and search are built by scrap.** From the HTML it was given, scrap builds the home
  page, the tag pages and the Pagefind index with plain Python templates (no Markdown), and pushes
  each as a unit of its own.
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
  - nginx alone behind an Ingress; the receiver has a cluster-internal Service only.

  The single-server install (a second rootless podman service under its own user, the receiver on
  a Unix socket, the ADR 18 pattern) is later work in a follow-up issue.
- **Unpublishing and caches.** A delete removes the page from the site, from the home and tag pages
  and from the search index. HTML is served `no-cache`, so a browser or proxy asks again before
  showing it; other files are `max-age=300`, so a copy can live up to five minutes more. Nothing
  can reach copies people saved, or caches outside the site's control. The docs say so plainly.
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
- Tags, Claude's write-up and the summary are public with the page. A link to a page made private,
  or trashed, from scrap's side (not by the PWA) stays a dead link on other public pages, pointing
  at a 404, until they are rendered again.
- scrap gains settings for the push (`SCRAP_PUBLISH_TO`, `SCRAP_PUBLISH_SITE`,
  `SCRAP_PUBLISH_TOKEN` or `SCRAP_PUBLISH_TOKEN_FILE`); without them the feature is off.
- CI builds and publishes a second image, `scrap-public`, beside scrap's.
- The gist workflow goes: no `gh` token with the `gist` scope, no headless Chrome, no second
  Markdown renderer. Gists already made stay as they are.
- Left to the implementation: how a tag becomes a `/t/<key>` key (scrap's tags can hold spaces,
  `/` and non-ASCII letters, the key cannot); where scrap keeps the HTML it was given, which it
  needs to build the index units again; whether the site's volume survives a restart, or scrap
  fills it again from the manifest; and how attachments' new names reach the PWA's render.
