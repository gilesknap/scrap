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
- **One hero per screen.** Capture: the Photo button. Composer and editor: Save. Page: its
  toolbar. Everything else steps down: secondary (outlined surface), then ghost (text only).
- **Under the thumb.** Capture actions, the page toolbar and the nav sit at the bottom; Cancel,
  Preview and Save sit in the editor's top bar because the keyboard owns the bottom.
- **Icons with words.** Icons help find a control; the word says what it does. Icon-only
  buttons (close, previous/next photo, remove a photo) carry an `aria-label`.
- **Calm states.** Empty, offline and error states are an icon, one plain sentence and at most
  one action. On the capture screen a problem is a quiet inline line, never a whole screen.
- **Dark is designed, not inverted.** Surfaces get lighter as they come forward; amber is a step
  lighter; toasts stay dark slabs in both themes.
- **Motion confirms, never decorates.** 90-260 ms, eased out; none under reduced motion.

## Tokens

Light / dark values. Every text pair is checked against WCAG AA (4.5:1 for text, 3:1 for
control edges) by `web/tests/contrast.test.ts`, which reads `tokens.css` itself.

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

Type: the system UI face (Roboto on Android); 17 px root. `--t-xs` 0.75rem (labels under icons,
chips), `--t-sm` 0.875rem (meta, small buttons), `--t-md` 1rem (body, list titles), `--t-lg`
1.1875rem (wordmark, field titles, Markdown headings), `--t-xl` 1.5rem (page title). Line height
1.5, 1.25 for titles, 1.6 for page text. Weights 500 (controls), 600 (titles, labels), 700
(hero, page title, active nav).

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
| Button, ghost | `.ghost`, `button.link` | no fill (Cancel, Raw text, Discard it) |
| Button, danger | `.danger` | red label, never filled |
| Hero | `.hero` | the capture screen's Photo: amber, 72 high, camera icon |
| Tile | `.tile` | icon over a short label on `--sunk`; the four other capture kinds |
| Toolbar | `.tools` | equal icon-over-label tiles: page actions (sticky above the nav), viewer tools |
| Segmented control | `.chips` (radio group) | Note / Todo / Read later; selected = raised surface, amber icon |
| Top bar | `header` | wordmark with the scrap mark; the queue badge on the right |
| Badge | `.badge`, `.badge.failed` | pill with a status dot: amber waiting, red failed |
| Bottom nav | `nav` | icon over label; active item gets an amber-soft pill and ink label |
| List group | `.list` | rows in one rounded card; `.pending` is dashed (still on the phone) |
| List row | `.list li` | 48 thumbnail or kind icon, title, date and kind chip; actions under it |
| Kind chip | `.list em` | amber-soft pill: "todo", "read later" |
| Thumbnail | `.list img`, `.thumbs img`, `.originals img` | fixed size or 4:3 frame reserved before load, shimmering `--sunk` placeholder |
| Photo strip | `.thumbs` | 84 squares, remove button with a 48 target |
| Field | `input`, `textarea` | surface, strong edge, 2 px accent-ink focus ring |
| Search field | `.field-search` | pill with a search icon |
| Editor sheet | `.editor` | full screen over the keyboard; top bar Cancel / Preview / Save |
| Toast | `.toast` | dark slab below the top bar, amber text action |
| Banner | `.conflict`, `.restored` | danger-soft with a red edge; accent-soft info line |
| Empty state | `.empty` (`empty()` in ui.ts) | icon in a `--sunk` circle, a sentence, one action |
| Photo viewer | `.viewer` | black; close top right, count pill top centre, tools on a bottom scrim |
| Icons | `icons.ts` | 24 px strokes (1.8), currentColor, `aria-hidden` |

Icons: camera, image, note, todo (check in a square), later (bookmark), link, file, download,
share, edit, trash, search, close, back, next, fit, retry, offline; the nav's plus and clock are
inline in `index.html`. The app icon (`web/public/icon.svg`, PNGs by `npm run icons`) is the
paper scrap on amber; the header mark is the same scrap in amber.

## What we don't do

- No web font, icon font, CSS framework or component library.
- No colour outside `tokens.css`, and no second accent; no gradients except the viewer's scrim.
- No colour as the only signal: selection also raises, failure also says so in words.
- No modal dialogs of our own (the browser's `confirm()` stays for destructive questions).
- No motion longer than 260 ms, no motion that carries meaning, none under reduced motion.
- No touch target under 48 px, no text under 12.75 px, no text pair under AA.
