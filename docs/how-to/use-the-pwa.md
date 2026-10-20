# Capture from your phone (the PWA)

scrap serves a small web app (a PWA) at the root of its address: capture, one screen of pages
to browse and search, and a page view. It is built for one-handed use on a phone and keeps working offline.

## Install it on Android

1. Open scrap's HTTPS address (for example the `tailscale serve` URL from
   [](deploy-single-server.md)) in Chrome. A PWA needs HTTPS; `http://127.0.0.1` also works for
   trying it out on the server itself.
2. Chrome menu, **Add to home screen** (or **Install app**), then **Install**.
3. Open scrap from its icon. It opens on the capture screen, in its own window.

Installing is what puts scrap in the Android **share sheet**.

## Capture

| Button | Does |
| --- | --- |
| **Camera** | Opens the camera |
| **Gallery** | Picks one or more images from the phone |
| **Note** | A text box; a pasted link alone becomes a link capture |

The buttons say how you capture, not what the page is. Its **kind** is chosen in the composer
(and changed later in the page's editor) with the row of chips above the text: **Note** (the
default), **Todo**, **Read** (to read later), **Board** (a whiteboard) or **Doc** (a document). A link on its own
picks **Read** for you until you pick something else. Photos skip the choice: Claude reads them
and makes a whiteboard or document a page of that kind, and you can change it after. A kind
you choose is kept: Claude never changes it. Changing a kind loses nothing: what the page
already has (a status, a due date, a summary) stays, and the new kind adds what it lacks, so
changing it back gives the page as it was.

In the composer, **Camera** and **Gallery** add more photos (to a note too), and the cross
on a thumbnail removes one: all the photos and the text become one capture and one page.
If the photos together are over the server's upload limit (it tells the app, which remembers
it for offline use), Save says so: remove some, or **Save separately**, one capture per photo
with the text and kind on the first.
**Save** returns at once: the capture is stored on the phone first and uploaded in the
background. The four newest pages are listed above the buttons.

## Share into scrap

From any Android app, **Share**, then **scrap**. Links, text, photos and other files are queued
like any other capture and the app opens on the capture screen saying *Shared item saved*.
Android often sends a link as text after the page title; scrap keeps the title as the note and
the link as the capture's URL.

## The offline queue

- Every capture gets its id (a ULID) on the phone before it is queued, so an upload that is
  retried after a lost answer saves it once, not twice.
- The queue lives in the browser's IndexedDB (photos as they are, not re-encoded) and survives
  closing the app and restarting the phone.
- The header badge shows what is on the phone: **2 waiting**, **1 failed**. Tap it to retry
  everything now. Waiting items are also listed at the top of the capture and search screens.
  Opening scrap, coming back to it or coming back online sends what waits at once (another
  tab's upload first, if one is running). A screen still waiting for the server after a moment
  says *Loading…*, and an upload that drops while the phone is online says *connection lost*.
- Uploads start at once, again when the phone comes back online, whenever the app is opened or
  brought to the front, and on a timer with backoff (2 s doubling to 5 minutes) while it is open.
  Android gives web apps no reliable background upload, so a capture made offline uploads the
  next time scrap is open with a connection.
- A capture the server refuses (for example over the upload limit, `413`) is marked **failed**
  with the server's reason, and stays on the phone with **Retry** and **Discard** (which asks
  first, then deletes it and its photos from the phone). A multi-photo capture refused as too
  large offers **Split and retry** instead of Retry: one capture per photo, text and kind on the first.
