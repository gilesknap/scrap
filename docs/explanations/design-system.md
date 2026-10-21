# The PWA's design system

The phone app is a tool you reach for one-handed, often in a hurry: open, capture, gone. The
design follows from that, and from keeping the app tiny (no UI framework, no icon library, no web
font). Everything visual is defined once, in `web/src/tokens.css`; the components in
`web/src/style.css` use nothing else. This page is the portable description, for carrying the
design into another tool and back.

## Principles

- **Paper and ink, one colour.** Warm off-white paper and warm black ink in daylight, a warm
  near-black and cream at night, and a single amber (a sticky note: scrap's mark). Amber means
  "the thing to press" or "this one is selected"; red means only "destructive" or "failed".
  No blue-greys, no second accent.
- **One hero per screen.** Composer and editor: Save, the one amber fill. Capture: no hero; its
  three actions (Camera, Gallery, Note) are equal tiles, since none is more likely than the
  others. Page: its toolbar. Everything else steps down: secondary (outlined surface), then
  ghost (text only).
- **Under the thumb.** Capture actions, the page toolbar and the nav sit at the bottom; Cancel,
  Preview and Save sit in the editor's top bar because the keyboard owns the bottom.
- **Icons with words.** Icons help find a control; the word says what it does. Icon-only
  buttons (close, previous/next photo, remove a photo) carry an `aria-label`.
- **Calm states.** Empty, offline and error states are an icon, one plain sentence and at most
  one action. On the capture screen a problem is a quiet inline line, never a whole screen.
- **Dark is designed, not inverted.** Surfaces get lighter as they come forward; amber is a step
  lighter; toasts stay dark slabs in both themes.
- **Every gesture has a button.** Swipes are shortcuts, never the only way: a row's Edit and
  Delete are also on its page (and a row's tick is a button of its own, with Done and Reopen
  on the page too), the page's swipe is also its ‹ › pager and the arrow keys.
  Gestures start away from the screen's edges, which belong to the phone's Back gesture.
- **Motion confirms, never decorates.** 90-260 ms, eased out; none under reduced motion.

## Tokens

Light / dark values, held to WCAG AA (4.5:1 for text, 3:1 for control edges) twice:
`web/tests/contrast.test.ts` reads `tokens.css` and checks the listed text/background pairs,
every `style.css` rule that sets both a text colour and a background from tokens, and white
text on `--overlay` over a white photo; and an end-to-end sweep (`web/e2e/view.spec.ts`)
computes the real colour of every visible piece of text and of what lies behind it, on each
screen in both themes.

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

Type: the system UI face (Roboto on Android); 17 px root. `--t-xs` 0.75rem (labels under icons,
chips), `--t-sm` 0.875rem (meta, small buttons), `--t-md` 1rem (body, list titles), `--t-lg`
1.1875rem (wordmark, field titles, Markdown headings), `--t-xl` 1.5rem (page title). Line height
1.5, 1.25 for titles, 1.6 for page text. Weights 500 (controls), 600 (titles, labels), 700
(page title, active nav).

Space: a 4 px grid, `--s-1`..`--s-7` = 4, 8, 12, 16, 24, 32, 48. Screen gutter 16.
Radius: `--r-sm` 8 (thumbnails, code), `--r-md` 12 (buttons, fields, toasts), `--r-lg` 16
(cards, lists, photos), `--r-pill` (badge, search field, nav indicator).
Size: `--tap` 48 (every touch target, extended with an invisible `::after` where the drawn control
is smaller), `--bar-h` 56, `--nav-h` 64. Elevation: `--shadow` (selected segment), `--shadow-2`
(capture cluster, toasts).
Motion: `--d-1` 90 ms (press), `--d-2` 180 ms (view enter, toast), `--d-3` 260 ms (editor sheet,
viewer); `--ease` `cubic-bezier(0.2, 0.8, 0.2, 1)`. Under `prefers-reduced-motion` all three are
0 and the placeholder shimmer stops.

## Components

| Component | Class / element | Notes |
| --- | --- | --- |
| Button, secondary | `button`, `.button` | surface, hairline edge, 48 high, icon 20 + label; presses scale to 0.97 on `--sunk` |
| Button, primary | `.primary` | amber fill, ink label; one per screen (Save) |
| Button, ghost | `.ghost`, `button.link` | no fill (Cancel, Discard it, the pager's ‹ ›) |
| Button, danger | `.danger` | red label, never filled |
| Tile | `.tile` | icon over a short label on `--sunk`, 72 high; the capture actions Camera, Gallery and Note, three equal columns |
| Toolbar | `.tools` | equal icon-over-label tiles: page actions (sticky above the nav), viewer tools |
| Segmented control | `.chips` (radio group) | the editor's kind (`.kinds`: Note, Todo, Read, Board, Doc: short labels so all five fit one row from 320 px, with the full names Whiteboard and Document as the radios' accessible names and titles) the search screen's fixed kind row (`.kindrow`: All, Notes, Todos, Reads, Boards, Docs; one tap sets or clears `kind:`) and the Tags screen's order (`.filters`); selected = raised surface, amber icon |
| Top bar | `header` | wordmark with the scrap mark; the queue badge on the right |
| Badge | `.badge`, `.badge.failed` | pill with a status dot: amber waiting, red failed |
| Bottom nav | `nav` | icon over label; active item gets an amber-soft pill and ink label |
| List group | `.list` | rows in one rounded card; `.pending` is dashed (still on the phone) |
| List row | `.list li` | 48 thumbnail or kind icon, title, date and kind chip; actions under it |
| Swipe row | `.list li.swipe`, `.row-under` | follows the finger; behind it Edit on `--accent-soft` (right) or Delete on `--danger-soft` (left); past the threshold the icon grows (Edit turns `--accent`) and letting go does it |
| Fold | `.claude-text` (`details`) | hairline above, a chevron before the heading: right folded, down open |
| Pager | `.pager` | a page opened from a list: ‹ "3 of 23 · Recent" ›; the page follows a sideways swipe and slides off to the next |
| Kind chip | `.list em` | amber-soft pill: "todo", "read", or the status that ends one: "done", "cancelled" |
| Due line | `.list .due`, `.todoline`, `.todoedit` | a todo's priority and due date in words ("high · due 3 Nov") after its chip, `--ink-2`; overdue (`.late`: due before today, not done or cancelled) says "overdue" in `--danger`, semibold: the word carries it, never colour alone. On its page, a pill button under the tags opens `.todoedit` in place: a native date input, **No date** (ghost) and a native priority `select`, then Cancel and Save; the editor shows the same while the kind is Todo |
| Saved views | `.facet` in `.refine` | the Todos screen's **Today**, **Overdue**, **Upcoming**: chips like the facets, `.on` while their filters are the query's (those filters then get no chips of their own) |
| Row tick | `.list .tick` | a todo's or a Read's row: a 48 px toggle (`aria-pressed`, `aria-label` "Done: title") at its end, beside the row's link rather than in it, so tapping it opens nothing; an empty box in `--ink-2`, ticked in `--accent-ink` when done; it slides with the row, and a drag that starts on it swipes the row |
| Thumbnail | `.list img`, `.thumbs img`, `.originals img` | fixed size or 4:3 frame reserved before load, shimmering `--sunk` placeholder |
| Photo strip | `.thumbs` | 84 squares, remove button with a 48 target |
| Field | `input`, `textarea` | surface, strong edge, 2 px accent-ink focus ring |
| Search field | `.field-search` | pill with a search icon |
| Editor sheet | `.editor` | full screen over the keyboard; top bar Cancel / Preview / Save |
| Share menu | `.share-menu` | Share's choice, a popover just above it: **Link**, or the content (**Text** on a page, **Photo** in the viewer), ghost rows on `--surface` with `--shadow-2`; a tap elsewhere, Back or Share again closes it |
| Sort menu | `select.facet.sort` | in the refine row, after Tags: a native `select` drawn as a chip (the phone's own picker opens), choosing the query's `sort:` |
| Tag line | `.tags` | a page's tags under its title, `--sunk` pills that each search for their tag, in one line that scrolls; first an outlined **Tags** pill (tag icon) that edits them |
| Tag editor | `.tagedit`, `.tagform` | the tags as `.facet.on` chips that wrap, each with a ✕ to take it off, then a field that suggests the tags in use (a native `datalist`); on a page, Cancel (ghost) and Save (primary) under it, in place of the tag line; in the editor, under the title; in the composer, under the text (above the photos) |
| Toast | `.toast` | dark slab above what is under the thumb, amber text action |
| Banner | `.conflict`, `.restored` | danger-soft with a red edge; accent-soft info line |
| Empty state | `.empty` (`empty()` in ui.ts) | icon in a `--sunk` circle, a sentence, one action |
| Photo viewer | `.viewer` | `--viewer`; close top right, count pill top centre, tools on an `--overlay` scrim |
| Icons | `icons.ts` | 24 px strokes (1.8), currentColor, `aria-hidden` |
| Markdown | `.md` (page text, Preview) | headings `--t-lg`/`--t-md`; code and a table's head on `--sunk`; a table in a `.table` box with `--line` hairlines that scrolls sideways on its own (the page never does); task boxes in `--accent`; strikethrough, quotes and footnotes in `--ink-2`; a Mermaid `.diagram` in its dark or neutral theme, following the system's |

## States

| State | How it shows |
| --- | --- |
| Pressed | scale 0.97 over `--d-1` and a `--sunk` fill (primary: 6 % darker; tiles: `--accent-soft`); the browser's tap flash is off |
| Focus (keyboard) | 2 px `--accent-ink` outline, 2 px offset; fields draw it inside their edge |
| Selected | segmented: raised `--surface` with `--shadow` and an amber icon; nav: `--accent-soft` pill, ink label, bold |
| Disabled | 50 % opacity (exempt from contrast, and never the only sign: the label says why) |
| Busy | the label reads "Preparing…" and taps are ignored; no dimming, so it stays at full contrast |
| Loading image | the reserved box shimmers between `--sunk` and `--line` until the image loads or fails, then stops |
| Failed | `--danger` text in words, a `--danger-soft` badge; never colour alone |
| Overdue | a todo's due line in `--danger`, semibold, saying "overdue" (AA on `--bg`, `--surface` and `--sunk` in both themes, as `--danger` is checked); back to `--ink-2` once done |

## Layout and breakpoints

- Portrait phones (300 px and up): the default. Under 380 px wide the segmented control drops
  its icons.
- Short screens (under 500 px high, i.e. landscape or a large text size): top bar and nav 48 px,
  and the page toolbar scrolls with the page instead of sticking. Landscape (also 560 px and
  wider): the nav's label sits beside its icon and the capture tiles are 64 high.
- Very narrow (under 300 px: a small phone at its largest text size): the capture cluster
  scrolls with the list instead of covering it, tiles go two by two, labels and list titles
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
badge get a `ButtonText` edge.

## Icons

Sizes: 20 in buttons, 24 in tiles, the nav and list placeholders, 18 in the
segmented control, 16 on a photo's remove button, 52 (in a circle) in empty states.
Icons: camera, image, note, todo (check in a square; Done, and a row's tick, which hides the
check until done), later (bookmark), board (a whiteboard on
its stand), link, file, download,
share, edit, trash, search, close, back, next, fit, retry (also Reopen), offline; the nav's plus and clock are
inline in `index.html`. The app icon (`web/public/icon.svg`, PNGs by `npm run icons`) is the
paper scrap on amber; the header mark is the same scrap in amber.

## What we don't do

- No web font, icon font, CSS framework or component library.
- No colour outside `tokens.css` (the debug panel aside), and no second accent; no gradients
  except the viewer's scrim. High-contrast mode uses the system's colour keywords.
- No colour as the only signal: selection also raises, failure also says so in words.
- No modal dialogs of our own (the browser's `confirm()` stays for destructive questions);
  the share menu is a light-dismiss popover, not a modal.
- No motion longer than 260 ms, no motion that carries meaning, none under reduced motion.
- No touch target under 48 px (the 36 px badge, the 30 px remove button and the 42 px segments
  extend their hit area with an invisible `::after`), no text under 12.75 px, no text pair
  under AA.
- No dimming to mean "busy": opacity would break contrast; the label says it instead.
