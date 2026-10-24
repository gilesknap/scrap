# Capture from your phone (the PWA)

scrap serves a web app (a PWA) at the root of its address. It is built for one-handed use on a
phone and has three tabs: **Capture** (the composer, camera and gallery, the share target and
the offline queue), **Todos** (what to do now, soon, or ever) and **Search** (every page, newest
first, with kinds, filters and tags). Opening a page gives a page view with an editor, photo and
drawing viewers and, with Claude on, what Claude made of it.

This page covers, in order: installing it, capturing, sharing into scrap, the offline queue, what
scrap stores on the phone and what works offline; then viewing, editing and searching (navigating
and the keyboard, search and its syntax, tags, todos, the page view, editing and deleting); what
Claude makes of a photo and of a note or link;
the iPhone and iPad limits, updates and the screen-layout debug panel; and, for developers, how
to build the app, with the licences of what it bundles.

## Install it on Android

1. Open scrap's HTTPS address in Chrome. A PWA needs HTTPS; `http://127.0.0.1` also works for
   trying it out on the server itself. Get an address with the `tailscale serve` URL from
   [](deploy-single-server.md), or the Tailscale operator or an ingress from
   [](deploy-kubernetes.md).
2. Chrome menu, **Add to home screen** (or **Install app**), then **Install**.
3. Open scrap from its icon. It opens on the capture screen, in its own window.

Installing is what puts scrap in the Android **share sheet**.

scrap has no login of its own: anyone who can reach its address can use the app, so reach it
only over your tailnet or behind a proxy that authenticates (see [](../reference/api.md)).

## Capture

| Button | Does |
| --- | --- |
| **Camera** | Opens the camera |
| **Gallery** | Picks one or more images from the phone |
| **Note** | A text box; a pasted link alone becomes a link capture |

The buttons say how you capture, not what the page is. Its **kind** is chosen in the composer
(and changed later in the page's editor) with the row of chips above the text: **Note** (the
default), **Todo**, **Later** (to read, watch or listen to later), **Board** (a whiteboard) or **Doc** (a document). A link on its own
picks **Later** for you until you pick something else. Photos skip the choice: Claude reads them
and makes a whiteboard or document a page of that kind, and you can change it after. A kind
you choose is kept: Claude never changes it. Changing a kind loses nothing: what the page
already has (a status, a due date, a summary) stays, and the new kind adds what it lacks, so
changing it back gives the page as it was. While the kind is **Todo** (and there are no
photos), the composer also has the todo's **Due** date (**Today**, **Tomorrow**, **Next week**
or a date) and **Priority**, as on its page; the text box asks *What needs doing?*. The due
date and the tags are each folded into one line above the text (**Due** *24 Oct · high*,
**Tags** *2 · #home #garden*), so the text stays in front: tap the line to open it, and again to
fold it.

In the composer, **Camera** and **Gallery** add more photos (to a note too), and the cross
on a thumbnail removes one: all the photos and the text become one capture and one page.
If the photos together are over the server's upload limit (50 MB by default, set with
`SCRAP_MAX_UPLOAD_MB`: see [](../reference/api.md); the server tells the app, which remembers
it for offline use), Save says so: remove some, or **Save separately**, one capture per photo
with the text on the first. A proxy in front of scrap may have a lower limit of its own.
The **Tags** line opens a tags box that works as on a page (see Tags, below): type a tag and press Enter
or a comma, or tap one of the tags offered in a row under the box (your most used tags, or as
you type, the tags in use that match); tap a tag's ✕ to take it off; what is still in the box
when you save counts too. The page is made with its tags, so search finds it by them at once,
also when it was saved offline and uploaded later. A photo you tag keeps your tags, and Claude's
join them when it first reads the photo (a later Reprocess adds its tags only to a page with
none, so one you took off stays off). Saved separately, every photo's page gets the tags.
**Save** returns at once: the capture is stored on the phone first and uploaded in the
background. The four newest pages are listed above the buttons.

