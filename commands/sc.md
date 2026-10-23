---
description: Search scrap, or list the scrap commands
argument-hint: <search words>
---

`/sc` is only an index; each command is its own command so it autocompletes:

- `/sc-post`: post the previous response verbatim
- `/sc-summarise`: summarise the current topic (latest activity) into one page
- `/sc-session`: summarise the whole conversation into one page
- `/sc-find <words>`: search
- `/sc-todos`: what to do now
- `/sc-tidy <what>`: bulk kind/tag changes
- `/sc-undo`: revert a recent change

If the arguments are non-empty, behave as `/sc-find` with them as the query. Otherwise list the
commands above in one short message.
