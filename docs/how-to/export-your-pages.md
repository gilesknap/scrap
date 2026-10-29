(export-your-pages)=
# Export your pages

An export is every page as a Markdown file, with its photos and other files beside it, in a
folder you can keep, read anywhere or open as an [Obsidian](https://obsidian.md) vault. Your
text stays yours: what Claude wrote about a page goes in a separate folder, `_claude/`. The
layout is in [](../reference/export-format.md).

An export is a copy to read and keep. It leaves out the trash, a page's revisions and Claude's
call records. To be able to put everything back, take a backup too (`scrap backup`, see
{ref}`api-cli-folders`).

## From the app

1. Open **Settings** (the cog).
2. Under **Store**, tap **Export everything**.

The browser saves `scrap-export-YYYY-MM-DD.zip` (the date is UTC) with its usual download. The
zip is made while it downloads, so a big store starts saving after a few seconds and takes as
long as its photos take to send. Exporting changes nothing in scrap.

## From the command line

On the machine that holds the data:

```sh
scrap export --data-dir /path/to/data ~/scrap-export
```

It writes the same files as the zip into the folder, and prints how many pages it wrote.
Export into a new folder for a clean copy: a second run into the same folder writes every page
again but deletes nothing, so a page deleted since stays there. Where scrap runs in a container,
see [](deploy-kubernetes.md) or [](deploy-single-server.md) for running a `scrap` command against
its data.

## Open it in Obsidian

1. Unzip the export (or use the folder `scrap export` wrote).
2. In Obsidian, **Open folder as vault** and pick that folder.

Each page is `<slug>.md`, so your `[[slug]]` and `[[slug|label]]` links work as they are. A page's
title is its alias, so Obsidian's search and link suggestions find it by title. Tags, dates, a
todo's due date and priority and the rest show as the page's properties, and photos show in the
text. Files a page has but does not show in its text are listed in its `attachments` property,
each a link that opens it.

Obsidian's tags have no spaces: a scrap tag such as `lab meeting` is kept as it is, so the export
reads back unchanged, and Obsidian lists it as a property value rather than a tag. A tag such as
`epics/ibek` is a nested tag there too.

`_claude/<slug>.md` holds Claude's notes on that page: its summary, the tags it added, a board's
write-up or a topic's synthesis, related pages, and for each photo its description, the text it
read and a link to its drawing. Each file says at the top that a model wrote it. The drawings are
`.excalidraw` files in `files/`, which the Excalidraw plugin for Obsidian opens.