Leave the composer with the phone's Back and what you typed is kept as a **draft**: a row over
the buttons (its kind's icon, *Draft:* and its first line). Tap it to carry on, or its **✕** to
discard it (with **Undo**). The buttons (and **New todo**) always start a fresh capture: left by
Back with something in it, the fresh one takes the older draft's place, and **Undo** in the
message puts the older one back. There is one kept draft at a time. The fresh one is kept on
the phone as you type too, so if the app is closed or killed before you save it (a phone short
of memory may do that after the camera), it is the draft the next time you open scrap, again
with **Undo** for the older one.

## Share into scrap

From any Android app, **Share**, then **scrap**. Links, text, photos and other files (scrap's
share target accepts any file type) are queued like any other capture and the app opens on the
capture screen saying *Shared item saved*. The service worker queues the share on the phone, so
it is saved even if the app was not open; the capture is recorded with source `share`. What
becomes of what was shared:

- **The link** is the shared URL, or, if there is none, a link at the very end of the shared
  text. Android often sends a link as text after the page title, so scrap takes the link off the
  end and keeps the rest as the note.
- **The note** is the shared text, with the shared title put in front of it as its first line,
  which titles the page, unless the text already contains the title.
- **Files** of zero size are dropped.
- A share with no text, link or usable file is ignored: the app opens on the capture screen with
  no message.

## The offline queue

- Every capture gets its id (a ULID) on the phone before it is queued, so an upload that is
  retried after a lost answer saves it once, not twice.
- The queue lives in the browser's IndexedDB (photos as they are, not re-encoded) and survives
  closing the app and restarting the phone.
- The header badge shows what is on the phone: **2 waiting · 1 failed**. Tap it to retry
  everything now. Waiting items are also listed at the top of the capture and search screens,
  oldest first; a row says *waiting to upload* with the last problem after it (*offline*, *server
  error (503)*, *connection lost*, *timed out*), or *not saved* with the server's reason.
  Offline, the capture screen shows the badge, the waiting rows and one quiet line, *Offline:
  showing what's on this phone*, in place of the newest pages: no error card, no Retry, no
  message on Save (the waiting row says it). When the phone is back online the newest pages
  come back by themselves.
  Opening scrap, coming back to it or coming back online sends what waits at once (another
  tab's upload first, if one is running). A screen still waiting for the server after a moment
  says *Loading…*, and an upload that drops while the phone is online says *connection lost*.
- Uploads start at once, again when the phone comes back online, whenever the app is opened or
  brought to the front, and on a timer with backoff (2 s doubling to 5 minutes) while it is open.
  Android gives web apps no reliable background upload, so a capture made offline uploads the
  next time scrap is open with a connection.
- Uploads go oldest first and one at a time; with no network the rest wait for the next try.
  What happens to a capture depends on the answer. A network error, a `5xx` answer, `408` and
  `429` are retried by themselves with the backoff above. Any other `4xx` answer is permanent: a
  capture the server refuses (for example over the upload limit, `413`) is marked **failed**
  with the server's reason (*refused:* or *too large:*), and stays on the phone with **Retry**
  and **Discard** (which asks first, then deletes it and its photos from the phone). A failed
  capture is not tried again until you tap **Retry** or the header badge. A multi-photo capture
  refused as too large offers **Split and retry** instead of Retry: one capture per photo, the
  text on the first, the tags and any kind on every one. Retry, Split and Discard wait for an
  upload already in progress, so a tapped button says *Waiting for upload…* until it is done.
- A page made from a queued capture is dated when the server receives it, not when it was
  written on the phone, so a capture made offline sorts as new when it uploads, and the
  `date:created`, `after:` and `before:` searches use that day. The phone's time is kept only on
  the capture itself (its `created_at` in the API) and, for a capture of photos or files alone, in the
  page's first title (a time such as `2026-10-22 13:04`, in UTC) until you retitle the page or
  Claude titles it from the photo.
- A slow upload may take as long as it needs while it keeps moving (up to 15 minutes); one with
  no progress for a minute is given up and retried later. Once the phone has handed over the whole
  upload, it waits at least two minutes for the answer (longer for big uploads, which may still
  be draining from the phone's network buffer). Network and server errors just wait
  and retry.
- If the phone refuses to store a capture (storage full), the composer stays open with your text
  and photos and says so. A share that cannot be stored goes straight to the server instead (its
  `POST /share`: see [](../reference/api.md)), or, with no connection either, shows a page
  saying it was not saved.
- Two open scrap tabs take turns (Web Locks), so one capture is never uploaded twice at once.

## What scrap stores on the phone

All of it stays in the browser, for scrap's own address, and none of it is sent anywhere:

- **IndexedDB**: the upload queue (photos as they are) and the drafts, which are the composer's,
  a page edit's and a drawing edit's.
- **Local storage**: your recent searches, whether Claude's **Description** and **Text Claude
  read** on a photo are folded, the debug panel's switch (see Troubleshooting the screen layout,
  below) and the server's upload limit, learned from `/healthz` each time the app opens, comes
  back or goes online, so a photo that is too big is caught offline.
- **Cache Storage**: the app's own files only, in a cache named for the build (`scrap-` and the
  build id). A new build makes a new cache and the old ones are deleted when it takes over.
  API answers and files are never cached.

Clearing the site's data for scrap's address in the browser (or iOS evicting it, see iPhone and
iPad, below) deletes anything still queued and every draft. If the browser blocks local storage
(a private tab, say), scrap carries on without it: no recent searches, no remembered folds, no
offline size check. If it refuses to store a capture, the composer says so (see above).

## What works offline

The app's own files are kept on the phone, so it opens without a connection. API answers and
files are never cached, so anything that reads from or writes to the server needs it.

| Works offline | Needs the server |
| --- | --- |
| Opening the app, the capture screen and the badge | Opening any page |
| The composer, with photos and tags, and its drafts | Search results, the Todos screen and the Tags screen |
| Saving a capture (it is queued and uploaded later) | Changing a page's tags or kind, and saving its due date or snooze |
| Sharing into scrap | Ticking a task box on a page |
| The editor (on a page already open) and its drafts, and the search screen's recent searches | Viewing or editing a drawing, and Mermaid diagrams (shown as code) |
| Waiting items: retry, discard, split | Claude's summary and related pages, and the pager and swipes |

Saving an edit of a page also needs the server; the editor keeps what you typed as a draft until
you can. The cached files are replaced when a new scrap is deployed (see Updates, below).

## View, edit, search

### Screens and navigation

- The nav has three tabs, **Capture**, **Todos** and **Search**. **Todos** opens the Todos
  screen on **Now** (see Todos, below); its badge counts the open todos due today or overdue, by your
  phone's day (none: no badge), and is counted again when the app opens or comes back and
  after a tick or an edit. **Search** opens the list screen for everything else: with
  nothing in the search box it lists every page newest first, with a thumbnail of the first
  photo (**Show more** at the end for older ones). The keyboard only comes up when you tap the
  box. There is no separate Recent screen: the empty box is it.
- A page is a step down from a list, so it has no nav: its toolbar is the only bar at the
  bottom. In the top bar, in place of the wordmark, Back names where it goes: **‹ Search**,
  **‹ Todos** or **‹ Capture**, the list you opened the page from (**Tags** has it too, with its
  title, going to Search). It goes straight back to that list as you left it, even after you
  have stepped through its pages or followed links from page to page; the phone's or the
  browser's own Back still goes back one step at a time. A page opened from a link or a share
  has no list behind it, so Back goes up instead: to the Todos screen for a todo, to Capture
  for any other page.
- On a wide screen (a laptop, a tablet on its side) the app is one centred column about 720 px
  wide. On a computer, a page's buttons (Mark done, Edit, Share, Delete) are a row
  under its title and details rather than a bar at the bottom of the window.
- Every row, a page's tags, its `[[links]]` and the pager's ∧ ∨ are ordinary links with their own
  address, so you can open one in a new tab: on a phone, long-press it and choose *Open in new
  tab* (in the installed app, Chrome may offer to open it in Chrome instead); on a computer,
  Ctrl-click (Cmd-click on a Mac) or middle-click it. A page opened that way has no pager: it
  wasn't opened from a list. A plain tap opens it in place.
- A row in a list shows a page's kind by its icon (a checklist for a todo, a bookmark for
  Later); a page says it in a chip at the start of its line under the title, with its status
  if it has one: *Todo · open*, *Later · done*, *Note*.
