---
name: s
description: Index of the user's scrap PKM commands. Use when the user types /s. The real commands are the s- skills (/s-post, /s-summarise, /s-find, /s-todos, /s-tidy, /s-undo), which autocomplete.
argument-hint: <search words>
---

# s

`/s` is only an index; each command is its own skill so it autocompletes:

- `/s-post`: post the previous response verbatim
- `/s-summarise`: summarise the session's learnings and activity into one page
- `/s-find <words>`: search
- `/s-todos`: what to do now
- `/s-tidy <what>`: bulk kind/tag changes
- `/s-undo`: revert a recent change

If the arguments are non-empty, behave as `/s-find` with them as the query. Otherwise list the
commands above in one short message.
