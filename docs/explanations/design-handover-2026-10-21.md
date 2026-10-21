# Design handover, 2026-10-21

This page hands four pieces of PWA work to Claude Design, to rebuild on `main` in its own pull
requests. Giles built and tried them on a test server from a local branch, `design-polish`,
which will not be merged: the pure-UX parts come to `main` through Design instead of the
normal pull request pipeline. The page is meant to be enough on its own, so Design does not
need the branch: each section says what the change is for, exactly what Giles approved, which
files it touched, which tests existed for it, and the commits to read if the branch is to hand.

It uses the vocabulary of [the PWA's design system](design-system.md) (hero, primary, ghost,
`.facet` chips, the toolbar `.tools`, the pager, toasts). Where this page and the design system
disagree on something below, this page records what Giles approved; update the design system as
each piece lands.

Screenshots of every state described here (light and dark, 360 and 412 px) were taken on the
branch. They are on Giles's machine, not in the repository, and you cannot reach them: ask
Giles to attach the ones you need. Each section names the screens it has.

## Constraints for every change

- **App shell budget.** The app shell (the JavaScript every screen loads) may be at most
  16 kB gzipped (`web/scripts/size.mjs`, checked in CI). At the time of writing (`main` at
  `a0ce9e4`) it is **16300 of 16384 bytes**: 84 bytes are left. Every merge moves it, so
  re-measure before you start (`cd web && npm run build && npm run size`).
  Anything bigger than a few lines goes in a lazy chunk (as `todos.ts`, `todoedit.ts`,
  `pager.ts` and the editor already are), and a change to a shell module should pay for itself.
  On the branch, items 1 to 4 were built mostly inside lazy chunks for this reason; each section
  says which.
- **Touch targets** are 48 px (`--tap`), extended with an invisible `::after` where the drawn
  control is smaller; never under 44 px, the WCAG minimum.
- **Contrast:** WCAG AA in light and dark (4.5:1 for text, 3:1 for control edges), checked by
  `web/tests/contrast.test.ts` and the end-to-end sweep in `web/e2e/view.spec.ts`. Never colour
  alone: a state also says itself in words.
- **Offline first.** Capture never waits on the network (the upload queue in IndexedDB); a list
  that needs the server shows the calm offline state (`problem()` in `ui.ts`); controls that
  need the server say so rather than failing silently. A new feature must not blank the app when
  storage or the network is missing.
- **One sheet.** The search screen's Filters sheet (`dialog.sheet`, opened with `showModal()` in
  `refine.ts`) is the only native modal `<dialog>` and the only bottom sheet. The photo viewer
  (`web/src/viewer.ts`) and the drawing layer (`web/src/board/viewer.ts`) are full-screen
  `role="dialog"` `aria-modal="true"` layers. Menus are light-dismiss popovers (the share menu);
  forms open in place. Don't add another modal or sheet.
- **The query is the source of truth** for any list: a view must survive Back, a reload and a
  shared link.
- **Small pull requests, each reviewed.** One change per pull request, branched from `main`, with
  its tests and its lines in `docs/explanations/design-system.md` and
  `docs/how-to/use-the-pwa.md`; CI green (`npm run check`, vitest, Playwright, the size budget,
  the docs build). Giles merges.

## 1. Mark done leads a todo's toolbar; Download moves into Share

**The problem.** On a todo's page, ticking it off is the action that matters, but Done sat
second in a row of five equal tools (Edit, Done, Download, Share, Delete) and the row was full:
at 360 px every new tool squeezed the labels.

**Approved behaviour.**

- On a todo's or a Read's page (anything with a status), the first tool is **Mark done**, the
  page's hero: `.primary`, `--accent` fill, `--on-accent` label at `--t-sm`, `--r-md` corners,
  and wider than the others (`flex: 1.6 1 auto` where the rest are `1 1 auto`). Its icon is the
  todo check.
- Once done, Mark done is gone and **Reopen** (retry icon, plain, not filled) takes the first
  place. A cancelled one shows both: Mark done (filled), then Reopen (plain).
- Then **Edit** (or Edit draft), **Share** and **Delete** (danger), in that order. Pages with no
  status (notes, boards, docs) have no Mark done or Reopen.
- **Download** leaves the toolbar and becomes the third row of Share's menu: **Link**, **Text**,
  **Download** (the menu's rows are ghost rows on `--surface`; Download is a link styled like
  them; tapping it closes the menu). Where the browser has no `navigator.share` there is no Share
  button, so Download stays in the toolbar in Share's place.
- All tools fit whole: four at 360 px, a cancelled todo's five at 320 px.
- Mark done on a todo opened from the Todos screen moves on to the next todo (item 4); opened
  anywhere else it stays on the page, which then shows Reopen.
