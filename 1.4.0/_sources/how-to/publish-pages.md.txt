(publish-pages)=
# Publish pages

A public page is one anyone with its address can read, on a static site of its own
(`https://pages.example.org/p/<slug>`), without reaching scrap. The site also has a home page
listing the public pages, a page per tag, and a search box. scrap itself stays private. Why it
works this way is in [](../explanations/decisions/0043-public-pages-a-static-site-scrap-pushes-to.md);
the exact rules are in [](../reference/public-site.md).

## Set it up

The site is the `scrap-public` image: nginx serving the files, and a small receiver that only
scrap can write to. Install it with the chart's `public` section: see {ref}`k8s-public-pages`.
That gives scrap three settings ([](../reference/api.md)):

- `SCRAP_PUBLISH_TO`, the receiver's address inside the cluster;
- `SCRAP_PUBLISH_SITE`, the site's public address, for the links scrap shows;
- `SCRAP_PUBLISH_TOKEN_FILE`, the file holding the receiver's token (a mounted Secret; scrap
  never reads the token from an environment variable).

Without `SCRAP_PUBLISH_TO` and the token, publishing is off: pages can still be marked public
or private, and nothing is pushed. `GET /healthz` has a `publish` block saying whether
publishing is on and how the last check of the site went; it never fails the health check.

## Make a page public

In the app, open the page's **Share** menu and choose **Make public…**. The app says what goes
public with the page (its tags, Claude's write-up and summary, its attached files by name, its
drawings; links to private pages show their titles as plain text), and publishes it when you choose
**Make public**. The page shows a **Public** chip linking to its address.

What a public page holds:

- the page as the app shows it, with Claude's write-up and summary and the tags;
- its photos as their 2048-pixel previews, with no EXIF or GPS data, never the originals; SVG
  images made safe again; its other attached files (PDFs and the like), as stored, under new
  names;
- links to other public pages, which work on the site. A link to a private page shows its label,
  or the page's title, as plain text;
- maths and Mermaid diagrams as the app draws them, a diagram in the reader's light or dark
  theme. Code blocks are as written, but for scrap's own addresses;
- a photo's drawing, beside the photo with **Photo | Drawing** tabs as in the app, and links to
  **Open in Excalidraw** (on excalidraw.com, which fetches it from the site: nothing is uploaded
  to Excalidraw) and **Download**. The file is an SVG with the drawing inside it, so
  excalidraw.com, or any copy of Excalidraw, opens it for editing. As in the app, the drawing
  replaces the photo: it has no photo in it, and scrap removes from it any image and anything of
  scrap's own: its addresses and links to private pages. Open in Excalidraw needs the
  site on `https`; without it the page has only "Download, then open in excalidraw.com to edit".
  Saving a drawing in the app publishes the page again.

Readers choose a light or dark theme, and how wide the column is (as the app's Maximum column
width), with the two buttons at the end of the site's header; their browser keeps the choice
for every page. Pages are light until a reader chooses dark, and with JavaScript off.

Saving a public page in the app publishes it again. A page changed some other way (over MCP,
or a regenerated write-up) keeps its last published copy until you refresh it: **Settings →
Public pages → Refresh N pages** renders and publishes every public page again, and first asks
before publishing any that have never been published.

Claude can mark a page public over MCP (`edit_meta` with `public: true`, one page at a time),
but never publishes it: the page shows "Public · not published yet" until the app renders it,
by Refresh all or a save.

## Make a page private

Choose **Make private** in the Share menu (or `edit_meta` with `public: false`, any number of
pages at once). The page is taken off the site straight away: its address, the home page, its
tag pages and the search index. Moving a page to the trash does the same, and a `revert` that
turns the flag off too. Bringing a page back from the trash, or reverting to a public flag,
leaves it public but not published yet, until the app renders it again.

If the site cannot be reached at that moment, the page is still private; scrap finishes taking
it off the site within ten minutes.

Unpublishing reaches only the site. HTML is served `no-cache`, so a browser asks again before
showing a page, but a photo or file can be served from a cache for up to five minutes more, and
nothing reaches copies people saved.

## Keeping the site whole

scrap keeps a copy of everything it published, under `cache/publish/` in its data folder (not
backed up: it is made again by Refresh all). At start and every ten minutes it checks the site
against these copies: it takes off pages no longer public, rebuilds the home, tag and search
pages, puts back anything missing (a restarted site pod starts empty) and deletes anything the
site holds that it should not. Nothing needs the app for this.

Search engines are told not to index the site (`noindex`), unless the chart's
`public.indexing` is `true`.
