---
name: sc
description: Index of the user's scrap PKM commands. Use when the user types /sc. The real commands are the sc- skills (/sc-post, /sc-summarise, /sc-session, /sc-find, /sc-todos, /sc-tidy, /sc-undo), which autocomplete.
argument-hint: <search words>
---

# sc

`/sc` is only an index; each command is its own skill so it autocompletes:

- `/sc-post`: post the previous response verbatim
- `/sc-summarise`: summarise the current topic (latest activity) into one page
- `/sc-session`: summarise the whole conversation into one page
- `/sc-find <words>`: search
- `/sc-todos`: what to do now
- `/sc-tidy <what>`: bulk kind/tag changes
- `/sc-undo`: revert a recent change

If the arguments are non-empty, behave as `/sc-find` with them as the query. Otherwise list the
commands above in one short message.
