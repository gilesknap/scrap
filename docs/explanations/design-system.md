# The PWA's design system

The phone app is a tool you reach for one-handed, often in a hurry: open, capture, gone. The
design follows from that, and from keeping the app tiny: the shell (capture, lists, pages,
search) uses no UI framework, icon library or web font, and its JavaScript is held under 16.5 kB
gzipped (`npm run size`, `web/scripts/size.mjs`). The one exception is the drawing viewer for a
photo's drawing: a separate chunk, fetched only when a drawing is shown, built on React and
Excalidraw with Excalidraw's own fonts (served by scrap from `/excalidraw/fonts/`), and outside
that budget. Everything visual is defined once, in `web/src/tokens.css`; the components in
`web/src/style.css` (which imports `web/src/css/*.css`) and `web/src/excalidraw.css` (the photo panel and the drawing viewer) use
nothing else. This page is the portable description, for carrying the design into another tool
and back.

## Principles

- **Paper and ink, one colour.** Warm off-white paper and warm black ink in daylight, a warm
  near-black and cream at night, and a single amber (a sticky note: scrap's mark). Filled amber is the one hero (the screen's
  primary action) and the badge dot; **amber-soft means only "selected" or "active"** (a chosen
  chip or segment, the current nav tab, a match highlight), never a label, count or state; and
  there is **no amber decorative text and no amber link in the app's chrome** (counts,
  headers, Claude's cards): links there are ink, underlined (Links, below). Amber link text
  is the owner's own text's alone. Red means only "destructive", "failed" or "overdue".
  No blue-greys, no second accent.
- **Links: every text link is underlined; its colour says whose it is.** A link in the
  owner's own text (a page's Markdown and `[[wiki]]` links, a topic's notes, the editor's
  Preview: `.body`) is `--accent-ink`, underlined. Every other text link, Claude's (Related,
  Topics, Sources, a write-up's links) and the app's (Regenerate, Clear filters, Clear all,
  Edit pins, Put back, Discard it, "1 snoozed", "by Claude"), is its text colour (`--ink`, or
  `--ink-2` for a quiet control) over a thin underline: `--line-strong`, 1 px, offset 0.2 em.
  On a card where `--line-strong` is under 3:1 (the Claude card's `--sunk`, the restored-draft
  line's `--accent-soft`) the underline is `--ink-2` (`--link-line`). Each keeps its weight;
  Claude's links are regular. One rule draws them all (`a`, `.link` in `css/base.css`, and
  `:where(.body) a` for the owner's, a write-up's `.body` excepted), so a new link follows it without a rule of its own.
  Not text links, so not underlined: whole-row list items (search, Todos, topic, Pinned and
  Recent rows), chips and pills (tags, filters, the due chip), icon buttons, the nav and the
  kind row, buttons that look like buttons (`.button`, Download, a link card, a file card), the
  top bar's Back and jump, footnote marks, and a section's heading that links (a Type heading,
  which reads as a heading).
- **One hero per screen.** Composer and editor: Save, the one amber fill. Todos: no hero (New
  todo is a quiet + in the top bar). Capture: no hero; its
  three actions (Camera, Gallery, Note) are equal tiles, since none is more likely than the
  others. Page: a todo's or a Later's **Mark done**, the toolbar's one fill; a page with no
  status has none. Everything else steps down: secondary (outlined surface), then
  ghost (text only).
- **Under the thumb.** Actions on the thing in hand live at the bottom: Capture's actions and
  the nav on a list screen, a page's toolbar on a page. Getting around lives in the top bar
  (Back and the jump to the list), so a page has no nav and its bottom bar only ever acts on
  that page. On a computer (a mouse and a window 900 px wide or more:
  `css/desktop.css`, one media query, so a phone or a touch tablet never changes) things go
  where the eye and the mouse already are instead: the nav is tabs in the middle of the top bar
  (icon beside its word, the current one on `--accent-soft`, the Todos count after the word;
  on a list screen the top bar's own column is 960 px there, and a long development version in
  the wordmark is cut with …, so four tabs clear the wordmark and Settings; a page, which has
  no nav, keeps its Back, jump to the list and pager on the 720 px column),
  Capture's tiles are a row over the list, a page's actions are a row of buttons under its
  title, meta line, dates line and chip row, kept in view under the top bar as it scrolls (Mark done
  filled, Delete apart at the end), toasts sit at the window's foot as wide as they need, and
  rows, chips, tiles and ghost buttons take `--sunk` on hover. Cancel, Preview and Save sit in the editor's top bar
  because the keyboard owns the bottom.