- A page opened from the list or a search shows where it is in that list at the right of the
  top bar, as a mail app does: *3 of 23* with **∧** (previous) and **∨** (next). Swipe left for
  the next one and right for the previous one, or use the arrows (or the arrow keys). The page
  follows your finger and slides away to the next one; a short drag settles back, and at the
  first or last it only gives a little and says so. Back returns to the list. Swipes start
  away from the screen's edges (the phone's own Back gesture lives there) and are ignored on
  text that scrolls sideways, while zoomed in or while selecting text. The pager needs the
  server's list, so a page has none when it is opened offline from a list (and a page cannot be
  opened offline in any case).
- Swipe a row of the list, the capture screen's list or search results: to the **right** to
  edit it (the page opens in its editor), to the **left** to delete it (with **Undo** for a few
  seconds). The row follows your finger with *Edit* or *Delete* showing behind it; past a third
  of the way (or with a quick flick) the icon grows, and letting go does it. Let go sooner and
  it slides back. The page itself has the same Edit and Delete.
- An address scrap doesn't know shows *Not found*.
- On a computer the keyboard does these:
  - **Enter** in the search box opens the first result and keeps the search under Recent.
  - **Left** and **Right** arrows go to the previous or next page in the pager, and to the
    previous or next photo in the photo viewer. The pager's arrows do nothing while you are
    typing in a box, editing, or have a photo or drawing open, or with Ctrl, Alt, Shift or Cmd
    held.
  - **Escape** closes the photo viewer (its Share menu first), the drawing viewer (not while you
    are editing the drawing), and a page's **Tags** and **Due** forms.
  - **Ctrl+Enter** (**Cmd+Enter** on a Mac) saves in the editor and the composer.

### Search

- **Search** searches titles, tags, summaries and text as you type (each word as the start of a
  word: `vsc` finds `vscode`); a title or tag match ranks first. Each result shows a snippet of
  the matching text, unless it only says the title again. Search needs the server: offline, the
  screen says so.
- Tap the empty search box for **Recent**: your last ten searches, newest first, filters and
  all (`kind:todo tag:home`). Tap one to run it again, its **✕** to forget it, or **Clear all**.
  A search is kept once it is run: Enter, opening a result, or leaving it a few seconds with
  results; not as you type. They are kept on this phone only, never sent to scrap; in a
  private tab, or with site storage blocked, there are none and search works as before.
- Under the search box (and any filters on), a row of kinds, always shown, each an icon over
  its word: **All**, **Notes**, **Todos**, **Later**, **Boards**, **Docs**. One tap shows only
  that kind (it writes `kind:later` into the query), a second tap on it (or **All**) shows
  every kind again. A kind alone still lists newest first. **Todos** works as the others do: it
  narrows the list to todos (`kind:todo`) in place; the Todos tab is the Todos screen.