- A slow upload may take as long as it needs while it keeps moving (up to 15 minutes); one with
  no progress for a minute is given up and retried later. Once the phone has handed over the whole
  upload, it waits at least two minutes for the answer (longer for big uploads, which may still
  be draining from the phone's network buffer). Network and server errors just wait
  and retry.
- If the phone refuses to store a capture (storage full), the composer stays open with your text
  and photos and says so. A share that cannot be stored goes straight to the server instead, or,
  with no connection either, shows a page saying it was not saved.
- Two open scrap tabs take turns (Web Locks), so one capture is never uploaded twice at once.
- Clearing the site's data in Chrome deletes anything still queued.

## View, edit, search

- The nav has two tabs, **Capture** and **Search**. **Search** opens the one list screen: with
  nothing in the search box it lists every page newest first, with a thumbnail of the first
  photo (**Show more** at the end for older ones). The keyboard only comes up when you tap the
  box. (There is no separate Recent screen any more: the empty box is it.)
- Under the search box, a fixed row of kinds: **All**, **Notes**, **Todos**, **Reads**,
  **Boards**, **Docs**. One tap shows only that kind (it writes `kind:todo` into the query), a
  second tap on it (or **All**) shows every kind again. A kind alone still lists newest first.
- Whenever anything is chosen or typed, a **Clear** chip starts the row of chips below: one tap
  goes back to every page, newest first.
- The query and its filters are in the address (`/search?q=...`), so a reload keeps them, and
  Back from a page, or deleting it, comes back to the same list, scrolled where it was. Old
  `/recent` links open this screen (`/recent?kind=todo` with Todos on).
- Todos and Read pages carry a status (open, in progress, done or cancelled). The page's
  toolbar has **Done** unless it is done, and **Reopen** if it is done or cancelled (a
  cancelled one has both). In the list, the capture screen's list and search results, their
  rows have a tick box on the right: tap it (or Tab to it and press Space) to tick it off, or to
  open it again; the row stays where it is and its chip says *done* (or *cancelled*). Ticking
  it or changing a kind doesn't move the page up the list.
- Swipe a row of the list, the capture screen's list or search results: to the **right** to
  edit it (the page opens in its editor), to the **left** to delete it (with **Undo** for a few
  seconds). The row follows your finger with *Edit* or *Delete* showing behind it; past a third
  of the way (or with a quick flick) the icon grows, and letting go does it. Let go sooner and
  it slides back. The page itself has the same Edit and Delete.
- A photo capture's photos are part of its page's text, one line each (`![](/api/blobs/...)`),
  in the order taken: edit the text to move or remove them. Claude reading a photo never
  changes the text. The page shows each photo where its line is, as a preview the server makes
  (so iPhone HEIC photos show too), with its file name, a **Download** of the original and
  **Ask Claude**, which sends that photo to Claude; once sent, the photo shows Claude's
  progress (waiting, reading, paused) and then what it read, described and drew. Below the text
  are the files it doesn't show, such as PDFs, as links with a **Download**.
- Deleting a photo's line deletes the photo from the page. **Save** warns first, naming each
  photo whose line went: *deleted*, or *still used by N other pages* if other pages show it too
  (it stays there). **Cancel** goes back to the editor with your text as it was (undo brings the
  line back); **OK** saves. The file and what Claude made of it are kept while anything still
  uses it; the nightly `scrap gc` deletes files nothing uses.
- Tap a photo to view it full screen: it opens fitted to the screen; pinch or double-tap to zoom,
  drag to pan, swipe (or the arrows) for the page's other photos. **Fit**, **100%**,
  **Download** and **Share** are along the bottom and the cross at the top right closes it, as
  does the phone's Back button. **Share** asks **Link** or **Photo**: **Link** sends the
  address of the photo's page; **Photo** sends the photo to another app: the original, or a
  JPEG of it if it is a HEIC or over 20 MB. If a big photo takes longer to download than the
  phone allows, a **Photo ready** message offers **Share** again.
- **Download** on a page saves it as Markdown, or as a zip of the Markdown and its files when it
  has any; its photos are in the zip and its text points at them there. **Share** asks
  **Link** or **Text**: **Link** sends the page's address (such as
  `https://<your scrap>/p/shopping-list`), which opens the page for anyone who can reach your
  scrap; **Text** sends its title and text, as typed but without the lines that only show a
  photo (no link to scrap in it). Tap **Share** again, or anywhere else, to close the choice.
  Share appears only where the browser can share.