- **Drill down, then Back, named.** A page is a drill-down. On every phone and browser the
  top bar swaps the wordmark for Back named for where it goes (‹ Search, ‹ Todos, ‹ Topics,
  ‹ Capture, or a page's title), as a mail app's ‹ Inbox, and it goes up one level: to the
  page you followed a link from, else to the list you opened it from (past the pages the pager
  stepped through). When Back doesn't go to the list, the list's name follows it as a second
  target, ‹ A · Search, which jumps straight back to the list. A page opened cold goes up to
  its parent list (Todos for a todo, Topics for a topic, Capture for any other page): Back goes
  where its label says, with no request, so while the page is still loading that is Capture
  and on a stalled link it is never a dead button. Every link to a page, `[[slug]]` or its full
  address on any address the server is reached at (the one the app was opened at, and each in
  `SCRAP_PUBLIC_URL`, which the server writes into `index.html`'s `scrap-origins` meta tag),
  opens in place, so the phone's own Back walks back through them one step at a time, as the
  top bar's Back does after a link.
  Delete is one step back (the list, or the page whose link opened it) with **Undo**; opened
  cold, it goes where Back names.
  Whichever Back (the top bar's, the jump, the phone's) or Forward, a screen comes back
  scrolled where it was left (`scroll.ts`: the position rides in its history entry, put back
  once the screen is tall enough, never smoothly; the search screen keeps its own).
- **Icons with words.** Icons help find a control; the word says what it does. Icon-only
  buttons (close, previous/next photo, remove a photo) carry an `aria-label`.
- **Calm states.** Empty, offline and error states are an icon, one plain sentence and at most
  one action (offline or unreachable, everywhere search included: why, and **Retry**). On the capture screen a problem is a quiet inline line, never a whole screen;
  offline there is the badge, the waiting rows and one line, with no card, Retry or toast.
- **Say it once.** A row shows its kind by its icon alone, and a status that ends it (done,
  cancelled) as a word on its meta line ("· done"). A page says its kind and status once, in its
  meta line. A count shown in a header is not said again by an empty state (a search with no
  results shows no count).
- **Few sizes, one style per job.** A screen's text uses few sizes, each for one role (a page's
  header: two; a Claude card: two); a pill or chip has one style per job: selected or active on
  `--accent-soft`, a tag on `--sunk`, an editable chip as the others it sits with. A label never
  breaks inside a phrase: a line of " · "-separated parts breaks only before a "·", which leads
  the part after it, so no line ends in one.
- **Dark is designed, not inverted.** Surfaces get lighter as they come forward; amber is a step
  lighter; toasts stay dark slabs in both themes.
- **Every gesture has a button.** Swipes are shortcuts, never the only way: a row's Edit and
  Delete are also on its page (and a row's tick is a button of its own, with Mark done and
  Reopen on the page too), the page's swipe is also its ∧ ∨ pager and the arrow keys.
  Gestures start away from the screen's edges, which belong to the phone's Back gesture.
- **Motion confirms, never decorates.** 90-260 ms, eased out; none under reduced motion. The
  two looping indicators (busy, loading image) are the only motion that runs longer.

## Tokens

Light / dark values, held to WCAG AA (4.5:1 for text, 3:1 for control edges) twice:
`web/tests/contrast.test.ts` reads `tokens.css` and checks the listed text/background pairs,
every rule in `web/src/css/` that sets both a text colour and a background from tokens, and white
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
| `--sunk` | `#ece7dd` | `#2c2723` | wells: tiles, segmented track, placeholders, pressed |
| `--ink` | `#1e1b16` | `#f2ece1` | text |
| `--ink-2` | `#5c564c` | `#b8b0a2` | secondary text: dates, hints |
| `--ink-3` | `#6e675c` | `#958d80` | placeholders, captions |
| `--line` | `#e2dccf` | `#423b33` | hairlines (decorative) |
| `--line-strong` | `#8f8778` | `#706858` | field and control edges; the underline of a link that isn't the owner's (`--ink-2` on `--sunk`, where it is under 3:1) |
| `--accent` | `#eba13a` | `#f0ac4b` | the hero's fill, the badge dot, a selected segment's icon, a new topic's dot |
| `--on-accent` | `#1e1b16` | `#1e1b16` | text on accent |
| `--accent-ink` | `#8a4f00` | `#f3b65c` | accent as text: links in the owner's text, focus ring, active icon |
| `--accent-soft` | `#f8e6c6` | `#3a2c17` | selected or active only: a chosen chip, the active nav pill, a pressed toggle, match highlights, a swipe to Edit |
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
| Button, ghost | `.ghost`, `button.link` | no fill (Cancel, Discard it, the pager's ∧ ∨) |
| Button, danger | `.danger` | red label, never filled |
| Tile | `.tile` | icon over a short label on `--sunk`, 72 high; the capture actions Camera, Gallery and Note, three equal columns |
| Toolbar | `.tools` | icon-over-label tiles sharing the width by their labels (`flex: 1 1 auto`), so no word is cut, every label `--t-xs`; page actions only, no navigation tiles (sticky at the bottom, where the nav would be: a page has none; over the page text: `z-index` 2), viewer tools. A page's order: **Mark done** (a todo or a Later open or in progress: `.primary`, `--accent` fill, `--on-accent` label, `--r-md` corners, wider at `flex: 1.6 1 auto`, the check icon; while a form is open in the page, its tags or its due date, a plain tool, so the form's Save is the one fill), or **Reopen** in its place once done or cancelled (plain, the retry icon: a cancelled one looks closed, so it offers only Reopen), **Edit** (or Edit draft), **Share**, **Delete** (danger); Download is in Share's menu, or in Share's place where the browser can't share. Four fit whole at 360 px |
| Segmented control | `.chips` (radio group) | the editor's kind (`.kinds`: Note, Todo, Later, Board, Doc: short labels so all five fit one row from 320 px, with the full names Whiteboard and Document as the radios' accessible names and titles), the search screen's kind row (`.kindrow`: All, Notes, Todos, Later, Boards, Docs, each its kind's 18 px icon over its word, All a grid of four tiles, so all six fit one row from 320 px; always shown, under the filters on; one tap sets or clears `kind:`, Todos included: it filters in place like the others), the Todos screen's **Now** (a clock), **Upcoming** (the due calendar) and **All** (the grid), drawn as the kind row; selected = raised surface, amber icon. The editor's kind picker draws each kind's icon over its word too (`--t-xs`), as the kind rows do, so every kind bar shows its icons at every width; at a large text size the kind rows and the picker wrap rather than clip |
| Top bar | `header` | wordmark with the scrap mark; at the right, the queue badge, then **Settings** (`#settings`, a ghost cog with eight teeth, "Settings", on every screen: it opens a sheet like the editor's with two radio groups, App theme System / Light / Dark and Drawings theme Light / Dark / Same as app, then under **Store** a **Store health** link and a **Trash** link, each with a button's look and a hint line; Done, Escape or Back close it, and Store health or Trash closes it, then opens its screen). The wordmark's version (`#ver`, `--t-sm`, `--ink-2`) sits on its baseline. On a page, on every phone and browser, Back in the wordmark's place (`#back`, a ghost button 48 high: the arrow, then where it goes in `--t-md` semibold, `#backto`: "Search", "Todos", "Capture", or the title of the page a link was followed from; accessible name "Back to Search"): it goes up one level, to the page a link was followed from, else to the list the page was opened from, else up to a parent: Todos for a todo, Topics for a topic, Capture for any other page (`go()` gives each entry it pushes its depth, the list it came from, kept by a page opened from a page, and, opened from a page, that page's depth and title, kept by a replace, so Back is one `history.go(-n)`; each screen records its name for its depth (`crumbs.ts`: a list's when drawn, a page's title each time it is shown, so renamed in its editor or by Claude too) in `sessionStorage` and in memory, so Back names a page as it is now, renamed, stepped on by the pager or replaced by its parent, a reload keeps it, and a browser that refuses storage still has it; a list's mark says where it was, so only a name recorded there names it). After Back, either the jump to the list or the pager. The jump (`#jump`, on every phone and computer: a page has no nav), when Back goes to a page that isn't the list: a dot (`aria-hidden`), then the list's name, a ghost text button with no icon (`#tolist`, `--t-sm`, `--ink-2`, 48 high; accessible name "Back to Search"), which goes straight to the list (one `history.go(-n)`); the pager (below, in `#pos`) when the page was opened from a list. Then the queue badge and Settings. Back ends where the jump begins (`header.crumb`), else at the free space before the right-hand controls; its label is cut with …. Beside the jump (`header.crumb`) Back never shrinks under 6.5 rem (the arrow and a few letters) and the badge and Settings never shrink (`flex: none`), so Back's label gives up the width; elsewhere (a list screen, a page with its pager) they may, so the wordmark, a two-part badge, New todo and Settings fit at 320 px, and a pager beside a badge does not widen the page. Sharing the bar with the jump or the pager under 560 px, the badge is compact, its dot and count ("● 2", a 48 px target with the 36 px pill drawn inside), named with the count and its words ("2 queued: 1 waiting · 1 failed"): at 360 px with it up, Back keeps about 150 px of a title, at 320 about 110. On the Todos screen, **New todo** (`#new`, a ghost plus, "New todo") at the right end, the badge beside it when up: it opens the composer with Todo chosen (kept even if the text is a link), which closes back onto the list; the list fetches again as the upload queue changes, so the new todo joins it |
| Badge | `.badge`, `.badge.failed` | a pill on `--sunk` with a status dot: the amber dot alone says waiting (the pill is no amber-soft: that means selected); failed is `--danger-soft` with a red dot and `--danger` words; "1 waiting · 1 failed", named with its count first, "2 queued: 1 waiting · 1 failed", so the compact badge's "2" leads its name. On a page under 560 px wide whose top bar also holds the jump or the pager: compact, the dot and the count ("● 2") |
| Bottom nav | `nav` | four tabs, Capture, Todos, Search, Topics (the newest last, so the others keep their places): icon over label; active item gets an amber-soft pill and ink label (`aria-current`). List screens only: a page hides it (`body.paged`), its toolbar is its only bottom bar, and the top bar's Back and jump are the way out. It grows with its labels at a large text size (`--nav-h`) |
| Nav count | `nav .due-n` | the Todos tab's open todos due today or overdue: a 20 px `--ink` pill with `--bg` digits on the icon's corner (after the word on a computer), ringed in `--bg`: a count, never amber; hidden at 0; the tab's accessible name says it ("Todos, 3 due"). One count request when the app opens or comes back and after a change, never polled |
| List group | `.list` | rows in one rounded card; `.pending` is dashed (still on the phone) |
| List row | `.list li` | 48 thumbnail or kind icon (the icon says the kind), title, then one meta line: its date, or for a todo with a due line its due line in the date's place ("high · due 26 Oct · 1 of 4", `small.due`; a priority alone says "low priority"), a Later's medium ("· Book"), a topic's "· Topic", and a status that ends it as a word ("· done", `em`, classed by its word); a search hit's snippet, tidied (`snipclean.ts`: task boxes out, a web address said as words, "en.wikipedia.org · wiki / Integrated information theory", a title leading it cut away; a long word breaks rather than being clipped), and none if it only repeats the title (the same whole words in order, punctuation, hyphens, underscores and case aside: `echoes()` in `snippet.ts`); a cancelled row (`li.cancelled`) has its title struck through in `--ink-2`; actions under it (`.rowbar`: whole words, the bar wraps to a second line rather than breaking a label such as Split and retry); a focused row draws its ring inside the card |
| Swipe row | `.list li.swipe`, `.row-under` | follows the finger; behind it Edit on `--accent-soft` (right) or Delete on `--danger-soft` (left); past the threshold the icon grows (Edit's turns `--accent-ink`, its fill staying `--accent-soft`) and letting go does it |
| Fold | `.claude-text` (`details`) | hairline above, a chevron before the heading: right folded, down open |
| Pager | `.pager` | a page opened from a list, in the top bar as a mail app has it: "3 of 23" (`.pager .at`, `--ink-2`), then ∧ (previous) and ∨ (next), 40 px ghost links, the one with nothing that way at 35 % opacity. Its group's label says which list ("In Latest"): "Latest" (Capture's list, and the search screen's newest-first list), the kind row's name when one kind is chosen alone ("Notes", "Todos", "Later", "Boards", "Docs"), "Search results", "Todos · Now", "Todos · Upcoming", "Todos · All" and "Todos · Done" (the Todos screen's folded done and cancelled), "Topics"; Back beside it names the list's screen and goes back to it; the page follows a sideways swipe and slides off to the next. From the Todos screen, Mark done steps on to the next todo with a toast "Done: <title>. Next todo, 3 of 9" and **Undo** (6 s); on the last, "Done: that was the last in the list" and **Back to list** |
| Status word | `.list em` | on a row only for a status that ends it: "· done", "· cancelled", `--ink-2` at `--t-sm` on its meta line, as a page's meta line says it (no pill; an open todo or Later has none: its icon says the kind) |
| Meta line | `.meta` (`pagehead.ts`, `pagemeta.ts`) | a page's header under its title: one quiet `--t-sm` `--ink-2` line, its kind word first in `--ink` semibold after its kind's 16 px icon (a topic's: the open book), then what else it is (a Later's medium and what it is for, "Later · Book · to read", or once done what was done, "Later · Book · read"; a status other than open; a todo's snooze and tasks), then "by Claude" on a page Claude made (below), then, on one line when the kind is all there is to say, the dates (below), else the dates on a line of their own. The parts are children of a flex-wrapping `.parts`, each `nowrap`; each part after the first draws its own leading "·" in a gutter the row is pulled left over and the line clips, so a part that starts a line loses its dot and no line ever ends or starts with one. The line has 4px of padding taken back by margin, so a link's focus ring is not clipped. Two sizes in the whole header (the title, `--t-sm`) and one red word (overdue, in the due chip) |
| Dates line | `.dates` | "Created 24 Oct, 09:12 · Edited 25 Oct, 14:03" (`whenShort`), `--t-sm`, `--ink-2`; Edited only when the last change was more than a minute after creation. When the kind is all the meta line has to say (a note, board, doc or plain todo) the dates join it on one line ("Todo · Created 25 Oct, 11:52"); otherwise they are a second line. Its parts wrap as the meta line's do |
| Due line | `.list .due`, `.duechip`, `.todoedit` | a todo's priority and due date in words ("high · due 3 Nov"; a priority alone "low priority"), `--ink-2`, its parts never breaking inside (no-break spaces, the line breaking only before a "·"); overdue (`.late`: due before today, not done or cancelled) says "overdue" in `--danger`, semibold: the word carries it, never colour alone; done or cancelled (`.closed`) keeps its due date in `--ink-3`, said as a date ("due 3 Nov"), never "today" or "overdue". On its page, the due chip leads the tag row (the calendar icon, "overdue 24 Oct · high" with only "overdue" in red, else "Add due date" on an open todo; a closed todo with none shows no chip: Reopen it first) and opens `.todoedit` in place under the row: under a small uppercase `.flabel` heading **Due** (as the Filters panel's rows), one row of `.facet` chips (`.soon`, a group "Due soon": **No date**, **Today**, **Tomorrow**, **Next week**, seven days on by the phone's calendar; the one matching the date set, No date while there is none, `aria-pressed` on `--accent-soft`, semibold; two and two under 380 px, never one alone), then the native date input (named "Due") for any other day; **Priority**, a native `select`; **Snooze**: **No snooze**, **Tomorrow** and **Next week** chips (a group "Snooze for") and a native date input (named "Snooze until"); then Cancel and Save. Every row starts at the same left edge. The editor shows the same in its Due fold while the kind is Todo, without the Due heading (the fold says it) and without Snooze. Saved with a snooze later than the due date, the form asks first in place (`.choice`, a group "Due date": "Snoozed past its due date (25 Oct). Move the due date to 2 Nov too?", **Move due date**, primary, and **Keep due date**); a snoozed todo's line ends "· snoozed till 3 Nov" and it is out of Now, Upcoming and the nav count until that day. The due line wraps rather than being cut (when it is due outranks one tidy line) |
| Filters button | `.field-search .ffield` | a 48 px slider icon (filter) at the search field's end; `--ink-2`, and while the panel is open (`aria-expanded`) an `--accent-ink` icon on `--accent-soft`. No count badge: the chips below say what is on |
| Filters on | `.refine .fon` | under the kind bar, each filter on (not the kind row's kind) as a `.facet.on` chip with a ✕ (`aria-label` "Remove #home"), saying it in words ("#home", "past month", "A–Z", "Written by Claude"), in a row of its own that wraps (never scrolls sideways); no filters, no row. The search screen's order is: search box, kind bar, Filters on, results header, results |
| Results header | `.rhead`: `.count`, `.acts` | one 48 px line that never changes shape: the count on the left (`--ink-2`, `--t-sm`, "10 pages"; none when nothing was found, the empty state saying so), then its actions as 48 px ghost buttons on the right. On the search screen **Pin search** and **Copy link** (`searchacts.ts`), icon buttons; a pinned search's pin is filled (`.on`) on an `--accent-soft` disc, named "Unpin search". The Todos and Topics screens draw their count line with it too: **Refine** (the filter icon, named "Refine in Search: <query>", tooltip "Refine in Search"), the view as a search, and on Now **1 snoozed** (a ghost text button in `--ink-2`, `--t-sm`, underlined as a link is, to the search `kind:todo is:snoozed sort:due`). No ⋯ fallback and no amber text links, on any screen. Icon-only is a deliberate exception to "icons with words": each has an accessible name and a tooltip, and Pin's and Copy's toasts ("Pinned", "Link copied") say the result in words |
| Filters panel | `.fpanel` | opens in place under the search field, above the kind row (the filters it puts on show under the kind row, as chips), a `--surface` card with a `--line` hairline and `--r-lg` corners. Rows (`.frow`, a group each), a small uppercase `.flabel` heading in `--ink-2` above its `.facet` chips, which wrap and never scroll sideways or clip, every row starting at the same left edge. **Order** and **Group** share the heading **Arrange**, each with a small sub-label (`--t-sm`, `--ink-2`) over its chips: **Tags** (`.ftags`: a pill field "Add a tag", then on the next line the tags it offers: with nothing typed, the current results' top tags with their counts (the 12 the search's facets give), or with no search yet the 8 most used top-level tags; as typed, the results' tags that match (those starting with the typed text first), at most 8 (the matches come from `search/facets?top=1000`, asked for only then; before any search, from every tag in use); none, a line saying why), **Order** (the default first: Best match with words typed, else Last edited; then Newest, Oldest, Last edited with words typed, A–Z, and for `kind:todo` Due soonest and Priority) and **When** (1w, 1m, 1y, Dates…, and By created date once a range is on; Dates… opens From and To date inputs, applied as picked); a chosen chip `aria-pressed` on `--accent-soft`, semibold (a chip's count, `small`, shares the label's line height so it sits on its baseline rather than raised); then **Clear filters** (`button.link`) while any are on. Each row is scrolled so its chosen chip shows. `refine.ts`, a chunk of its own, kept offline by the service worker |
| Todos screen | `.todos` | the segmented control again, as the kind row (**Now**, a clock; **Upcoming**, the due calendar: due from tomorrow to 7 days away; **All**, the grid: each sets its own order, so no Sort), then the results header (`.rhead`, above: "12 open todos", and at its end on Now **1 snoozed**, then **Refine**), then Now's groups under `h2.label` headings ("Overdue · 3", "Today", "High priority", "Open": not "Later", which is a kind), each its own `.list`; rows are two lines on every tab: the title (wrapping to a second line rather than cut: no thumbnail beside it), then the due line (CSS `order`) and a done or cancelled word; no edit date, no kind icon and no thumbnail (every row is a todo, so the room goes to the title and every title lines up; a todo with a photo has a small picture mark after its details line instead). New todo is the top bar's + (above) |
| Topics screen | `.topics` (`topics.ts`, `topics.css`: a lazy chunk) | the topic pages Claude keeps (#261), from `GET /api/topics`: a filter box (`.field-search`, "Filter topics", matching every word typed in the title, summary or area; kept in the history entry, so Back from a topic finds it as typed), the results header (`.rhead`: "12 topics", "2 of 12 topics" while filtered, and **Refine**, to the search `is:topic`), then a group per area under an `h2.label` ("epics · 4"; *Other* for no area, last), each a `.list` of text rows with no thumbnail or kind icon, so every title lines up: the title, the synthesis's lead on one line cut with …, and "3 sources · 25 Oct, 10:04". A topic new or changed since this device last looked has a 9 px `--accent` dot at its row's end by its title (`.new`, named "new or changed", with a tooltip: not colour alone), kept until the app closes or the topic's page is shown, however it was reached (the list, a
search, a link, the pager); what was seen is `scrap.topics.seen` on the device, and the first look shows no dots. The rows are one pager trail, "Topics". Empty: the open book, "No topics yet." and a line on the weekly pass |
| Store health | `.health` (`health.ts`, `health.css`, a chunk of its own; `/health`) | opened from Settings: an `h2.label` "Store health", a `--ink-2` hint line, then the health checks as one `.list` group, a row each (Orphans, Untagged, Stale todos, Duplicates, Dangling links, Outdated write-ups: `checks.ts`): its name (`strong`, wrapping) over what it finds (`small`), and at the row's end its count (`.n`, `--t-md` semibold `--ink`, tabular figures; `0` in `--ink-2` at 500), a link to the check's search (accessible name "Orphans: 3"), rows 48 high at least (no thumbnail); a hint line under it says an outdated write-up waits for the owner, and that the nightly and weekly passes refresh related pages and topic syntheses (not listed). No nav tab is current; Back (the phone's) goes back to where it was opened from. The Filters on row names a check's chip by its name ("Dangling links") |
| Trash | `.trash` (`trash.ts`, `trash.css`, a chunk of its own; `/trash`) | opened from Settings: an `h2.label` "Trash", a `--ink-2` hint line saying how long a deleted page stays ("Deleted pages stay here for 30 days, then scrap deletes them for good…", from `GET /api/trash`'s `days`; with purging off, "…until you restore them"), then the pages in the trash as one `.list` group, most recently deleted first, a row each with no thumbnail or kind icon: its title (`strong`, cut with …) over what happens to it (`small`, `--ink-2`, never cut, a line per part with its date kept with the words before it: "Deleted 20 Oct" then "deleted for good after 19 Nov", "deleted for good at the next nightly clean-up" once due, "kept: Claude won't make this topic again" for a topic page; the " · " between them is in the text for a screen reader, not drawn), and at its end **Restore** (a secondary button with the retry icon, 48 high, accessible name "Restore <title>"). Under the list, when it stops short of the trash (100 rows), a hint line "Showing the 100 most recently deleted of 130." Restore brings the page back, the row goes (focus moves to the next row's Restore, or to the heading once the last row has gone and the empty state shows), and a toast "Restored: <title>" offers **Open**; a failure toasts why and the button works again. Empty: the trash icon, "The trash is empty." A trashed page has no page view, so a row is not a link. No nav tab is current; Back (the phone's) goes back to where it was opened from |
| Done fold | `.donefold` (`details`) | Now's done and cancelled todos, folded at the end: a 48 px summary in `--ink-2` with the chevron of `.claude-text` |
| Search sections | `.groups`, `h2.label` | the search screen's grouped results (Group row in Filters: Type, Now, Due, Area, None, A–Z, Tag; the list's own first; for `is:topic` Area is the default and the row reads Area, None, A–Z), also drawn by the Topics screen. A–Z is one continuous card: each letter a slim divider row with no count, sticky under the top bar; the other groups keep their counts, drawn as Now is: an `h2.label` heading with its count ("To watch · 4") over each section's `.list`, done and cancelled in a `.donefold` at the end. The server orders by section, so a page of results never splits one and Show more only appends. A Type heading is a link to that type alone (`later:watch`) unless one is asked. Later rows end with the type (`.media`: "Book"); the editor's **Type** fold (a `select`, on Later pages) sets it |
| Row tick | `.list .tick` | a todo's or a Later's row: a 48 px toggle (`aria-pressed`, `aria-label` "Done: title") at its end, beside the row's link rather than in it, so tapping it opens nothing; an empty box in `--ink-2` (the tick icon), ticked in `--accent-ink` when done, a bar across it (`aria-pressed="mixed"`, `--accent-ink`) while only some of the page's task boxes are ticked, its row saying "2 of 5"; a cancelled one has a grey dash in its box, and pressing it marks it done; it slides with the row, and a drag that starts on it swipes the row |
| Claude card | `.claude`, `.enrich` (`ingest.ts`, `writeup.ts`, `enrich.ts`) | everything Claude makes, so it never reads as the owner's text: a `--sunk` card, `--r-md`, at two sizes: `--t-sm` for all its text (its summary and a write-up's headings too, semibold) and `--t-xs` for its by-lines and kinds. Its first line (`.ingest`) is its title (`.ctitle`, bold `--t-sm`), saying what it holds: **What's in the photo** (under each photo) and **About this page** (one, after the page's text), and at that line's end its action: **Generate** the first time (a button), **Regenerate** after (`button.link`, quiet: rarely wanted), **Retry** when it failed, **Resume** when paused. Under the title, only while Claude has it, where Claude is up to as a line of words, no pill (`.state`: "Waiting for Claude", "Claude is reading it…", "Paused (reason): nothing is lost", "Claude couldn't read it: …" in `--danger`). Never read, a line in `--ink-2` says what Claude would do (not once it failed); then its parts as folds (`.claude-text`: a chevron, a semibold `--ink-2` heading, a `--line` rule above): Description and Text in the photo (its `pre` on `--surface`), In detail (a board's write-up or a topic's synthesis, in About this page: a by-line "Claude · 25 Oct, 22:00 · v2", the model by name in its tooltip, then its text, with Guidance for Claude and Versions as folds inside), a board's folded until opened, a topic's open until closed (it is what the page is for); Summary (a board's is its write-up's lead), then Topics (a source's, below), Sources (a topic's, below) and Related, open until closed; each remembered on the phone. Claude's links (a source's Topics, a topic's Sources, Related, a write-up's) are the app's links (Links, above): `--ink`, regular, underlined in `--ink-2` (`--line-strong` is under 3:1 on `--sunk`), each a 48 px target; amber links are the owner's text's. A photo's Regenerate asks before replacing a drawing the owner edited; About this page's is Ask (it reads the page again and, on a board, writes it up and finds related pages again too), named for the write-up on a board; its state line is the write-up's state, else the page's (a pause always the page's, with Resume) |
| Topic parts | `.enrich .topics`, `.enrich .sources` (`topic.ts`, `topic.css`) | Claude's topic pages (#261), in About this page. On a source, **Topics** is a fold (open until closed) drawn as Related is, straight before it: a line per topic, the topic icon hung in the indent, its title an `--ink` link, underlined. A card with only topics to show is still the card, with that one fold. Related marks a topic citing it "· in a topic". On a topic, after In detail, **Sources · 3** (a fold, open until closed): a 48 px row per source, its title (an `--ink` link, underlined) then "· Note" (its kind) in `--ink-2` at `--t-xs`, and a 48 px ghost ✕ (the close icon in `--ink-2`, "Take out <title>"); one taken out stays, its title struck through in `--ink-2`, "· taken out", and **Put back** (`button.link`) in the ✕'s place; taking out toasts "Taken out: <title>" with **Undo**, and focus goes to that source's new button. A failure toasts why, the button usable again. Offline the ✕ and Put back are disabled, their tooltip saying why (as a page's task boxes are). Its Related leaves its sources out. The page's notes come before the card: empty, one `--ink-2` line (`.page > .notes`) says where they go |
| Link card | `.md > .linkcard` | on a Later page, a paragraph that is only a link to the web (`cards()` in `render.ts`) is drawn as a file card: its site (no `www.`) over its path, tidied to words ("wiki / Integrated information theory": no escapes, trailing slash or `.html`; or the link's own text, if it was given one), each cut to one line, and **Open** (the open icon) with a button's look at its end. The whole card is the link, one tab stop |
| Draft row | `.capture .draft` | the composer's kept draft (left by Back), one quiet line on `--sunk` over Capture's tiles, the whole width, `--t-sm`: the kind's icon (a photo's for photos), "Draft: " and its first line, cut with …; tap to carry on; a 48 px ✕ ("Discard draft") at its end, with **Undo** in a toast. The tiles always start a fresh capture; beside a kept draft it is saved as typed under a key of its own (`fresh.ts`), and takes the kept one's place, with **Undo**, when left by Back or when found after the app was killed |
| Offline line | `.strip .offline` | Capture offline, in Latest's place: "Offline: showing what's on this phone", `--ink-2`, `--t-sm`; Latest draws itself again when the phone is back online |
| Figure | `.orig` | a page's photo as a preview, with no caption: a tap opens the viewer, which names it (`.viewer .name`, a pill at the top left, cut with … when long) and has its **Download**. A file the server can't preview is a row with its name and **Download** (`.save`, whole words) |
| File row | `.filerow` (`filerow.ts`, `files.css`) | a file below a page's text that is not a photo (a PDF, a text file): a card with the file icon, its name (wrapping) and, once read, a PDF's page count under it (`small`, `--ink-2`: "12 pages"); the card opens the file in a new tab, **Download** beside it. Under the name, the quiet hint "Text couldn't be read; not searchable" (`.hint`, `--t-sm`, `--ink-2`) only when reading failed or found no text: nothing while it waits or is read. No Claude panel |
| Thumbnail | `.list img`, `.thumbs img`, `.originals img` | fixed size or 4:3 frame reserved before load, shimmering `--sunk` placeholder |
| Photo strip | `.thumbs` | 84 squares, remove button with a 48 target |
| Field | `input`, `textarea` | surface, strong edge, 2 px accent-ink focus ring |
| Search field | `.field-search` | pill with a search icon; on the search screen a ✕ (`.clear`, a 48 px ghost button, "Clear search") at its end while it has text, in place of the browser's own |
| Recent searches | `.recents-top`, `.list.recents` | under the search field while it is empty and focused (gone once it has text, or loses focus): an `h2.label` "Recent" with **Clear all** (`button.link`) at its end, then up to 10 past searches as one `.list` group (`role="group"`, "Recent searches"), newest first: a search icon and the query as typed, start-aligned and cut with … on one line, then its pin (a 48 px ghost icon, "Pin <query>"; once pinned, filled in `--ink`, "Unpin <query>") and a 48 px ghost ✕ ("Remove <query>"), both `--ink-2`. Under the kind row, the newest pages under an `h2.label` "Latest", as on Capture. A tap on the list keeps the field focused until the choice is made; a choice runs it and the keyboard goes. No history: no block at all. On this device only (`scrap.searches`, through `kept()` in `api.ts`, the one guard every `localStorage` use goes through: with storage blocked it keeps nothing and never throws) |
| Editor sheet | `.editor` | full screen over the keyboard; top bar Cancel / Preview / Save. The text box asks for what the kind needs: "Note or link", "What needs doing?", "Link or title", "What the board is about", "What the document is". Just above the keyboard, one line of five equal keys (`.keys`, on `--bg` under a `--line` hairline, gone in Preview; ghost buttons, an icon drawn in `editor.ts` over a `--t-xs` word; under 300 px the icons alone): **Task** (the line, or each line selected, a task, `- [ ] `, a bullet or number keeping its marker; or plain items again if all are tasks), **Bullet** (`- `, or plain again), **Number** (`1.` `2.` `3.` in order at each indent, on from a number just above; or plain again), **Indent** and **Outdent** (a level in or out: nested at the parent item's text column, 2 spaces under `- `, 3 under `1. `, as CommonMark needs, a numbered item renumbered in its new place; in a code block, 2 spaces, and the other keys do nothing); a tap keeps the keyboard up. In the text, Enter continues a bullet, numbered or task list, GitHub-style, and Enter on an empty item ends it (`listedit.ts`) |
| Embed chips | `.editor > .embeds` | the page editor shows each of the page's own images and files as a short token (`⟦image 1⟧`, `⟦file 2: scan.pdf⟧`; `embeds.ts`), and under the fields, above the keys, a chip each (`.embed`: a thumbnail, or the file icon, and its name, cut with …) in one line that scrolls sideways; a tap on a chip selects its token (to cut and paste it elsewhere), its ✕ ("Remove image 1"; 40 px wide, 48 high) takes the token out, with its line if alone on one. Saved, the tokens become the Markdown they stood for, byte for byte where none was touched; a deleted or mangled token is no embed. Gone in Preview |
| Editor fold | `.fold` (`details`) | in the composer and editor, the rarely changed parts folded to one 48 px line each above the text, so the text stays the hero: **Tags** (the tag icon, "3 · #work #garden…", or "none") and, while the kind is Todo (in the composer, not with photos: they have no kind there), **Due** (the calendar, "24 Oct · high", or "none"); the name in `--ink`, semibold, what it holds in `--ink-2`, cut with …, a chevron at its end (down folded, up open); tapped, the controls open in place under it and nothing takes focus. Two folds read as one group. Under the text, the composer's and the page editor's **Camera** and **Gallery** (Add photo) are ghost buttons in `--ink-2` at `--t-sm`; in the page editor the text gives their row (and the embeds' row) its room, so they show whole above the keys |
| Share menu | `.share-menu` | Share's choice, a popover just above it: **Link**, the content (**Text** on a page, **Photo** in the viewer) and on a page **Download** (a link drawn as the rows are; tapping it closes the menu), ghost rows on `--surface` with `--shadow-2`; a tap elsewhere, Back or Share again closes it. What Share and Download do is a chunk of its own (`sharing.ts`), loaded on the first tap |
| Tag line | `.tags` (`pagehead.ts`, `chipfold.ts`) | one row of same-size chips under a page's meta line, drawn inside 48 px targets and wrapping to at most two rows: a todo's due chip first (`.duechip`, the calendar icon; always shown), then its tags, `--sunk` `--t-sm` pills that each link to their search (`/search?q=tag:car`, which includes its children), each said by its last part ("#project-management" for kind/project-management; with as much of its path as tells two apart, "#epics/thoth" beside "#other/thoth"), its full name in its accessible name and tooltip ("Tag kind/project-management"). Beside the due chip the tags are grouped in a `.tagset`, so they go together to the next line when they do not all fit beside it (at 360 px the due chip is alone on a line). The **+** chip (`.add`, "Change tags") is kept on the last tag's line (`.last`) so it never sits alone; with no tags it is a "+ Tag" text chip ("Add tags"). Only the + opens the tag editor; focus returns to it (or to the due chip) when its editor closes. Pills pad by `0.6em`, so a larger text size grows them with the text, not more. When the chips need more than two rows (measured, and again when the row's width or a chip's size changes), the tags that don't fit are hidden and a **+N** pill ("Show N more tags") shows them in place, with + right after it in one box and focus on the first tag shown; a first tag too long to fit beside +N is cut with an ellipsis, never hidden. A tag Claude added (`a.ai`) is the same pill with "✦" before its name, its accessible name adding "added by Claude" (the tag editor marks Claude's the same way). A `--line` hairline (`hr.headend`) under the row ends the header on a phone (16 px above, 20 px below, across the text column, also while the tag editor or the due form is open); on a computer there is none, the action row under the header having its own; the meta and dates lines clip sideways (`overflow-x: clip`, with 4 px of padding and a matching negative margin, so a focus ring or the 48 px "by Claude" target is not cut) |
| Tag editor | `.tagedit`, `.tagform` | the tags as `.facet.on` chips that wrap, each with a ✕ to take it off, then a field, then one row of up to six `.facet` chips with a dashed `--line-strong` edge (offered, where the chosen are filled), one tap each, in a line that scrolls and fades at its end (`.toptags`): with nothing typed, the most used tags not on it yet (a group "Most used tags"); as you type, the tags in use that match, those starting with it first (a group "Matching tags"), and a tap on one replaces what was typed. Our own row, not a native `datalist`, whose menu covers the keyboard on a phone; all from one `/api/tags` answer. On a page, Cancel (ghost) and Save (primary) under it, in place of the tag line; in the composer and editor, inside the Tags fold |
| Toast | `.toast` | dark slab above what is under the thumb, amber text action. A capture saved online says "Saved" at once (offline, on another screen than Capture, "Saved on the phone: uploads when online"); if the server then refuses it, a second toast says "Kept on this phone" (its row says why, with Retry). "Update available" with **Reload** appears when a new version of the app has installed behind the one running; it has no timeout and stays through navigation until tapped, and Reload swaps it in and reloads the app |
| Banner | `.conflict`, `.restored` | danger-soft with a red edge; accent-soft info line |
| Empty state | `.empty` (`empty()` in ui.ts) | icon in a `--sunk` circle, one plain sentence in `--ink` ("Nothing here.", "No matches", "No todos yet."), and at most one extra: a `small` hint line (Capture's "Nothing captured yet." adds "Photos, notes and links you save show up here.") or one action (**Back to capture** on "Not found: it may have been deleted."; **Retry** under a problem, on every screen search included: "Offline: this needs the server." or "Can't reach the server. Check your connection or VPN."). A view still loading after 150 ms is a plain "Loading…" line (`role="status"`) in the same block, without an icon; a quick answer shows no flash |
| Match highlight | `mark` | the matched words in a search hit's snippet: `--accent-soft` with `--ink` text and a 2 px `--accent` underline drawn inside the box |
| Build line | `.build` | the running build (the service worker's cache name, `scrap-…`) at the foot of the search screen: centred, `--ink-2`, `--t-xs`. Five taps turn the debug panel (`debug.ts`) on or off |
| By Claude | `.meta .written` | on a page Claude made, in its meta line right after the kind word: "by Claude", a quiet `--ink-2` link with no pill, underlined as the app's links are (its target 48 px high): on a page written over MCP ("Note · by Claude", named "Written by Claude"), to the search `is:claude`, its tooltip the page's `origin` field ("Written by Claude over MCP" if none); on a topic ("Topic · by Claude", named "Topic by Claude"), to the Topics screen |
| Topic word | `.list .sub .topic` | a search hit that is a topic page: "· Topic" after its date, in `--ink-2` as a Later's medium is; its row's icon is the open book |
| Draft dot | `.dot` | a 9 px `--accent` dot ringed in `--bg` on the corner of a button's icon: a page's Edit when a draft of it is kept (its word becomes "Edit draft", its name "Edit draft (unsaved)") and, on the button's own corner, the drawing viewer's Edit (no room there for words; on its amber fill the dot is inverted, `--on-accent` ringed in `--accent`) |
| Photo panel | `.photo-panel`, `.pair`, `.tabs`, `.drawing-card` (`excalidraw.css`) | under a photo's page: the photo and, if Claude drew one, its drawing, as a `.pair` of two columns from 700 px wide (or landscape from 560 px), else one at a time under **Photo** / **Drawing** `.tabs` (a segmented control like `.chips`: `--sunk` track, the chosen tab raised on `--surface`; 42 px segments in a 48 px track; Drawing chosen to start with). The drawing is a preview (`.drawing-card`: a button in the drawings theme, not the app's (`data-scheme`, from Settings: paper `#ffffff` or Excalidraw's dark `#121212`, with `--ink-2` and `--line` set to match; updated live), with a `--line` edge and `--r-lg` corners, the drawing's own shape, at most 75 % of the screen high, inert to gestures so a drag scrolls the page); a tap opens the viewer. While it renders it says "Loading drawing…"; if it can't, "Can't show the drawing here: tap to open it", or offline "Offline: the drawing needs the server" |
| Drawing viewer | `.drawing-layer`, `.drawing-bar` | the full-screen drawing (`board/viewer.ts`), a `role="dialog"` `aria-modal` sheet over the app (the nav is hidden) that rises in over `--d-3`, on `--bg`. A top bar of ghost text buttons (no boxes, as the editor's Cancel and Preview) sharing the width by their labels (**Close** is the exception: a 48 px ✕ icon button named "Close", as the photo viewer's, `.close`): **Close**, **Fit**, **Photo** (a toggle, `aria-pressed` on `--accent-soft` with an `--accent` edge: the photo beside the drawing in landscape or from 900 px wide, over it in portrait), **More** (a menu: History, Export .excalidraw, Export PNG, Export SVG) and **Edit** (`.primary`); while editing, **Cancel**, **Undo**, **Photo** and **Save** (`.primary`, `aria-busy` while it saves). Under the bar, a live-region `.drawing-notes` (at most 40 % of the height) holds the restored-draft and conflict banners (`.restored`, `.conflict`) and History (`.versions`: a 48 px row per version, **Restore**). The canvas and its tools are Excalidraw's own |
| Photo viewer | `.viewer` | `--viewer`; close top right, count pill top centre, tools on a scrim that fades from clear to `--overlay` |
| Icons | `icons.ts` | 24 px strokes (1.8), currentColor, `aria-hidden` |
| Markdown | `.md` (page text, Preview) | headings a step down a level (see Type), all under the page title; on a Later page, a link alone on a line is a link card (above); code and a table's head on `--sunk`; a table in a `.table` box with `--line` hairlines that scrolls sideways on its own (the page never does); task boxes in `--accent`, in the bullet's place, the list as tight as a bulleted one; each box in a `.taskbox` label with a target `--tap` (48 px) wide and one line high, so no two overlap; each box is named by its item's text (`aria-label`); on a page they tick in place (`tasks.ts`: each box's `data-line` is its item's line in the text, from markdown-it's map), off while offline and in Preview; strikethrough, quotes and footnotes in `--ink-2` (a quote's edge `--line-strong`: no decorative amber); a Mermaid `.diagram` in its dark or neutral theme, following the system's |

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

- **Filters** is a slider icon at the end of the search field, where the thumb already is (no
  count on it: the chips under the kind row say what is on). A tap opens or folds the panel (`aria-expanded`,
  `aria-controls`); it stays open or folded while the app is open, the next search too.
- The panel opens under the search field, above the kind row and the list, so each tap in it
  shows its effect at once. A row per kind of choice (Tags, When, Arrange), each a small
  heading over chips that wrap (never scrolling sideways), keeps it short. The tags
  it offers are capped at 8 when typing (12 for a search's top tags). Typing matches the tags of
  the results (of every tag in use before a search), so there is no separate screen to browse
  them (the Tags screen is retired; `/tags` opens Search).
- What is on is always in view, panel open or not: a row of chips under the kind row, each
  with a ✕, then the results header. The kind row is always shown.
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
  (the top bar, the screen, the nav and the editor), the background still to the edges. On a
  computer a list screen's top bar has a 960 px column, so its four tabs clear the wordmark and
  Settings; a page's stays on the 720 px column.
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
Icons: camera, image, note, tag (the Tags fold), todo (a checklist: the Todo kind, so a row's kind icon never reads
as a ticked box beside its tick box), tick (check in a square: a row's tick, which hides the
check until done, and the Todos empty state; the nav's Todos tab draws the same box inline), done (a check alone: Mark done, so a box always means a tick you can see), add (a plus: New todo, the tag row's + circle), due (a calendar: a todo's due pill, the Due fold, Upcoming), now (a
clock: Now), all (four tiles: All, on the kind row and the Todos screen), later (bookmark: Later), board (a whiteboard on
its stand), topic (an open book: the Topics tab, a topic's row in search, the Topics empty state), link, open (an arrow out of a box: a link card's Open), file, download,
share, edit, trash, search, filter (two sliders: the Filters chip), close, back, next, fit, retry (also Reopen), offline; the editor's keys draw their own (an empty box, a bulleted and
a numbered list, lines moved in and out); the nav's plus, check box, magnifier and book are
inline in `index.html`. The app icon (`web/public/icon.svg`, PNGs by `npm run icons`) is the
paper scrap on amber; the header mark is the same scrap in amber.

## What we don't do

- No web font, icon font, CSS framework or component library in the shell. The drawing viewer
  is a separate lazily loaded chunk on React and Excalidraw, with Excalidraw's bundled fonts,
  and is outside the 16.5 kB shell budget.
- No colour outside `tokens.css` (the debug panel aside), and no second accent; no gradients
  except the photo viewer's scrim and the fade mask at the end of a sideways-scrolling row
  (`.tags`, `.refine`, `.toptags`: a 32 px `mask-image` fade to transparent, not a colour).
  High-contrast mode uses the system's colour keywords.
- No colour as the only signal: selection also raises, failure also says so in words.
- No amber decorative text, no amber link in the app's chrome (counts, headers, Claude's
  cards), no text link without an underline, no amber-soft that doesn't mean selected or active, and no filled amber but the
  screen's one hero.
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
  tabs are 42 px segments in a 48 px track, with no extension. No text under 12.75 px
  (`--t-xs`); no text pair under AA.
- No dimming to mean "busy": the label (the text) is never dimmed, since opacity would break
  contrast; it says "Preparing…" in words, and only the control's icon pulses.