- Whenever anything is chosen or typed, the search box has a **✕** at its end: one tap goes
  back to every page, newest first (the keyboard stays down).
- **Filters** is the slider button at the end of the search box; with filters on, it shows how
  many. Each filter that is on is a chip with a ✕ in a row under the box (*#home*, *past
  month*, *A–Z*): tap it to take that filter out. So nothing chosen is hidden. How many pages
  were found leads that row (with no filters on, it is a short line over the list).
- Tap **Filters** to open its panel in place, under the box, and tap it again to fold it (it
  stays as you left it for the next search). Its rows: **Tags** (type in its box for the tags
  in use that match, or with nothing typed tap one of the results' top tags, with their counts:
  only tags that narrow what was found are offered; **All tags** opens the tags screen),
  **Order** (**Best match** or **Last edited**, **Newest**, **Oldest**, **A–Z**, and for todos
  **Due soonest** and **Priority**) and **When** (**1w**, **1m**, **1y**, **Dates…** with a
  From and a To, and **By created date** once a range is on). Each row scrolls sideways. Each
  tap changes the search at once, and the list under it follows; a chosen one is shown pressed
  and a second tap takes it off. **Clear filters** takes every filter off and keeps the words.
  For todos due today, overdue or soon, use the Todos screen, or type `due:` in the box.
- The list shows 100 pages at first and **Show more** adds 100 each time. The newest-first list
  (empty box, or a kind alone) stops at 500 pages and a search at 1000 results, then there is no
  more button. That is how far the screen goes, not a limit on what is stored: to reach further,
  narrow the query with filters or a date (`after:`, `before:`), or turn the order round
  (`-sort:created` lists the oldest first).
- The query and its filters are in the address (`/search?q=...`), so a reload keeps them, and
  Back from a page, or deleting it, comes back to the same list, scrolled where it was. Old
  `/recent` links open this screen (`/recent?kind=todo` the Todos screen).

#### Search syntax

The chips and panels only write the query, which you can also type:

- Words match as the start of a word. `-word` or `!word` leaves out pages with the word, and
  `"a phrase"` matches those words together, in order. A `-` or `!` in front of any filter below
  leaves out the pages it matches. A query may have at most 64 terms and 64 filters (more is
  refused, not cut short), and a word with no letter or digit in it (`&`, `?`) is ignored.
- `kind:todo` (or `kind:later`, also `kind:read`, `kind:board`, `kind:doc`...).
- `tag:tech` (also `tech/epics`; `tag:epics` finds `tech/epics` too).
- `is:STATUS` for a todo's or Later page's status: `is:open`, `is:in_progress`, `is:done`,
  `is:cancelled`. `is:snoozed` finds open todos snoozed till later. `is:claude` finds pages
  Claude wrote over MCP, which show a *Written by Claude* badge, and `is:claude-edited` pages
  whose text Claude changed over MCP. `is:personal` and `is:work`
  (a page not marked personal) use the page's `personal` flag, which an import sets (see
  [](import-a-vault.md)); the app cannot set it.
- `has:image` (pages with an image file) and `has:drawing` (pages with a drawing made from a
  photo). `image:photo` or `image:whiteboard` (what Claude took the photo for).
- A todo's `due:today`, `due:<today` (overdue), `due:>today`, `due:2026-11-01` (also `<=`,
  `>=`), `due:none`, and `priority:high` (`medium`, `low`, `none`).
- `after:1w` or `before:2026-03-01` (last edited; dates are UTC days, both ends included; a time
  ago is `Nd`, `Nw`, `Nm` or `Ny` with N up to 100; add `date:created` for when it was made).
- `sort:title` (A to Z; also `sort:created`, newest first, `sort:updated`, and a todo's
  `sort:due`, soonest first, and `sort:priority`, high first; `-sort:` turns one round:
  `-sort:created` is oldest first). The Filters panel's **Order** writes the commonest `sort:`
  for you, and works with nothing typed too.

Filters alone list their pages, newest first. [](../reference/api.md) has the full grammar.

How matching works:

- Words are stemmed and accents are folded: `running` finds `run`, `runs` and `running`, and
  `cafe` finds `café`. The stemming is English; `ß` is not folded to `ss`.
- Punctuation splits words, and so does `_`. `e-mail` is searched as `e` and `mail`, so `email`
  does not find it, and `don't` is `don` and `t`.
- A phrase in quotes matches whole words next to each other: `"hello wor"` does not find
  `hello world`, as `hello wor` does.
- Filter names and values are not case-sensitive: `Kind:Todo` works.
- `date:` takes only `created`, which makes `after:` and `before:` use the creation date; any
  other `date:` value is ignored.
- A value scrap doesn't know does not give an error. An unknown `kind:`, `is:`, `has:` or
  `image:` value, or a `due:`, `after:` or `before:` that is not a date or a time ago, finds
  nothing (after a `-`, it leaves out nothing).

### Tags