- Offline or on error, the tap gives a toast "Not changed: ..." and the button is enabled again.

**Touched.** `web/src/page.ts` (toolbar order and classes), `web/src/status.ts` (`ticks()`
labels the action "Mark done"), `web/src/ui.ts` (`share()` takes an extra element for its menu),
`web/src/style.css` (`.tools > .primary`, `.share-menu :is(button, .button)`, the viewer's copy
of that rule). All in the shell, but small.

**Tests on the branch.** `web/e2e/tick.spec.ts` ("Mark done leads a todo's toolbar, filled and
wider; Download is in Share's menu", and the existing Done/Reopen test), `web/tests/status.test.ts`
("offers Mark done from any status but done, Reopen from done or cancelled").

**Commits.** `525c08e`, `0867e8f` on `design-polish` (the same as `9948f29`, `96a8987` on
`split-mark-done`). Screens (ask Giles): `round3/01-todo-page-mark-done-partial-*.png`,
`round3/02-share-menu-download-*.png`, `round3/03-cancelled-mark-done-reopen-*.png`.

## 2. Recent searches under the empty search box

**The problem.** The same few searches get typed again and again on a phone keyboard, and there
was no Recent screen any more: the empty search box had nothing to offer.

**Approved behaviour.**

- Tapping (focusing) the **empty** search box shows **Recent**: a small `h2.label` heading
  "Recent" with **Clear all** (a `button.link`) at its end, then up to **10** past searches,
  newest first, as one `.list` group (`role="group"`, `aria-label` "Recent searches") between the
  search field and the kind row.
- Each row: a search icon and the query as typed, including its filters (they are the query's
  text, e.g. `kind:todo tag:home`), aligned to the start and cut with … on one line; then a 48 px
  ghost **✕** (`aria-label` "Remove <query>") that forgets that one.
- Tapping a row runs that search (the box gets its text, the list hides, the keyboard goes).
  A tap on the list keeps the box focused until the choice is made (no flicker of the keyboard).
- The list hides as soon as the box has text, and when it loses focus.
- A search is remembered when it is **run**: Enter, opening a result, or the same query left for
  3 s with at least one result. Never per keystroke. Duplicates collapse (the newest wins, spaces
  tidied, case kept); at most 10 kept.
- **On this device only**: `localStorage` key `scrap.searches`, never sent to the server.
- **Empty state:** no history, no Recent block at all (no heading, no placeholder text).
- **No storage** (a private tab, blocked storage): no Recent block, and search works exactly as
  before. Every `localStorage` use in the app goes through one helper that never throws,
  `kept(key, value?)` in `api.ts` (read; set; `null` removes; returns `null` on any error). This
  also fixed a real bug: with storage blocked the app opened to a blank screen, because
  `main.ts` read its debug flag unguarded. Keep that helper even if the Recent design changes.

**Touched.** New lazy chunk `web/src/searches.ts` (the list, `added()`, `load()`,
`remember()`, `forget()`, `attach()`); `web/src/search.ts` (a slot under the field, the three
"run" moments, the chunk loaded on the screen's start); `web/src/api.ts` (`kept()`), and
`app.ts`, `debug.ts`, `ingest.ts`, `main.ts` moved onto it; `web/src/style.css` (`.recents`,
`.recents-top`, `.again`, `.forget`).

**Tests on the branch.** `web/tests/searches.test.ts` (newest first, once, at most ten; kept and
forgotten; works without storage); `web/e2e/unified-recents.spec.ts` ("the empty box shows the
last searches: run again, forget one, clear all", "search works the same when the phone keeps
nothing"). The spec's name sorts it after `smoke.spec.ts` on purpose: smoke wants an empty store.

**Commits.** `e1e33a2`, `df2592e`, `6950156` (start-aligned rows) on `design-polish`; the same as
`28d9a45`, `d006c75`, `34d7fc0` on `split-recents`. Screen (ask Giles): `round3/05-recent-searches-*.png`.

## 3. Due chips, and a done todo keeps its date greyed

**The problem.** Setting a due date meant opening the phone's date picker for what is nearly
always today, tomorrow or next week. And ticking a todo done removed or changed what its due line
said, so the history of when it was due was lost from the row.

**Approved behaviour.**

- Under the **Due** date input (and its ghost **No date**), three `.facet` chips: **Today**,
  **Tomorrow**, **Next week** (seven days on, on the phone's calendar), in a group
  `aria-label` "Due soon" on a line of their own (`.soon`, wrapping). One tap sets the date as if
  picked; the chip matching the date now set is `aria-pressed` (on `--accent-soft`, semibold,
  as in the Filters sheet); picking any other date in the input un-presses them.
- The same field (`todoField`) is used on a todo's page (the in-place form under the tags), in
  the editor while the kind is Todo, and in the composer (item 4).
- A **done or cancelled** todo keeps its due date on its row and page, greyed (`.due.closed`,
  `--ink-3`), said as a date ("due 3 Nov"), never "today" or "overdue", and never counted in the
  Todos tab's count or Now's groups. Open todos are unchanged: `--ink-2`, and "overdue" in
  `--danger`, semibold, when late. Ticking a row updates its line and its chip ("done") in place.

**Touched.** `web/src/todoedit.ts` (lazy chunk: `inDays()`, the chips), `web/src/status.ts`
(`dueOf()` returns the line's class: `due`, `due late` or `due closed`), `web/src/lists.ts`,
`web/src/rows.ts`, `web/src/page.ts` (use that class), `web/src/style.css` (`.todoedit .soon`,
`.list .due.closed`, `.todoline .closed`).

**Tests on the branch.** `web/e2e/todo-fields.spec.ts` ("due date and priority are set and
cleared on a todo's page", "rows show priority and due date, overdue until ticked done", "the
todo views meet AA contrast, in both themes"), `web/tests/status.test.ts` ("says a todo's
priority and due date, overdue only while it is not done"). Check the greyed date with the
contrast tests: `--ink-3` is for captions, so confirm it passes AA where it lands.

**Commits.** `502010e`, `47ae059` on `design-polish` (`3b223ea`, `456b8bd` on
`split-todo-fields`). Screens (ask Giles): `round2/05-todo-form-due-snooze-*.png`,
`round2/02-todos-all-snoozed-done-grey-*.png`.

## 4. The Todos screen: New todo, Done moves on, the composer's due and priority, Snooze's line

**The problem.** The Todos screen (on `main` since #114) answers "what do I do now", but adding a
todo still meant going to Capture and choosing Todo, working through a list meant Done, Back,
open the next one, and the todo form wrapped awkwardly once Snooze joined it.

**Approved behaviour.**

- **New todo** button: the Todos screen's one hero (`.primary`, pill radius, `--shadow-2`, todo
  icon and the words "New todo"), sticky over the list's end just above the nav
  (`bottom: nav height + safe area + --s-3`), at the **bottom left**: at the right it covered the
  row ticks behind it; at the left it covers only titles. It opens the composer with **Todo**
  already chosen (kept even if the text looks like a link, which would otherwise suggest Read).
  Saving closes back onto the Todos list, which fetches again when the upload queue changes, so
  the new todo appears. The Todos screen itself needs the server (offline it shows the calm
  offline state, so no button); if a refetch fails the list stays as it was. If
  the composer chunk can't load, a toast says "Can't open the composer: reload scrap and try
  again". Write "bottom left" in `use-the-pwa.md` when it lands.
- **Done moves on.** Mark done on a todo opened from a Todos list steps to the next todo in that
  list (it slides in as a pager step; the pager reads "3 of 9 · Todos · Now") and shows a toast
  "Done: <title>. Next todo, 3 of 9" with **Undo** for 6 s. Undo sets the old status back and
  returns to that todo. On the last todo it stays on the page, with the toast "Done: that was the
  last in the list" and **Back to list**. Opened from anywhere else (search, a link), Done stays
  on the page. The pager's middle text ("3 of 9 · Todos · Now") became a button back to the list
  (`.pager .up`, `--ink-2`, underlined dotted in `--line-strong`, `aria-label`
  "3 of 9: back to Todos · Now").
- **Composer due and priority.** While the composer's kind is **Todo** and it has **no photos**,
  it shows the same due field (date, No date, Today / Tomorrow / Next week) and priority select
  as a todo's page, above the tags. They are kept in the composer's draft, sent with the capture
  (and with every part when a capture is saved separately), and a due date or priority alone
  makes the draft worth keeping. With photos the kind row is hidden (ingest decides), so these
  are hidden too.
- **Snooze on its own line.** In a todo's page form, **Snooze until** (a date, Tomorrow and Next
  week chips in a group "Snooze for", and ghost **No snooze**) starts a new line under Priority
  instead of wrapping beside it. Only the page's form has Snooze; the editor and composer don't,
  and rows never show a snooze control.

**Touched.** `web/src/todos.ts` (lazy chunk: the button, refetch on `queuechange`),
`web/src/composer.ts` (`compose(files, as)`; the todo field and its draft), `web/src/pager.ts`
(lazy chunk: `done()`, the `.up` button), `web/src/page.ts` (Done hands over to the pager),
`web/src/queue.ts` and `web/src/api.ts` (a capture carries `due` and `priority`; `split()` copies
them to every part), `web/src/todoedit.ts` (the line break before Snooze), `web/src/style.css`
(`.todos .newtodo`, `.pager .up`, `.todoedit .break`).

**Tests on the branch.** `web/e2e/todos.spec.ts` ("New todo opens the composer on Todo, and the
saved todo joins the list", which also sets a due date in the composer; "Done on a todo from the
Todos screen moves on to the next, with Undo and a way back"), `web/e2e/swipe.spec.ts` (the
pager's text is now a button).

**Commits.** On `design-polish`: `9ccf269` (New todo), `ca9cff0` (Done moves on), `a6c15bc`
(composer due and priority), `5595474` (New todo to the left, Snooze's line), and the Todos
screen's wording in `236c208` (Upcoming's count "N due in the next 7 days", empty "Nothing due in
the next 7 days."). On `split-todos-screen`: `ce9f412`, `21bb985`, `6cbbaa7`, `fc4db46`.
Screens (ask Giles): `round2/01-todos-now-newtodo-*.png`, `round2/03-composer-new-todo-*.png`,
`round2/07-done-moves-on-light.png`, `round2/05-todo-form-due-snooze-*.png`.

**Depends on** item 1 for the Mark done button that moves on, and on the snooze data (below)
for the Snooze line. Snooze is **not on `main` yet**: build New todo, Done moves on and the
composer's due and priority now, and the Snooze line only once snooze lands.

## Decided, but not in this handover's scope

These go through normal pull requests, not Design. They are listed so Design doesn't redo them;
build on them once they are on `main`.

- **Page cap** (on `main`, #125): a page holds at most 1 MB of text; the API answers 422 (#62).
  Vault import is not capped.
- **Snooze data:** `snoozed_until` on todos (an additive migration), `is:snoozed`, snoozed todos
  out of Now, Upcoming and the nav count until their day, "· snoozed till 3 Nov" in All. Only the
  form's layout is item 4.
- **Task boxes drive todos:** Markdown task boxes tick in place in view mode (saved at once,
  disabled offline); a Note with boxes is filed as a Todo unless Note is chosen; a row says
  "2 of 5"; all ticked means done, unticking reopens; Mark done ticks no boxes.
- **Upcoming = due from tomorrow to 7 days on** (on the calendar), not "after today".
- **Back leaves Todos:** switching Now, Upcoming and All replaces the history entry rather than
  adding one.
- **Save separately gives every page the kind**, as well as the tags.
- **Filters sheet without due views:** a todo search's Today, Overdue and Upcoming leave the
  Filters sheet (the Todos screen owns them); typed `due:` still works.

Already on `main` (#121, #123), so build on them as they are: the six most used tags as one-tap
chips under Add a tag, ranked by the pages given exactly that tag (`5e8dff8`), and Claude's tags
joining the user's on a photo's first reading.

**Don't build:** Save unlinking a photo whose last embed is deleted. It was dropped; instead gc
will gather orphaned assets into one page per month (#124).

## Later work on the branch, after `6950156`

`design-polish` has two more commits Giles tried on the canary after this page's items. Neither
is on `main` as written.

- **A calmer edit pane** (`86a7ce9`): **UX, for Design.** In the editor and the composer the
  text box keeps at least 60 % of the visible height (a `--vv-h` property that follows the visual
  viewport), however many tags, and the fields scroll as one. The tags, and a todo's due date and
  priority, fold into one summary line each that says what they hold ("Tags 15 · #work
  #garden…", "Due 24 Oct · high"); a tap opens them in place (a native `<details>`, a `fold()`
  helper in the editor chunk). Save is the top bar's one fill, with Cancel and Preview as text
  buttons; the title sits on a rule instead of in a second box; the composer's Camera and Gallery
  are text buttons. Shell unchanged. Its e2e (`web/e2e/tags.spec.ts`) checks the text keeps at
  least 40 % of the visible height with 15 tags and a simulated keyboard, at 360 and 412 px.
  It changes how items 3 and 4's due field is reached in the editor and composer, so build it
  after them or together. Screens (ask Giles): `round4/`.
- **Top tags by direct use** (`e5df617`): the **behaviour** (ranking by direct count, never
  offering a parent used only through its children) is on `main` as `5e8dff8`. Its remaining
  **UX, for Design**: a long top-tag chip is cut at its start ("…/raised-beds", `max-width`
  11rem, the ellipsis first) so the leaf that tells tags apart shows, with the whole tag as its
  `title` and accessible name.
