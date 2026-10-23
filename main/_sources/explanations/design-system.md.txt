# The PWA's design system

The phone app is a tool you reach for one-handed, often in a hurry: open, capture, gone. The
design follows from that, and from keeping the app tiny: the shell (capture, lists, pages,
search) uses no UI framework, icon library or web font, and its JavaScript is held under 16 kB
gzipped (`npm run size`, `web/scripts/size.mjs`). The one exception is the drawing viewer for a
photo's drawing: a separate chunk, fetched only when a drawing is shown, built on React and
Excalidraw with Excalidraw's own fonts (served by scrap from `/excalidraw/fonts/`), and outside
that budget. Everything visual is defined once, in `web/src/tokens.css`; the components in
`web/src/style.css` and `web/src/excalidraw.css` (the photo panel and the drawing viewer) use
nothing else. This page is the portable description, for carrying the design into another tool
and back.

## Principles

- **Paper and ink, one colour.** Warm off-white paper and warm black ink in daylight, a warm
  near-black and cream at night, and a single amber (a sticky note: scrap's mark). Amber means
  "the thing to press" or "this one is selected"; red means only "destructive" or "failed".
  No blue-greys, no second accent.
- **One hero per screen.** Composer and editor: Save, the one amber fill. Todos: no hero (New
  todo is a quiet + in the top bar). Capture: no hero; its
  three actions (Camera, Gallery, Note) are equal tiles, since none is more likely than the
  others. Page: a todo's or a Later's **Mark done**, the toolbar's one fill; a page with no
  status has none. Everything else steps down: secondary (outlined surface), then
  ghost (text only).
- **Under the thumb.** Capture actions and the nav sit at the bottom; a page has no nav, so
  its toolbar is the only bottom bar. Cancel, Preview and Save sit in the editor's top bar
  because the keyboard owns the bottom.
- **Drill down, then Back.** A page and Tags are reached from somewhere. Android and browsers
  have a Back of their own, so the top bar stays as it is; an iPhone's home-screen app has none,
  so there (`navigator.standalone`) the top bar swaps the wordmark for a back arrow (Tags with
  its title), which steps back in the app, or, opened cold
  from a link, goes up to a parent (Todos for a todo, Capture for any other page, Search for
  Tags).
- **Icons with words.** Icons help find a control; the word says what it does. Icon-only
  buttons (close, previous/next photo, remove a photo) carry an `aria-label`.
- **Calm states.** Empty, offline and error states are an icon, one plain sentence and at most
  one action. On the capture screen a problem is a quiet inline line, never a whole screen;
  offline there is the badge, the waiting rows and one line, with no card, Retry or toast.
- **Say it once.** A row shows its kind by its icon alone; a chip only for a status that ends
  it (done, cancelled). A page says its kind and status once, in its meta line's chip.
- **Dark is designed, not inverted.** Surfaces get lighter as they come forward; amber is a step
  lighter; toasts stay dark slabs in both themes.
- **Every gesture has a button.** Swipes are shortcuts, never the only way: a row's Edit and
  Delete are also on its page (and a row's tick is a button of its own, with Mark done and
  Reopen on the page too), the page's swipe is also its ‹ › pager and the arrow keys.
  Gestures start away from the screen's edges, which belong to the phone's Back gesture.
- **Motion confirms, never decorates.** 90-260 ms, eased out; none under reduced motion. The
  two looping indicators (busy, loading image) are the only motion that runs longer.

## Tokens

Light / dark values, held to WCAG AA (4.5:1 for text, 3:1 for control edges) twice:
`web/tests/contrast.test.ts` reads `tokens.css` and checks the listed text/background pairs,
every `style.css` rule that sets both a text colour and a background from tokens, and white
text on `--overlay` over a white photo; and an end-to-end sweep (the `lowContrast` helper in
`web/e2e/contrast.ts`, run by `web/e2e/view.spec.ts` on each screen in both themes and by
several other e2e specs) computes the real colour of every visible piece of text and of what
lies behind it.

The theme follows the system unless Settings (the top bar's cog) says otherwise
([](decisions/0024-settings-pane-theme-overrides.md)): Light or Dark sets `data-theme` on
`<html>`, which `tokens.css` reads in place of the media query (`web/src/theme.ts`). Drawings
have a theme of their own, Light by default.

The browser's `theme-color` follows the colour scheme: two `<meta name="theme-color">` tags in
`web/index.html`, one per scheme, with the `--bg` values below (`theme.ts` sets both to the
chosen one when the theme is forced). The PWA manifest
(`web/public/manifest.webmanifest`) does not: its `theme_color` and `background_color` are a
fixed dark `#161411`.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--bg` | `#f6f3ec` | `#161411` | the page; theme-color |
| `--surface` | `#fffdf9` | `#211e1a` | cards, list groups, fields |
| `--sunk` | `#ece7dd` | `#2b2722` | wells: tiles, segmented track, placeholders, pressed |
| `--ink` | `#1e1b16` | `#f2ece1` | text |
| `--ink-2` | `#5c564c` | `#b8b0a2` | secondary text: dates, hints |
| `--ink-3` | `#736c61` | `#958d80` | placeholders, captions |
| `--line` | `#e2dccf` | `#322d27` | hairlines (decorative) |
| `--line-strong` | `#8f8778` | `#706858` | field and control edges |
| `--accent` | `#eba13a` | `#f0ac4b` | primary fills, selection, badge dot |
| `--on-accent` | `#1e1b16` | `#1e1b16` | text on accent |
| `--accent-ink` | `#8a4f00` | `#f3b65c` | accent as text: links, focus ring, active icon |
| `--accent-soft` | `#f8e6c6` | `#3a2c17` | chips, highlights, active nav pill, badge |
| `--danger` | `#b42318` | `#f29086` | destructive, failed (text) |
| `--danger-soft` | `#fbe4df` | `#3b201c` | failed badge, conflict banner |
| `--toast` / `--on-toast` | `#2a2620` / `#f6f1e7` | `#3a352d` / `#f2ece1` | toasts |
| `--toast-action` | `#f3b65c` | `#f3b65c` | a toast's action |
| `--viewer` | `#000000` | `#000000` | the photo viewer's backdrop |
| `--on-overlay` | `#ffffff` | `#ffffff` | text and icons over photos |
| `--overlay` | `rgb(0 0 0 / 65%)` | same | pills, scrims and buttons over photos (white on it is over 4.5:1 even on a white photo) |

Presses, edges and washes that need a translucent tint mix a token with `transparent`
(`color-mix(in srgb, var(--ink) 14%, transparent)`) rather than writing a new colour.

Type: the system UI face (Roboto on Android; `--font`: `system-ui, -apple-system, "Segoe UI",
Roboto, sans-serif`, and `--mono` for code: `ui-monospace, "SF Mono", Menlo, Consolas,
monospace`); a 17 px root, so a `rem` is 17 px and `--t-xs` (0.75rem) is 12.75 px. On iPhone the root follows the
phone's text size, Larger Text too (`font: -apple-system-body`, applied only where
`-webkit-touch-callout` exists, so iOS and not a Mac), with scrap's own family and line height
set again after it; a small check in `main.ts` keeps it from going under 17 px (the smaller
settings), measured again whenever the app comes back. `--t-xs` 0.75rem (labels under icons,
chips), `--t-sm` 0.875rem (meta, small buttons), `--t-md` 1rem (body, list titles), `--t-lg`
1.1875rem (wordmark, field titles, a Markdown `h2`), `--t-xl` 1.5rem (page title). Markdown
headings step down a size a level, all under the page title: `h1` 1.3125rem, `h2` `--t-lg`,
`h3` 1.0625rem semibold, `h4`-`h6` `--t-md`. Line height
`--lh` 1.5, `--lh-tight` 1.25 for titles, 1.6 for page text. Weights 500 (controls), 600 (titles, labels), 700
(page title, active nav).

Space: a 4 px grid, `--s-1`..`--s-7` = 4, 8, 12, 16, 24, 32, 48. Screen gutter 16.
Radius: `--r-sm` 8 (thumbnails, code), `--r-md` 12 (buttons, fields, toasts), `--r-lg` 16
(cards, lists, photos), `--r-pill` (badge, search field, nav indicator).
Size: `--tap` 48 (the touch target, extended with an invisible `::after` where the drawn control
is smaller; the exceptions are listed under "What we don't do"), `--bar-h` 56, `--nav-h` 64 (`max(64px, 1.125rem + 44px)`: taller when its labels
are, at a large text size). Elevation: `--shadow` (selected segment), `--shadow-2`
(capture cluster, toasts).
Motion: `--d-1` 90 ms (press), `--d-2` 180 ms (view enter, toast), `--d-3` 260 ms (editor sheet,
viewer); `--ease` `cubic-bezier(0.2, 0.8, 0.2, 1)`. Under `prefers-reduced-motion` all three are
0, and the two looping indicators stop: the placeholder shimmer (1.2 s, alternating) and the busy
icon's pulse (0.8 s, see Busy under States). Those two are not on the `--d-*` scale: they repeat
only while the work or the image is in progress.

## Components

| Component | Class / element | Notes |
| --- | --- | --- |
| Button, secondary | `button`, `.button` | surface, hairline edge, 48 high, icon 20 + label; presses scale to 0.97 on `--sunk` |
| Button, primary | `.primary` | amber fill, ink label; one per screen (Save) |
| Button, ghost | `.ghost`, `button.link` | no fill (Cancel, Discard it, the pager's ‹ ›) |
| Button, danger | `.danger` | red label, never filled |
| Tile | `.tile` | icon over a short label on `--sunk`, 72 high; the capture actions Camera, Gallery and Note, three equal columns |
| Toolbar | `.tools` | icon-over-label tiles sharing the width by their labels (`flex: 1 1 auto`), so no word is cut; page actions (sticky at the bottom, where the nav would be: a page has none; over the page text: `z-index` 2), viewer tools. A page's order: **Mark done** (a todo or a Later open or in progress: `.primary`, `--accent` fill, `--on-accent` label at `--t-sm`, `--r-md` corners, wider at `flex: 1.6 1 auto`, the check icon), or **Reopen** in its place once done or cancelled (plain, the retry icon: a cancelled one looks closed, so it offers only Reopen), **Edit** (or Edit draft), **Share**, **Delete** (danger); Download is in Share's menu, or in Share's place where the browser can't share. Four fit whole at 360 px |
| Segmented control | `.chips` (radio group) | the editor's kind (`.kinds`: Note, Todo, Later, Board, Doc: short labels so all five fit one row from 320 px, with the full names Whiteboard and Document as the radios' accessible names and titles), the search screen's kind row (`.kindrow`: All, Notes, Todos, Later, Boards, Docs, each its kind's 18 px icon over its word, All a grid of four tiles, so all six fit one row from 320 px; always shown, under the filters on; one tap sets or clears `kind:`, Todos included: it filters in place like the others), the Todos screen's **Now** (a clock), **Upcoming** (the due calendar) and **All** (the grid), drawn as the kind row, and the Tags screen's order (`.filters`); selected = raised surface, amber icon. The editor's kind picker draws each kind's icon over its word too (`--t-xs`), as the kind rows do, so every kind bar shows its icons at every width; at a large text size the kind rows and the picker wrap rather than clip |
| Top bar | `header` | wordmark with the scrap mark; at the right, the queue badge, then **Settings** (`#settings`, a ghost cog, "Settings", on every screen: it opens a sheet like the editor's with two radio groups, App theme System / Light / Dark and Drawings theme Light / Dark / Same as app; Done, Escape or Back close it). On a page and on Tags in an iPhone's home-screen app (`navigator.standalone`; elsewhere the phone's or browser's Back serves), a back arrow (`#back`, a 48 px ghost button, "Back") in the wordmark's place, and on Tags its title (`#where`, `--t-lg`) beside it: it steps back to the app's entry before this one (`go()` marks the entries it pushes), else goes up to a parent: Todos for a todo, Capture for any other page, Search for Tags. On the Todos screen, **New todo** (`#new`, a ghost plus, "New todo") at the right end, the badge beside it when up: it opens the composer with Todo chosen (kept even if the text is a link), which closes back onto the list; the list fetches again as the upload queue changes, so the new todo joins it |
| Badge | `.badge`, `.badge.failed` | pill with a status dot: amber waiting, red failed |
| Bottom nav | `nav` | three tabs, Capture, Todos, Search: icon over label; active item gets an amber-soft pill and ink label (`aria-current`). Not on a page (`body.paged`): its toolbar is the bottom bar. It grows with its labels at a large text size (`--nav-h`) |
| Nav count | `nav .due-n` | the Todos tab's open todos due today or overdue: a 20 px `--accent` pill with `--on-accent` digits on the icon's corner, ringed in `--bg`; hidden at 0; the tab's accessible name says it ("Todos, 3 due"). One count request when the app opens or comes back and after a change, never polled |
| List group | `.list` | rows in one rounded card; `.pending` is dashed (still on the phone) |
| List row | `.list li` | 48 thumbnail or kind icon (the icon says the kind), title, date and, done or cancelled only, a status chip (`em`, classed by its word); a search hit's snippet, unless it only repeats the title (the same whole words in order, punctuation and case aside: `echoes()` in `snippet.ts`); a cancelled row (`li.cancelled`) has its title struck through in `--ink-2`; actions under it (`.rowbar`: whole words, the bar wraps to a second line rather than breaking a label such as Split and retry); a focused row draws its ring inside the card |
| Swipe row | `.list li.swipe`, `.row-under` | follows the finger; behind it Edit on `--accent-soft` (right) or Delete on `--danger-soft` (left); past the threshold the icon grows (Edit turns `--accent`) and letting go does it |
| Fold | `.claude-text` (`details`) | hairline above, a chevron before the heading: right folded, down open |
| Pager | `.pager` | a page opened from a list: ‹ "3 of 23 · Latest" ›, its middle a plain label (`.pager .at`, `--ink-2`) saying which list: "Latest" (Capture's list, and the search screen's newest-first list), the kind row's name when one kind is chosen alone ("Notes", "Todos", "Later", "Boards", "Docs"), "Search results", "Todos · Now", "Todos · Upcoming", "Todos · All" and "Todos · Done" (the Todos screen's folded done and cancelled): the top bar's Back goes back to the list; the page follows a sideways swipe and slides off to the next. From the Todos screen, Mark done steps on to the next todo with a toast "Done: <title>. Next todo, 3 of 9" and **Undo** (6 s); on the last, "Done: that was the last in the list" and **Back to list** |
| Status chip | `.list em` | amber-soft pill, on a row only for a status that ends it: "done", "cancelled" (an open todo or Later has none: its icon says the kind) |
| Kind chip | `.meta .state` | a page's kind, and its status if it has one, leading its meta line: "Todo · open", "Todo · in progress", "Later · done", "Note" (`pageChip()` in `status.ts`); an amber-soft pill |
| Due line | `.list .due`, `.todoline`, `.todoedit` | a todo's priority and due date in words ("high · due 3 Nov") after its chip, `--ink-2`; overdue (`.late`: due before today, not done or cancelled) says "overdue" in `--danger`, semibold: the word carries it, never colour alone; done or cancelled (`.closed`) keeps its due date in `--ink-3`, said as a date ("due 3 Nov"), never "today" or "overdue". On its page, a pill button under the tags (the calendar icon) opens `.todoedit` in place: a native date input and **No date** (ghost), then on a line of their own (`.soon`, a group "Due soon") **Today**, **Tomorrow** and **Next week** (seven days on, the phone's calendar) as `.facet` chips, the one matching the date set `aria-pressed` on `--accent-soft`, semibold, as in the Filters panel, then a native priority `select`, then Cancel and Save; the pill reads the due line's words when there is any ("high · due 3 Nov"), else "Add due date" on an open todo; a closed todo with none shows no pill (Reopen it first); the editor shows the same while the kind is Todo. The page's form adds, on a line of its own, **Snooze until** (a native date input and **No snooze**, ghost, then **Tomorrow** and **Next week** chips in a group "Snooze for"); a snoozed todo's line ends "· snoozed till 3 Nov" and it is out of Now, Upcoming and the nav count until that day. The due line wraps rather than being cut (when it is due outranks one tidy line); the page's pill is drawn like the Tags pill, 32 px inside a 48 px target |
| Filters button | `.field-search .ffield` | a 48 px slider icon (filter) at the search field's end, `--ink-2`; while the panel is open (`aria-expanded`), `--accent-ink` on `--sunk`. With filters on, their number in an 18 px `--accent` pill with `--on-accent` digits on its corner (`b`, 0.7rem, about 12 px: the one text under 12.75 px, a non-interactive count whose number is also in the button's name); its name says "Filters, 2 on" |
| Filters on | `.refine .fon` | under the search field, led by how many pages were found (`.count`, `--ink-2`), so the count and the chips share one line; then each filter on (not the kind row's kind) as a `.facet.on` chip with a ✕ (`aria-label` "Remove #home"), saying it in words ("#home", "past month", "A–Z", "Written by Claude"), in one row that scrolls sideways to the screen's edges, the last 32 px of the block fading out (a mask on `.refine`, which holds this row and the Filters panel); no filters, no row |
| Filters panel | `.fpanel` | opens in place under the filters on (below), a `--surface` card with a `--line` hairline and `--r-lg` corners. Rows (`.frow`, a group each), a small uppercase `.flabel` in `--ink-2` then `.facet` chips on one line that scrolls sideways (never a wall of chips): **Tags** (`.ftags`: a pill field "Add a tag", then on the next line the tags it offers: with nothing typed, the current results' top tags with their counts (the 12 the search's facets give), or with no search yet the 8 most used top-level tags, then a link-chip **All tags** to the Tags screen; as typed, the results' tags that match (those starting with the typed text first), at most 8, no All tags (the matches come from `search/facets?top=1000`, asked for only then; before any search, from every tag in use); none, a line saying why), **Order** (the default first: Best match with words typed, else Last edited; then Newest, Oldest, Last edited with words typed, A–Z, and for `kind:todo` Due soonest and Priority) and **When** (1w, 1m, 1y, Dates…, and By created date once a range is on; Dates… opens From and To date inputs, applied as picked); a chosen chip `aria-pressed` on `--accent-soft`, semibold (a chip's count, `small`, shares the label's line height so it sits on its baseline rather than raised); then **Clear filters** (`button.link`) while any are on. Each row is scrolled so its chosen chip shows. `refine.ts`, a chunk of its own, kept offline by the service worker |
| Found line | `.found` | with no filters on, over the list, under the kind row: how many pages were found ("104 pages", `--ink-2`, `--t-sm`, a tight line under 20 px); with filters on, the count leads their row instead, so results start 21-39 px higher |
| Todos screen | `.todos` | the segmented control again, as the kind row (**Now**, a clock; **Upcoming**, the due calendar: due from tomorrow to 7 days away; **All**, the grid: each sets its own order, so no Sort), the count in `--ink-2` (on Now, "· 1 snoozed" after it, a link to the search `kind:todo is:snoozed sort:due`), then Now's groups under `h2.label` headings ("Overdue · 3", "Today", "High priority", "Open": not "Later", which is a kind), each its own `.list`; rows are two lines on every tab: the title, then the due line (CSS `order`) and a done or cancelled chip; no edit date and no kind icon (every row is a todo, so the room goes to the title). New todo is the top bar's + (above) |
| Done fold | `.donefold` (`details`) | Now's done and cancelled todos, folded at the end: a 48 px summary in `--ink-2` with the chevron of `.claude-text` |
| Row tick | `.list .tick` | a todo's or a Later's row: a 48 px toggle (`aria-pressed`, `aria-label` "Done: title") at its end, beside the row's link rather than in it, so tapping it opens nothing; an empty box in `--ink-2` (the tick icon), ticked in `--accent-ink` when done, a bar across it (`aria-pressed="mixed"`, `--accent-ink`) while only some of the page's task boxes are ticked, its row saying "2 of 5"; a cancelled one has a grey dash in its box, and pressing it marks it done; it slides with the row, and a drag that starts on it swipes the row |
| Claude's panel | `.orig` | under a read photo, its state ("Read by Claude"); **Reprocess**, rarely wanted, is a quiet text button (`button.link`) at that row's end, not a full button |
| Link card | `.md > .linkcard` | on a Later page, a paragraph that is only a link to the web (`cards()` in `render.ts`) is drawn as a file card: its site (no `www.`) over its path, tidied to words ("wiki / Integrated information theory": no escapes, trailing slash or `.html`; or the link's own text, if it was given one), each cut to one line, and **Open** (the open icon) with a button's look at its end. The whole card is the link, one tab stop |
| Draft row | `.capture .draft` | the composer's kept draft (left by Back), one quiet line on `--sunk` over Capture's tiles, the whole width, `--t-sm`: the kind's icon (a photo's for photos), "Draft: " and its first line, cut with …; tap to carry on; a 48 px ✕ ("Discard draft") at its end, with **Undo** in a toast. The tiles always start a fresh capture; beside a kept draft it is saved as typed under a key of its own (`fresh.ts`), and takes the kept one's place, with **Undo**, when left by Back or when found after the app was killed |
| Offline line | `.strip .offline` | Capture offline, in Latest's place: "Offline: showing what's on this phone", `--ink-2`, `--t-sm`; Latest draws itself again when the phone is back online |
| Figure caption | `.orig figcaption`, `.save` | under a page's photo: its file name in `--ink-3` (cut with … when long), then **Download** and **Ask Claude** as `.save` text buttons in `--ink-2`, a 20 px icon, whole words (`flex: none`, `nowrap`: the page text's `overflow-wrap: anywhere` must not break them), 48 high |
| Thumbnail | `.list img`, `.thumbs img`, `.originals img` | fixed size or 4:3 frame reserved before load, shimmering `--sunk` placeholder |
| Photo strip | `.thumbs` | 84 squares, remove button with a 48 target |
| Field | `input`, `textarea` | surface, strong edge, 2 px accent-ink focus ring |
| Search field | `.field-search` | pill with a search icon; on the search screen a ✕ (`.clear`, a 48 px ghost button, "Clear search") at its end while it has text, in place of the browser's own |
| Recent searches | `.recents-top`, `.list.recents` | under the search field while it is empty and focused (gone once it has text, or loses focus): an `h2.label` "Recent" with **Clear all** (`button.link`) at its end, then up to 10 past searches as one `.list` group (`role="group"`, "Recent searches"), newest first: a search icon and the query as typed, start-aligned and cut with … on one line, then a 48 px ghost ✕ ("Remove <query>"). A tap on the list keeps the field focused until the choice is made; a choice runs it and the keyboard goes. No history: no block at all. On this device only (`scrap.searches`, through `kept()` in `api.ts`, the one guard every `localStorage` use goes through: with storage blocked it keeps nothing and never throws) |
| Editor sheet | `.editor` | full screen over the keyboard; top bar Cancel / Preview / Save. Just above the keyboard, one line of five equal keys (`.keys`, on `--bg` under a `--line` hairline, gone in Preview; ghost buttons, an icon drawn in `editor.ts` over a `--t-xs` word; under 300 px the icons alone): **Task** (the line, or each line selected, a task, `- [ ] `, a bullet or number keeping its marker; or plain items again if all are tasks), **Bullet** (`- `, or plain again), **Number** (`1.` `2.` `3.` in order at each indent, on from a number just above; or plain again), **Indent** and **Outdent** (a level in or out: nested at the parent item's text column, 2 spaces under `- `, 3 under `1. `, as CommonMark needs, a numbered item renumbered in its new place; in a code block, 2 spaces, and the other keys do nothing); a tap keeps the keyboard up. In the text, Enter continues a bullet, numbered or task list, GitHub-style, and Enter on an empty item ends it (`listedit.ts`) |
| Embed chips | `.editor > .embeds` | the page editor shows each of the page's own images and files as a short token (`⟦image 1⟧`, `⟦file 2: scan.pdf⟧`; `embeds.ts`), and under the fields, above the keys, a chip each (`.embed`: a thumbnail, or the file icon, and its name, cut with …) in one line that scrolls sideways; a tap on a chip selects its token (to cut and paste it elsewhere), its ✕ ("Remove image 1"; 40 px wide, 48 high) takes the token out, with its line if alone on one. Saved, the tokens become the Markdown they stood for, byte for byte where none was touched; a deleted or mangled token is no embed. Gone in Preview |
| Editor fold | `.fold` (`details`) | in the composer and editor, the rarely changed parts folded to one 48 px line each above the text, so the text stays the hero: **Tags** (the tag icon, "3 · #work #garden…", or "none") and, while the kind is Todo (in the composer, not with photos: they have no kind there), **Due** (the calendar, "24 Oct · high", or "none"); the name in `--ink`, semibold, what it holds in `--ink-2`, cut with …, a chevron at its end (down folded, up open); tapped, the controls open in place under it and nothing takes focus. Two folds read as one group |
| Share menu | `.share-menu` | Share's choice, a popover just above it: **Link**, the content (**Text** on a page, **Photo** in the viewer) and on a page **Download** (a link drawn as the rows are; tapping it closes the menu), ghost rows on `--surface` with `--shadow-2`; a tap elsewhere, Back or Share again closes it. What Share and Download do is a chunk of its own (`sharing.ts`), loaded on the first tap |
| Tag line | `.tags` | a page's tags under its title, `--sunk` pills that each search for their tag, in one line that scrolls, its last 32 px fading out (a mask, as on the Filters on row and `.toptags`); first an outlined pill (tag icon) that edits them: **Tags** (its name "Change tags"), or **Add tags** when the page has none. A tag Claude added (`a.ai`, tooltip "Added by Claude") is drawn dashed in `--line-strong` on `--surface`, so the user's own stand apart |
| Tag editor | `.tagedit`, `.tagform` | the tags as `.facet.on` chips that wrap, each with a ✕ to take it off, then a field, then one row of up to six `.facet` chips with a dashed `--line-strong` edge (offered, where the chosen are filled), one tap each, in a line that scrolls and fades at its end (`.toptags`): with nothing typed, the most used tags not on it yet (a group "Most used tags"); as you type, the tags in use that match, those starting with it first (a group "Matching tags"), and a tap on one replaces what was typed. Our own row, not a native `datalist`, whose menu covers the keyboard on a phone; all from one `/api/tags` answer. On a page, Cancel (ghost) and Save (primary) under it, in place of the tag line; in the composer and editor, inside the Tags fold |
| Toast | `.toast` | dark slab above what is under the thumb, amber text action. "Update available" with **Reload** appears when a new version of the app has installed behind the one running; it has no timeout and stays through navigation until tapped, and Reload swaps it in and reloads the app |
| Banner | `.conflict`, `.restored` | danger-soft with a red edge; accent-soft info line |
| Empty state | `.empty` (`empty()` in ui.ts) | icon in a `--sunk` circle, one plain sentence in `--ink` ("Nothing here.", "No matches", "No todos yet."), and at most one extra: a `small` hint line (Capture's "Nothing captured yet." adds "Photos, notes and links you save show up here.") or one action (**Back to capture** on "Not found: it may have been deleted."; **Retry** under a problem such as "Offline: this needs the server." or "Can't reach the server. Check your connection or VPN."). A view still loading after 150 ms is a plain "Loading…" line (`role="status"`) in the same block, without an icon; a quick answer shows no flash |
| Tags tree | `.tagtree` (`tags.ts`) | the Tags screen: a filter field with the tag icon ("Filter tags"), the order as a segmented control (**A–Z**, **Most used**), then a `.list` of tags as a tree: each row a link to the search for that tag (`#name`, or the full path at the top level) with its page count (`small`) at the end, indented by depth (`--depth` × `--s-5`); a parent has a 48 px ghost chevron (the next icon) that turns down when open (`aria-expanded`, "Show tags under x"); a filter keeps a tag if it or one under it matches and opens the parents of a match. Empty: "No such tag" or "No tags yet" |
| Match highlight | `mark` | the matched words in a search hit's snippet: `--accent-soft` with `--ink` text and a 2 px `--accent` underline drawn inside the box |
| Build line | `.build` | the running build (the service worker's cache name, `scrap-…`) at the foot of the search screen: centred, `--ink-2`, `--t-xs`. Five taps turn the debug panel (`debug.ts`) on or off |
| Written-by badge | `.meta .badge` | on a page that came in over MCP, last in its meta line: "Written by Claude", a link to the search `is:claude`, as a hairline pill in `--ink-2` at `--t-xs`; its tooltip is the page's `origin` field ("Written by Claude over MCP" if none) |
| Draft dot | `.dot` | a 9 px `--accent` dot ringed in `--bg` on the corner of a button's icon: a page's Edit when a draft of it is kept (its word becomes "Edit draft", its name "Edit draft (unsaved)") and, on the button's own corner, the drawing viewer's Edit (no room there for words; on its amber fill the dot is inverted, `--on-accent` ringed in `--accent`) |
| Enrich panel | `.enrich` (`enrich.ts`) | under a text page's text, shown when Claude is on for it or it has a summary or related pages: a `--sunk` card, `--r-md`, `--t-sm`. A row of bold "Claude", its state in `--ink-2` ("Waiting for Claude", "Waiting: Claude is off", "Claude is reading it…"; "Claude couldn't read it: …" in `--danger`) and, while Claude is on, at the row's end a ghost **Ask Claude** (**Ask again** once it has a summary or is done), disabled while waiting or reading; then its summary, then a "Related" heading and up to 8 page links, with "· links here" after those that link to this page |
| Photo panel | `.photo-panel`, `.pair`, `.tabs`, `.drawing-card` (`excalidraw.css`) | under a photo's page: the photo and, if Claude drew one, its drawing, as a `.pair` of two columns from 700 px wide (or landscape from 560 px), else one at a time under **Photo** / **Drawing** `.tabs` (a segmented control like `.chips`: `--sunk` track, the chosen tab raised on `--surface`; 42 px segments in a 48 px track; Drawing chosen to start with). The drawing is a preview (`.drawing-card`: a button on `--surface` with a `--line` edge and `--r-lg` corners, the drawing's own shape, at most 75 % of the screen high, inert to gestures so a drag scrolls the page); a tap opens the viewer. While it renders it says "Loading drawing…"; if it can't, "Can't show the drawing here: tap to open it", or offline "Offline: the drawing needs the server" |
| Drawing viewer | `.drawing-layer`, `.drawing-bar` | the full-screen drawing (`board/viewer.ts`), a `role="dialog"` `aria-modal` sheet over the app (the nav is hidden) that rises in over `--d-3`, on `--bg`. A top bar of text buttons sharing the width by their labels: **Close**, **Fit**, **Photo** (a toggle, `aria-pressed` on `--accent-soft` with an `--accent` edge: the photo beside the drawing in landscape or from 900 px wide, over it in portrait), **More** (a menu: History, Export .excalidraw, Export PNG, Export SVG) and **Edit** (`.primary`); while editing, **Cancel**, **Undo**, **Photo** and **Save** (`.primary`, `aria-busy` while it saves). Under the bar, a live-region `.drawing-notes` (at most 40 % of the height) holds the restored-draft and conflict banners (`.restored`, `.conflict`) and History (`.versions`: a 48 px row per version, **Restore**). The canvas and its tools are Excalidraw's own |
| Photo viewer | `.viewer` | `--viewer`; close top right, count pill top centre, tools on a scrim that fades from clear to `--overlay` |
| Icons | `icons.ts` | 24 px strokes (1.8), currentColor, `aria-hidden` |
| Markdown | `.md` (page text, Preview) | headings a step down a level (see Type), all under the page title; on a Later page, a link alone on a line is a link card (above); code and a table's head on `--sunk`; a table in a `.table` box with `--line` hairlines that scrolls sideways on its own (the page never does); task boxes in `--accent`, in the bullet's place, the list as tight as a bulleted one; each box in a `.taskbox` label with a target `--tap` (48 px) wide and one line high, so no two overlap; each box is named by its item's text (`aria-label`); on a page they tick in place (`tasks.ts`: each box's `data-line` is its item's line in the text, from markdown-it's map), off while offline and in Preview; strikethrough, quotes and footnotes in `--ink-2`; a Mermaid `.diagram` in its dark or neutral theme, following the system's |

## States

| State | How it shows |
| --- | --- |
| Pressed | scale 0.97 over `--d-1` and a `--sunk` fill (primary: 6 % darker; tiles: `--accent-soft`); the browser's tap flash is off |
| Focus (keyboard) | 2 px `--accent-ink` outline, 2 px offset; fields draw it inside their edge |
| Selected | segmented: raised `--surface` with `--shadow` and an amber icon; nav: `--accent-soft` pill, ink label, bold |
| Disabled | 50 % opacity (exempt from contrast, and never the only sign: the label says why) |
| Busy | the label reads "Preparing…" and taps are ignored; the label is never dimmed, so it stays at full contrast. Only the control's icon pulses (opacity down to 0.3 and back, 0.8 s, looping), so the state shows even where labels are hidden; it stops under reduced motion |
| Loading image | the reserved box shimmers between `--sunk` and `--line` until the image loads or fails, then stops |
| Loading view | after 150 ms without an answer, a plain "Loading…" line in place of the last screen (a quick answer shows none; the same page again does not blank) |
| Not found | an empty state with the search icon, "Not found: it may have been deleted." and **Back to capture**; any other failure is the offline icon, its reason and **Retry** |
| Failed | `--danger` text in words, a `--danger-soft` badge; never colour alone |
| Overdue | a todo's due line in `--danger`, semibold, saying "overdue" (AA on `--bg`, `--surface` and `--sunk` in both themes, as `--danger` is checked); back to `--ink-2` once done |

## The Filters panel: in place, not a modal

The refine row kept gaining controls at its left end (Clear, Tags, Sort, the count, then every
filter chosen), pushing what you came for off the screen. Those controls are used now and then,
not on every search, so they moved behind one **Filters** button. For a while it opened a bottom
sheet (a modal `<dialog>`), but a sheet hides the list its choices change, needs its own Back
handling (a history entry of its own, stepped over on Forward) and costs a tap to close after
every few taps. So the filters open in place instead:

- **Filters** is a slider icon at the end of the search field, where the thumb already is; the
  number of filters on rides on it. A tap opens or folds the panel (`aria-expanded`,
  `aria-controls`); it stays open or folded while the app is open, the next search too.
- The panel opens under the search field and the filters on, above the kind row and the
  list, so each tap in it shows its effect at once. A row per kind of choice (Tags, Order,
  When), each one line that scrolls sideways, keeps it short: never a wall of chips. The tags
  it offers are capped at 8 when typing (12 for a search's top tags), with **All tags**, a link
  to the Tags screen, after them while nothing is typed.
- What is on is always in view, panel open or not: a row of chips under the field, each with
  a ✕. The kind row stays under it, always shown.
- A tap changes the query at once, so the panel is never a form to submit and never holds
  state the address doesn't: Back, a reload or a shared link show the same list. A control
  keeps its focus as the panel is drawn again.
- It is `refine.ts`, a chunk of its own loaded with the search screen and kept offline by the
  service worker, so the app shell stays small.

## Layout and breakpoints

- Portrait phones (300 px and up): the default. Under 380 px wide a segmented control drops its
  icons, except the kind rows (search's and the Todos screen's) and the editor's kind picker,
  which keep theirs over the word.
- A wide window (760 px and up: a laptop, a tablet on its side): one centred column of 720 px
  (the top bar, the screen, the nav and the editor), the background still to the edges.
- Larger text (iPhone's Larger Text at 150 % or 200 %): the kind rows and the kind picker wrap
  instead of clipping, the Filters tag box fits, and the nav grows with its labels. Left for
  later at 200 %: the page toolbar wraps Delete to a second row, the editor's top bar is tight,
  its folds push the kind picker off-screen, and Capture's tiles leave about two rows of the list
  in view.
- Short screens (under 500 px high, i.e. landscape or a large text size): top bar and nav 48 px,
  and the page toolbar scrolls with the page instead of sticking. Landscape (also 560 px and
  wider): the nav's label sits beside its icon and the capture tiles are 64 high.
- Very narrow (under 300 px: a small phone at its largest text size): the capture cluster
  scrolls with the list instead of covering it (it is static and moves to the top, `order: -1`,
  so Camera is on the first screen and the list follows), tiles go two by two, labels and list titles
  wrap, list thumbnails shrink to 32, and toolbars show icons only (the words remain their
  accessible names).
- Toasts sit just above whatever is under the thumb (the capture cluster, the page toolbar, the
  viewer's tools or the nav), clear of the newest row and the title; in the editor, just under
  its top bar.
- Text that may be right-to-left (titles, page text, snippets, the editor) has `dir="auto"`,
  and spacing uses logical properties (`margin-inline-*`, `padding-inline-start`).
- A page photo reserves a 4:3 box while it loads, then takes the photo's own shape
  (`aspect-ratio: auto 4 / 3`), at most 75 % of the screen high.

## High contrast

Under `forced-colors: active` the system replaces fills and drops shadows, so the selected
segment and the current nav item get a 2 px `Highlight` outline, and the borderless tiles and
badge get a `ButtonText` edge. In the drawing viewer, the chosen Photo / Drawing tab and a pressed
toggle in its bar get a 3 px `Highlight` outline.

## Icons

Sizes: 20 in buttons, 24 in tiles, the nav and list placeholders, 18 in the
segmented control, 16 on a photo's remove button, 52 (in a circle) in empty states.
Icons: camera, image, note, tag (the Tags pill, the Tags fold, the Tags screen's field and All tags), todo (a checklist: the Todo kind, so a row's kind icon never reads
as a ticked box beside its tick box), tick (check in a square: a row's tick, which hides the
check until done, and the Todos empty state; the nav's Todos tab draws the same box inline), done (a check alone: Mark done, so a box always means a tick you can see), add (a plus: New todo), due (a calendar: a todo's due pill, the Due fold, Upcoming), now (a
clock: Now), all (four tiles: All, on the kind row and the Todos screen), later (bookmark: Later), board (a whiteboard on
its stand), link, open (an arrow out of a box: a link card's Open), file, download,
share, edit, trash, search, filter (two sliders: the Filters chip), close, back, next, fit, retry (also Reopen), offline; the editor's keys draw their own (an empty box, a bulleted and
a numbered list, lines moved in and out); the nav's plus, check box and magnifier are
inline in `index.html`. The app icon (`web/public/icon.svg`, PNGs by `npm run icons`) is the
paper scrap on amber; the header mark is the same scrap in amber.

## What we don't do

- No web font, icon font, CSS framework or component library in the shell. The drawing viewer
  is a separate lazily loaded chunk on React and Excalidraw, with Excalidraw's bundled fonts,
  and is outside the 16 kB shell budget.
- No colour outside `tokens.css` (the debug panel aside), and no second accent; no gradients
  except the photo viewer's scrim and the fade mask at the end of a sideways-scrolling row
  (`.tags`, `.refine`, `.toptags`: a 32 px `mask-image` fade to transparent, not a colour).
  High-contrast mode uses the system's colour keywords.
- No colour as the only signal: selection also raises, failure also says so in words.
- No sheet or dialog for choices: the Filters panel opens in place (above), the browser's
  `confirm()` stays for destructive questions, and the share menu is a light-dismiss popover.
  The full-screen photo viewer and drawing viewer (`role="dialog"`, `aria-modal`) are the only
  modal surfaces of our own.
- No transition or entrance longer than 260 ms, no motion that carries meaning, none under
  reduced motion. The exceptions are the two looping indicators, which stop under reduced
  motion: the busy icon's pulse (0.8 s) and the image placeholder's shimmer (1.2 s).
- No touch target under 48 px where it can be avoided (the 36 px badge, the 30 px remove button
  and the 42 px `.chips` segments extend their hit area with an invisible `::after`). The
  exceptions: the `.facet` chips and the tag-field inputs in the Filters panel and the tag
  editor are 44 px high; the embed chip's ✕ is 40 px wide (48 high); and the Photo / Drawing
  tabs are 42 px segments in a 48 px track, with no extension. No text under 12.75 px, except
  the 0.7rem (about 12 px) count on the Filters button, which is not interactive and is also
  in the button's name; no text pair under AA.
- No dimming to mean "busy": the label (the text) is never dimmed, since opacity would break
  contrast; it says "Preparing…" in words, and only the control's icon pulses.
