# Make your own lists: a contacts directory

scrap has a few kinds of page built in (notes, todos, Later, boards, docs), but most of what you
keep falls into classes of your own: people, recipes, places, gift ideas. You don't need a new
kind for each. A class is a tag, a list is a search for it, and a pin puts the list one tap
away. This guide builds a contacts directory as the worked example; the same steps make any
other list.

## 1. Pick a tag for the class

Choose one top-level tag for the class, and a sub-tag under it for each group you want to see
apart:

| Tag | For |
| --- | --- |
| `person` | everyone you keep a note on |
| `person/family` | family |
| `person/work` | colleagues |

A search for `tag:person` also finds `person/family` and `person/work`, so the top-level tag is
the whole directory and the sub-tags are its sections. Someone can be in two groups: give their
page both sub-tags. Keep each person to one page, titled with their name; the text holds
whatever you want to remember (an address, a birthday, who they work with).

## 2. Add people

Any of these works, and you can mix them:

- **New from the list.** Search for `tag:person/work`. With a tag filter on, the top bar shows
  **New** (a **+** at its right end, as **New todo** is on the Todos screen). Tap it and the
  composer opens with **Tags** already set to *#person/work*. Type the name on the first line
  (it becomes the title), anything else below, and **Save**. The composer closes back onto the
  search, and the new page joins the list once it has uploaded. The same works for a kind:
  on `kind:later`, **New** opens the composer with **Later** chosen.
- **Tag by hand.** On any page, tap **Tags** (or **Add tags**) under the title and add
  `person/family`. In the composer, open the **Tags** line above the text.
- **Let Claude suggest it.** Once the tag is in use on a few pages, Claude's reading of a new
  note (**About this page**) can suggest it. A tag Claude added is drawn dashed; keep it, or take
  it off with **Tags**.
- **A business card.** Tap **Camera** on Capture and photograph the card. Claude reads the text
  on it (**What's in the photo**, then **Text in the photo**), so the name, number and email are
  searchable. Add the `person` tag in the composer's **Tags** line before you save, or on the
  page after.

## 3. Find them

Search for `tag:person` and open **Filters** (the slider at the end of the search box). The
**Group** row sets how the list is laid out:

- **A–Z** puts everyone under their first letter (`group:letter`).
- **Tag** puts them under their sub-tags, *person/family* and *person/work*
  (`group:tag`); someone with both appears in both.

Each choice is written into the query, so you can type it too: `tag:person group:letter`. Add
words to narrow it (`tag:person whitby`), or pick a sub-tag alone (`tag:person/family`).

## 4. Keep the list one tap away

Tap the empty search box: **Pinned** is listed first, then **Recent**. There are three ways to
add to Pinned:

- **From the results.** On a search with results, the count line reads *10 pages · Pin · Copy
  link*. Tap **Pin**. It now says **Pinned**; tap it again to unpin. When the filters on make that
  line too long for the screen, **Pin** and **Copy link** move into a **⋯** at the count.
- **From Recent.** Each search under **Recent** has a pin beside its **✕**. Tap it to pin that
  search.
- **A page.** Open a page, tap **Share**, then **Pin to Search** (**Unpin from Search** once it
  is pinned).

Pinning shows *Pinned* with **Undo**. A pinned search is named after its query, as the filter
chips say it: `tag:person group:letter` becomes *#person · grouped A–Z*.

Pins are kept on a page of their own, titled **Pinned**: a list of links, one per pin. Tap
**Edit pins** beside the **Pinned** heading to open it, then **Edit** to change it. Rename a pin
by changing its link text, reorder by moving its line, take one out by deleting its line:

```markdown
- [People A–Z](/search?q=tag:person%20group:letter)
- [Family](/search?q=tag:person/family%20sort:title)
- [Contacts](/p/contacts)
```

Because Pinned is an ordinary page, your pins are the same on every device, and you can link
to it from other pages.

### Or write an index page

For a list with several views, write one page of search links and pin that instead. A
*Contacts* note might read:

```markdown
The people I keep a note on are tagged #person, with family and work under it.

- [Everyone](/search?q=tag:person%20group:letter)
- [By group](/search?q=tag:person%20group:tag)
- [Family](/search?q=tag:person/family%20sort:title)
- [Work](/search?q=tag:person/work%20sort:title)
```

A link to `/search?q=...` opens the search in place, and Back returns to the page. To get a
search's address, run it and tap **Copy link** on its count line. Then pin the page with
**Share**, **Pin to Search**.

## Other lists

The same recipe, with a different tag:

- **Recipes:** `recipe`, with `recipe/baking` and `recipe/weeknight`; group by **Tag**.
- **Places:** `place`, with `place/eat` and `place/visit`; photograph the menu or the sign.
- **Gift ideas:** `gift`, with a sub-tag per person (`gift/dad`); pin the one you need in
  December.
- **Equipment:** `kit`, with `kit/garden` and `kit/climbing`; a photo of each model plate makes
  the serial number searchable.