- A page shows its **tags** in one line under its title, most used first (swipe it for more):
  tap one to search for it. A tag Claude added is marked as such. **Tags** (or **Add tags**),
  first in that line, edits them in place: tap a tag's ✕ to take it off, type one in the box and
  press Enter or type a comma to add it, or tap one of the tags offered in a row under the box
  (the six most used, or as you type, the tags in use that match: a tap adds it in place of what
  you typed), then **Save**; what is still in the box when you save counts too. Tags are kept
  as the importer keeps them: lower case, without a leading `#`, at most 64 characters each and
  64 per page (the box says when one is too long). Tag editing needs the server.
- **Edit** (also a list row swiped right) has the same tags box, in its **Tags** line under the
  title, and saves them with the text; the composer has it too, for a new page. Changing tags is
  not a new revision and does not move the page up the list.
- **All tags** (in the Filters panel, under Tags) lists every tag with how many pages have it,
  as a tree (open a parent with its arrow), A to Z or most used first, with a box to filter it.
  The sort choice is kept in the address, so a link to `/tags?sort=n` opens it most used first.

### Todos

- Todos and Later pages carry a status (open, in progress, done or cancelled). The page's
  toolbar starts with **Mark done** (the filled button) while it is open or in progress, or
  **Reopen** once it is done or cancelled, then **Edit**, **Share** and **Delete**. In the list, the capture screen's list and search results, their
  rows have a tick box on the right: tap it (or Tab to it and press Space) to tick it off, or to
  open it again; the row stays where it is and gets a *done* chip (an open row has no chip). A
  cancelled one looks closed: its title struck through and greyed, a dash in its box, a
  *cancelled* chip; its tick box marks it done. Ticking
  it or changing a kind doesn't move the page up the list. In the app a todo only moves between
  open and done: **in progress** and **cancelled** are set through the API (a page's `status`
  field: [](../reference/api.md)) or by Claude over MCP ([](../reference/mcp.md)), and the app
  shows them.
- A todo may have a **due date** and a **priority** (high, medium or low). Its page shows them
  in a line under its tags (*high · due 3 Nov*, or **Add due date**): tap it to pick a date,
  or set one in a tap with **Today**, **Tomorrow** or **Next week** (**No date** clears it),
  and a priority, then **Save**. **Edit** has the same two under the
  tags while the kind is Todo. A todo's row in a list says them too; one due before today and
  not done says *overdue* in red, until ticked off. Once done or cancelled it keeps its due
  date, greyed. They are a todo's only: a page made a note
  keeps them, hidden, and shows them again if it is made a todo again. Neither is a revision
  nor moves the page up the list. Today is your phone's day on rows and pages, and the server's
  for `due:` searches.
- **Task lists drive a todo.** A note with task boxes (`- [ ]`) becomes a todo when it is saved
  (done, if every box is ticked), unless its kind was chosen: the server files it, and the
  composer and editor don't suggest a kind for boxes (the kind picker still shows **Note**, and
  leaving it so is no choice). To keep such a page a note, **Edit** it and pick **Note**: a kind
  picked by hand is kept. A Later, Board or Doc never changes. Boxes in code (a fenced or
  indented block) don't count. Its row and page say how many are ticked (*2 of 5*), and its
  tick box on rows shows a bar while only some are. Ticking the last box (on the page, or in
  the editor) marks it done. While every box is ticked, unticking one or adding a new unticked
  one opens a done todo again; otherwise a todo marked done by hand stays done. **Mark done**
  ticks no box, and a cancelled todo is left as it is.
- **Snooze** a todo to put it out of the way until a day: on its page, tap the line under its
  tags and pick a **Snooze until** date, or **Tomorrow** or **Next week** (**No snooze** wakes
  it), then **Save**. A snooze later than the todo's due date asks first whether the due date
  moves with it: **Move due date** (to the snooze's day) or **Keep due date**. Until that day it is out of **Now** and **Upcoming** and the Todos
  tab's count (Now's count says how many are snoozed: tap *1 snoozed* for a search of them,
  `kind:todo is:snoozed sort:due`); **All** shows it, marked *snoozed till 3 Nov*, and
  `is:snoozed` finds them (open ones only: a done or cancelled todo's snooze no longer hides
  anything). On its day it comes back by itself.
- The **Todos** screen (`/todos`, the Todos tab) opens on **Now**: the todos not done or
  cancelled, what to do first at the top, in groups: **Overdue** (oldest due date first),
  **Today**, **High priority** (no due date), then **Open** (the rest, by priority, then due
  date, then last edited). Each row is two lines on every list: its title, then its priority and
  due date (no edit date). Done and cancelled todos are
  folded away at the end (**Done**, tap to open; those among the 500 todos last edited). A
  switch at the top, an icon over each word like the search screen's kinds (**Now** a clock),
  picks the list instead: **Upcoming** (a calendar: due from tomorrow to a week away, soonest
  first) or **All** (every open todo and those done ones, last edited first). Each list
  sets its own order: there is no Sort here. The address says which list
  (`/todos?view=upcoming`; switching changes it in place, so Back leaves Todos rather than
  stepping through the lists), so
  Back from a todo and a reload come back to it; the rows tick and swipe as anywhere else.
  To search todos, use **Todos** in the search screen's kind row (`kind:todo`), where `due:`,
  `priority:` and `sort:due` still search and order them.
