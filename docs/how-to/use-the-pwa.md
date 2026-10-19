# Capture from your phone (the PWA)

scrap serves a small web app (a PWA) at the root of its address: capture, recent pages, search
and a page view. It is built for one-handed use on a phone and keeps working offline.

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
| **Photo** | Opens the camera |
| **Gallery** | Picks one or more images from the phone |
| **Note** | A text box; a pasted link alone becomes a link capture |
| **Todo**, **Read later** | A note with a hint that fixes the page kind (`todo`, `consume`) |

In the composer, **+ Camera** and **+ Gallery** add more photos (to a note too), and the cross
on a thumbnail removes one: all the photos and the text become one capture and one page.
If the photos together are over the server's upload limit (it tells the app, which remembers
it for offline use), Save says so: remove some, or **Save separately**, one capture per photo
with the text and hint on the first.
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
  everything now. Waiting items are also listed at the top of the capture and Recent screens.
- Uploads start at once, again when the phone comes back online, whenever the app is opened or
  brought to the front, and on a timer with backoff (2 s doubling to 5 minutes) while it is open.
  Android gives web apps no reliable background upload, so a capture made offline uploads the
  next time scrap is open with a connection.
- A capture the server refuses (for example over the upload limit, `413`) is marked **failed**
  with the server's reason, and stays on the phone with **Retry** and **Discard** (which asks
  first, then deletes it and its photos from the phone). A multi-photo capture refused as too
  large offers **Split and retry** instead of Retry: one capture per photo, text and hint on the first.
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

- **Recent** lists pages newest first, with a thumbnail of the first photo.
- A page shows its text and its files: photos inline (as previews the server makes, so iPhone HEIC
  photos show too), other files as links. Each has a **Download** of the original.
- Tap a photo to view it full screen: it opens fitted to the screen; pinch or double-tap to zoom,
  drag to pan, swipe (or the arrows) for the page's other photos. **Fit**, **100%**,
  **Download** and **Close** are along the bottom; the phone's Back button closes it too.
- **Download** on a page saves it as Markdown, or as a zip of the Markdown and its files when it
  has any.
- Page text is shown as Markdown (headings, **bold**, *italic*, lists, quotes, code, links);
  **Raw text** shows it exactly as typed, and the phone remembers the choice. The text is
  always stored as typed.
- **Edit** changes the title and text in a full-screen editor, like the composer: **Cancel**,
  **Preview** and **Save** stay at its top, clear of the keyboard, and Ctrl+Enter saves.
- Nothing typed is lost: the composer and **Edit** keep a draft on the phone as you type
  (photos too), so after the phone's Back button, a reload or a closed app, opening them again
  brings it back (**Discard it** drops it). Back closes the editor, not the app. **Cancel** asks
  before discarding changes. If the page was changed elsewhere since you opened it, the
  other version is shown under yours: merge what you want into your text and save again (this
  overwrites theirs), or discard yours.
- **Delete** moves the page to the trash, with **Undo** for a few seconds.
- **Search** searches titles and text as you type.

## Troubleshooting the screen layout

Tapping the build id at the bottom of **Recent** five times turns on a small debug panel of
viewport numbers (and five more taps turn it off). It helps to report how a phone's keyboard
resizes the page.

## Updates

The app's files are cached on the phone so it opens instantly and offline; API answers and
files are never cached. After a new scrap is deployed, the app shows **Update available,
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

The PWA's source is in `web/` (TypeScript, Vite, no UI framework). The container image builds
it; for `scrap serve` from a checkout, build it once with Node 22:

```sh
npm --prefix web ci
npm --prefix web run build   # writes src/scrap/static/, which scrap serve picks up
```

Without it `scrap serve` still serves the API, and `/` says how to build the app. For working on
the app, run `scrap serve` and `npm --prefix web run dev` (Vite proxies `/api` to port 8000).
Checks: `npm --prefix web run check` (Biome, TypeScript), `npm --prefix web test` (unit tests),
`npm --prefix web run e2e` (Playwright against a real `scrap serve` on a throwaway data folder).