- Page text is shown as Markdown (headings, **bold**, *italic*, lists, quotes, code, links);
  it is always stored as typed, and **Edit** shows it so.
- A page opened from the list or a search shows where it is in that list (*3 of 23 ·
  Recent*): swipe left for the next one and right for the previous one, or use the ‹ › beside
  it (or the arrow keys). The page follows your finger and slides away to the next one; a short
  drag settles back, and at the first or last it only gives a little and says so. Back returns to the list. Swipes start
  away from the screen's edges (the phone's own Back gesture lives there) and are ignored on
  text that scrolls sideways, while zoomed in or while selecting text.
- **Edit** changes the title and text in a full-screen editor, like the composer: **Cancel**,
  **Preview** and **Save** stay at its top, clear of the keyboard, and Ctrl+Enter saves.
- Nothing typed is lost: the composer and **Edit** keep a draft on the phone as you type
  (photos too), so after the phone's Back button, a reload or a closed app, opening them again
  brings it back (**Discard it** drops it); a page with a kept edit shows **Edit draft**. Back closes the editor, not the app. **Cancel** asks
  before discarding changes. If the page was changed elsewhere since you opened it, the
  other version is shown under yours: merge what you want into your text and save again (this
  overwrites theirs), or discard yours.
- **Delete** moves the page to the trash, with **Undo** for a few seconds, and goes back to the
  list or search it was opened from (else to every page, newest first).

## What Claude made of a photo

With Claude ingest on (see [](../explanations/ingest.md)), each photo on a page has, under it:

- Its state: *Waiting for Claude* (or *Claude ingest is off*), *Claude is reading it*, *Read by
  Claude*, *Failed* with the reason and **Retry**, or *Paused* with the reason and **Resume**
  (nothing is lost while paused). The page checks again every 10 seconds while a photo waits.
  **Reprocess** sends it to Claude again; if you have edited its drawing, it asks first:
  **Replace mine**, or **Keep mine** (Claude's new drawing goes into History).
- **Description** and **Text Claude read**, open; tap a heading (its arrow) to fold it away,
  and the phone remembers that for the next page. The text can be selected and copied.
- **The drawing** of a whiteboard or diagram, beside the photo when the screen is wide enough
  (a tablet, or a phone on its side), else under a **Photo** / **Drawing** switch. It is a
  picture: it scrolls with the page and takes no gestures. It lines up with the photo, since
  the drawing is made in the photo's own pixels.

Tap the drawing to open it full screen:

- Pinch and drag to zoom and pan; **Fit** shows all of it again. **Photo** shows the photo
  beside the drawing (on its side) or over it (upright), to compare. The phone's Back button
  closes it.
- **Edit** turns on Excalidraw's tools (draw, shapes, arrows, text, the eraser; not images).
  **Undo** is in the top bar, **Cancel** puts the drawing back, **Save** stores it as a new
  version. Zoom, scroll and the edit are kept when switching between viewing and editing.
- Nothing drawn is lost: the edit is kept as a draft on the phone as you draw, so after Back, a
  failed save, a reload or a closed app, **Edit** (with a dot, and a line under the bar
  saying so) brings it back
  (**Discard it** drops it). If the drawing was changed elsewhere meanwhile, saving says so:
  **Save mine** adds yours as a newer version (theirs stays in History), or **Discard mine,
  show theirs**.
- **More**, **History** lists every version (Claude's, yours, restored ones) with **Restore**,
  which makes an old version current again as a new copy: nothing is ever overwritten.
- **More**, **Export** saves the drawing as `.excalidraw` (opens in excalidraw.com or the
  Excalidraw app), PNG or SVG. The page's **Download** zip has it too, beside the photo, with
  the description and text in the Markdown.
- The drawing follows the phone's light or dark theme. Viewing a drawing needs the server: the
  app shell works offline, but a page and its drawing are not cached.
- Excalidraw is loaded only when a drawing is first shown (about 435 kB over the network, as
  scrap compresses it; 1.46 MB unpacked; then cached by the browser), never for capture or the
  search screen. Its fonts are served by scrap itself, never
  from a CDN; Chinese, Japanese and Korean handwriting falls back to a system font.
- **Search** searches titles, tags, summaries and text as you type (each word as the start of a
  word: `vsc` finds `vscode`); a title or tag match ranks first. Under the results, chips say how many pages were found and what they have in common
  (Work or Personal and their top tags, each with a count; kinds are the fixed row above): tap one to narrow the
  search, tap a chip of the query's own filters to take it out. The chips only write the query,
  which you can also type: `-word` or `!word` (without it), `"a phrase"`, `kind:todo` (or
  `kind:read`, `kind:board`...), `tag:tech` (also `tech/epics`; `tag:epics` finds `tech/epics`
  too), `is:personal`, `is:work` (a page not marked personal), `is:claude` (pages Claude wrote over MCP, which show a *Written by Claude* badge), `has:image` (pages with a photo), `image:photo` or `image:whiteboard` (what Claude took the photo for), `is:done` (any status), `after:1w` or
  `before:2026-03-01` (last edited; dates are UTC days, both ends included; add `date:created`
  for when it was made). The chip row also has **Tags** (browse them), **1w**, **1m**, **1y**
  and **Dates…** (pick a From and a To).
  Filters alone list their pages, newest first.
- A page shows its **tags** in one line under its title, most used first (swipe it for more):
  tap one to search for it. **Tags** (the first chip under the search box) lists every tag with how many pages have it, as a tree (open a parent with its
  arrow), A to Z or most used first, with a box to filter it.

## Licences of the drawing fonts

The drawing viewer is [Excalidraw](https://github.com/excalidraw/excalidraw) (MIT). scrap serves
the drawing fonts that come with it: Excalifont, Virgil, Nunito, Lilita One, Cascadia Code and
Liberation Sans under the SIL Open Font License 1.1, and Comic Shanns under the MIT licence;
Excalidraw's interface font, Assistant, is OFL 1.1 too. The CJK font (Xiaolai, 14 MB) is left
out.

## Troubleshooting the screen layout

Tapping the build id at the bottom of the search screen five times turns on a small debug panel of
viewport numbers (and five more taps turn it off). It helps to report how a phone's keyboard
resizes the page.

## Updates

The app's files are cached on the phone so it opens instantly and offline, the composer and
editor included; API answers and files are never cached. Some parts load only when first used
and are not cached ahead: a page's pager and list swipes, what Claude made of a photo, and the
drawing viewer. So a page opened offline from a list has no ‹ › pager, and rows don't swipe. After a new scrap is deployed, the app shows **Update available,
Reload**. Until you tap it the old version keeps running; it is also replaced the next time the
app is opened after being closed.

## iPhone and iPad

Safari can add scrap to the home screen and capture, view, search and the offline queue work, with
these limits:

- **No share target**: scrap does not appear in the iOS share sheet. A Shortcut that posts to
  `POST /api/captures` (see [](../reference/api.md)) can stand in.
- iOS may evict a home-screen app's storage after weeks of non-use, which would drop anything
  still queued; open it once a connection is back.

## Build it (developers)

The PWA's source is in `web/` (TypeScript, Vite, no UI framework; the drawing viewer in
`web/src/board/` uses Excalidraw and React, in a chunk of its own). The container image builds
it; for `scrap serve` from a checkout, build it once with Node 22:

```sh
npm --prefix web ci
npm --prefix web run build   # writes src/scrap/static/, which scrap serve picks up
```

Without it `scrap serve` still serves the API, and `/` says how to build the app. For working on
the app, run `scrap serve` and `npm --prefix web run dev` (Vite proxies `/api` to port 8000).
Checks: `npm --prefix web run check` (Biome, TypeScript), `npm --prefix web test` (unit tests),
`npm --prefix web run size` (after a build: the app shell stays within its size budget and
never loads Excalidraw),
`npm --prefix web run e2e` (Playwright against a real `scrap serve` on a throwaway data folder).