- **New todo**, the **+** at the right of the top bar on the Todos screen (its accessible name
  is *New todo*), opens the composer on **Todo**; save, and you are back on the list with the
  new todo in it once it has uploaded.
- Opened from the Todos screen, **Mark done** moves on to the next todo in that list (the top
  bar says *3 of 9*) with **Undo** for a few seconds; on the last one it stays, and offers
  **Back to list**. **‹ Todos** in the top bar goes back to the list at any time.
  Opened from anywhere else, Mark done stays on the page.

### The page view

- Page text is shown as Markdown, as GitHub writes it: headings (each level a size smaller,
  all under the page's title), **bold**, *italic*,
  ~~strikethrough~~, lists (nested too), quotes, code (inline and fenced), links and bare
  `https://` addresses (a `www.` address without `https://` stays plain text), tables
  (a `|` inside a cell is written `\|`), task lists (`- [ ]` and `- [x]`, shown as boxes: tap one on the
  page to tick it, or untick it, and that item's line in the text is saved at once, with no
  editor; the same words twice still tick the right one, and a box in code is no box. If the
  page was changed elsewhere meanwhile, it is shown as it is now, and the tap is not saved: tap
  again. Offline, and in **Preview**, the boxes don't tick) and footnotes (`[^1]`); `[[slug]]` or `[[slug|label]]` links to another
  page (in a table cell write `[[slug\|label]]`: a bare `|` starts the next cell). A
  ` ```mermaid ` block is drawn as a [Mermaid](https://mermaid.js.org) diagram (flowcharts,
  sequence diagrams and the rest); offline, or if it has a mistake, it shows as code. A link to
  `#a-heading` scrolls to that heading: write the heading in lower case with hyphens for the
  spaces (`[top](#my-heading)` for `## My Heading`), as a link with a space in it is no link.
  HTML is shown as typed, never run; images show only
  when they are this server's own photos (an image from another site is not fetched: a web
  address shows as a link to it, named by the image's alt text, and anything else as its alt
  text); links open only to the web (`https`, `http`, `mailto`) or to pages here, and any other
  link is left as plain text. A line break stays a line break. A wide table scrolls sideways in
  its own box. On a Later page, a link on a line of its own shows as a card: the site, the
  path in words, and **Open**. The text is always stored as typed, and **Edit** shows it so
  (but for the photo tokens, below).
- **Linking pages.** A page is linked by its slug, the last part of its address: `[[shopping-list]]`
  or `[[shopping-list|the list]]` for `/p/shopping-list`. Only a slug of lower-case letters,
  digits and hyphens is a link, so a title such as `[[Shopping list]]` stays as typed. The slug
  is made when the page is created, from its title (letters and digits without accents, lower
  case, hyphens between words, at most 60 characters; `-2`, `-3` if it is taken), and is never
  changed or reused, not when the page is retitled nor when it is trashed, so links survive
  renames. A title with no letter or digit that can be written in ASCII (all Chinese, or only
  emoji) gets the slug `page`, then `page-2` and so on. A page's backlinks (under **Related**)
  are the pages whose text has exactly `[[slug]]` or `[[slug|`, so a link written `[[slug\|label]]`
  in a table cell shows as a link but is not counted. `![[slug]]` is not an embed here: it shows
  as `!` and a link.
- **Share** on a page asks **Link**, **Text** or **Download**: **Link** sends the page's
  address (such as `https://<your scrap>/p/shopping-list`), which opens the page for anyone who
  can reach your scrap; **Text** sends its title and text, as typed but without the lines that
  only show a photo (no link to scrap in it); **Download** saves it as Markdown, or as a zip of
  the Markdown and its files when it has any (its photos are in the zip and its text points at
  them there). Tap **Share** again, or anywhere else, to close the choice. Where the browser
  can't share, there is no Share and **Download** is in the toolbar in its place. While a
  Share or Download is fetching its file, the button says *Preparing…* and ignores taps. A
  finished Download says *Downloaded* with the file's name and size. A failure says *Download
  failed* or *Share failed* and why (*can't reach the server*, say) for about 8 seconds.
  Closing the phone's share sheet without choosing is no failure and says nothing. Where the
  browser can't share a file, **Photo** says *Sharing files is not supported here*: use
  **Download**. If the part of the app that does it can't be loaded, you get *Can't do that
  offline: reload scrap and try again*.
- A photo capture's photos are part of its page's text, one line each (`![](/api/blobs/...)`),
  in the order taken: edit the text to move or remove them. **Edit** shows each of the page's
  own photos and files as a short token instead, `⟦image 1⟧` or `⟦file 2: scan.pdf⟧`, with a
  chip for it under the text box (a thumbnail and its name): tap a chip to select its token (to
  cut and paste it elsewhere), or its **✕** to take it out. Saving puts back the Markdown each
  token stands for, exactly as it was; a token you delete or change is no photo any more. Claude reading a photo never
  changes the text. The page shows each photo where its line is, as a preview the server makes
  (so iPhone HEIC photos show too), with its file name, a **Download** of the original and
  **Ask Claude**, which sends that photo to Claude; once sent, the photo shows Claude's
  progress (waiting, reading, paused) and then what it read, described and drew. Below the text
  are the files it doesn't show, such as PDFs, as links with a **Download**.
- Tap a photo to view it full screen: it opens fitted to the screen; pinch or double-tap to zoom,
  drag to pan, swipe (or the arrows) for the page's other photos. **Fit**, **100%**,
  **Download** and **Share** are along the bottom and the cross at the top right closes it, as
  does the phone's Back button. **Share** asks **Link** or **Photo**: **Link** sends the
  address of the photo's page; **Photo** sends the photo to another app: the original if it is
  a JPEG, PNG, GIF or WebP of up to 20 MB, otherwise a JPEG of up to 2048 px that the server
  makes (HEIC and other formats, or anything larger). If a big photo takes longer to download
  than the phone allows, a **Photo ready** message offers **Share** again.

### Editing and deleting

- **Edit** changes the title and text in a full-screen editor, like the composer: **Cancel**,
  **Preview** and **Save** stay at its top, clear of the keyboard, and Ctrl+Enter saves. The
  tags and a todo's due date are folded into a line each under the title, as in the composer.
- Writing lists in the composer or editor: Enter on a bullet (`- `), numbered (`1. `) or task
  (`- [ ] `) line starts the next item, and Enter on an empty item ends the list. Just above
  the keyboard, five keys act on the line (or the lines selected): **Task** makes it a task,
  **Bullet** a bullet and **Number** a numbered item (1, 2, 3 in order), each a plain line again
  if they all are already; **Indent** nests it under the item above and **Outdent** moves it
  back out, renumbering numbered items. In a code block only Indent and Outdent work (two
  spaces). On a page, a task list sits as tight as a bulleted one.
- Nothing typed is lost (tags too): the composer and **Edit** keep a draft on the phone as you type
  (photos too), so after the phone's Back button, a reload or a closed app, it comes back: the
  composer's as the draft row on the capture screen (above), an edit as **Edit draft** on its
  page (**Discard it** drops either). Back closes the editor, not the app. **Cancel** asks
  before discarding changes. If the page was changed elsewhere since you opened it, the
  other version is shown under yours: merge what you want into your text and save again (this
  overwrites theirs), or discard yours.
- Every save that changes a page's title or text is kept as a revision, whether you made it in
  the app or Claude over MCP. The app has no screen to browse or restore them. Claude can read
  them with the MCP `revisions` tool (see [](../reference/mcp.md)); to go back to an old text,
  copy it back into the page by hand. A change of tags or kind is kept apart from these.
  **Download** and `scrap export` hold only the current text.
- A page's text holds at most 1 MB (about a million letters). Save says so before sending a
  longer one (counting the photo links a capture adds), and keeps it in the editor (and the composer) for you to shorten or split. A page imported over the limit can still be edited: only its text must stay as it is, or shrink, for the title, kind and tags to save.
- Deleting a photo's line (its token, in the editor) removes the photo from the page. **Save** warns first, naming each
  photo whose line went: *no longer shown on any page*, or *still shown on N other pages*. This
  doesn't delete the stored file. **Cancel** goes back to the editor with your text as it was (undo brings the
  line back); **OK** saves. The file and what Claude made of it are kept while anything still
  uses it; `scrap gc` (nightly on a single-server install) deletes files nothing uses.
- **Delete** moves the page to the trash, with **Undo** for a few seconds, and goes back to the
  list or search it was opened from (else to every page, newest first). The app has no trash
  screen: once the Undo has gone, a page can be brought back with
  `POST /api/pages/{id}/undelete` (see [](../reference/api.md)).

## What Claude made of a photo

Claude reads photos only with ingest on. It is **off by default**: set `SCRAP_INGEST=on` and
give scrap an `ANTHROPIC_API_KEY` (the Helm chart's `ingest.enabled`, with an existing Secret
holding the key) as in [](../explanations/ingest.md) and the deploy guides.
Without ingest photos are still stored and queued, and each shows *Waiting: Claude ingest is off*.

With Claude ingest on, each photo on a page has, under it:

- Its state: *Waiting for Claude* (or *Waiting: Claude ingest is off*), *Claude is reading it…*,
  *Read by Claude*, *Failed* with the reason and **Retry**, or *Paused* with the reason and **Resume**
  (nothing is lost while paused). The page checks again every 10 seconds while a photo waits.
  **Reprocess**, a quiet text button at the end of the *Read by Claude* line, sends it to
  Claude again; if you have edited its drawing, it asks first:
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
- Excalidraw is loaded only when a drawing is first shown (about 430 kB compressed over the
  network; then cached by the browser), never for capture or the search screen. Mermaid is
  loaded the same way, for a page with a diagram. `npm --prefix web run size` prints the
  current figures. Excalidraw's fonts are served by scrap itself, never
  from a CDN; Chinese, Japanese and Korean handwriting falls back to a system font.

## What Claude makes of a note or link

With ingest on and `SCRAP_ENRICH` not set to `off` (see [](../explanations/ingest.md)), a text
or link page gets a **Claude** panel on its page view, under its text. Enrichment is on by
default once `SCRAP_INGEST=on`; without ingest the panel is not shown unless the page already
has a summary or related pages. The panel has:

- Its state, as a photo's is said: *Read by Claude* once it has read the page, with
  **Reprocess** at the end of the line to have it read the page again (a saved link is fetched
  again); while it works, *Waiting for Claude* (or *Waiting: Claude is off*) or *Claude is
  reading it…*; *Paused* with the reason and **Resume** (the queue is shared with photos;
  nothing is lost while paused); *Claude couldn't read it* with the reason, and **Retry**.
- A line saying what Claude did: *Claude wrote the summary, added the dashed tags and found
  the related pages* (its tags are marked with a dashed outline in the tag line). Before Claude
  has read the page, the line says what it would do instead, with **Ask Claude to read it**.
- Claude's one-line summary of the page, which search also looks in.
- **Related**: pages Claude picked, merged with the pages that link here (marked *· links
  here*).

Reading a page needs the server, like opening it; the page checks again while Claude has it
queued or is reading it.

## Licences of the Markdown libraries

Page text is rendered by [markdown-it](https://github.com/markdown-it/markdown-it) and its
[footnote plugin](https://github.com/markdown-it/markdown-it-footnote) (MIT), and diagrams by
[Mermaid](https://github.com/mermaid-js/mermaid) (MIT), all bundled with scrap and served by
it, never from a CDN.

## Licences of the drawing fonts

The drawing viewer is [Excalidraw](https://github.com/excalidraw/excalidraw) (MIT). scrap serves
the drawing fonts that come with it: Excalifont, Virgil, Nunito, Lilita One, Cascadia Code and
Liberation Sans under the SIL Open Font License 1.1, and Comic Shanns under the MIT licence;
Excalidraw's interface font, Assistant, is OFL 1.1 too. The CJK font (Xiaolai, 14 MB) is left
out. The font files are served as they come from Excalidraw's package, without licence texts
beside them; the licences are in the fonts' own projects (the OFL is at
<https://openfontlicense.org>).

## Troubleshooting the screen layout

Tapping the build id at the bottom of the search screen five times turns on a small debug panel of
viewport numbers (and five more taps turn it off). It helps to report how a phone's keyboard
resizes the page.

## Updates

The app's files are cached on the phone so it opens instantly and offline, the composer and
editor included; API answers and files are never cached (see What works offline, above).
Some parts load only when first used and are not cached ahead: the Todos and Tags screens, a
page's pager and list swipes, Claude's summary and related pages, what Claude made of a photo,
Mermaid and the drawing viewer. After a new scrap is deployed, the app shows **Update available,
Reload**. Until you tap it the old version keeps running; it is also replaced the next time the
app is opened after being closed. The app looks for a new build each time it comes to the front,
not only when it starts. The build id at the bottom of the search screen (`scrap-` and the
build) says which build a phone is running, so after a deploy you can tell whether it has
updated.

## iPhone and iPad

Safari can add scrap to the home screen and capture, view, search and the offline queue work, with
these limits:

- **No share target**: scrap does not appear in the iOS share sheet. A Shortcut that posts to
  `POST /api/captures` (see [](../reference/api.md)) can stand in.
- iOS may evict a home-screen app's storage after weeks of non-use, which would drop anything
  still queued; open it once a connection is back.
- The app follows the iPhone's text size (**Text Size** in Settings, and **Larger Text** in
  Accessibility), keeping its own font and line spacing, and never goes below its
  usual 17 px. At the largest sizes the kind rows wrap rather than clip and the nav grows with
  its labels; a page's toolbar may wrap **Delete** onto a second row.

## Build it (developers)

The PWA's source is in `web/` (TypeScript, Vite, no UI framework; the drawing viewer in
`web/src/board/` uses Excalidraw and React, in a chunk of its own). The container image builds
it; for `scrap serve` from a checkout, build it once with Node 22:

```sh
npm --prefix web ci
npm --prefix web run build   # writes src/scrap/static/, which scrap serve picks up
```

Without it `scrap serve` still serves the API, and `/` says how to build the app. To try a build
from another folder without restarting, point `SCRAP_WEB_DIR` at it. For working on
the app, run `scrap serve` (it listens on 127.0.0.1:8000 by default) and
`npm --prefix web run dev` (Vite proxies `/api` and `/share` to port 8000).

Checks: `npm --prefix web run check` (Biome, TypeScript), `npm --prefix web test` (unit tests),
`npm --prefix web run size` (after a build: the app shell stays within its 16 kB gzipped budget and
never loads Excalidraw). `npm --prefix web run e2e` runs Playwright against a real
`uv run scrap serve` on a throwaway data folder, so it needs `uv`, a built PWA and Playwright's
browser, installed once with `npx --prefix web playwright install chromium`.
`npm --prefix web run icons` regenerates the app's icons.
