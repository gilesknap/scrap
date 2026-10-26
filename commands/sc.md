---
description: Search scrap, or list the scrap commands
argument-hint: <search words>
---

`/sc` is only an index; each command is its own command so it autocompletes:

- `/sc-post`: post the previous response verbatim
- `/sc-summarise [all]`: summarise the current topic (latest activity) into one page; `all` for the whole conversation
- `/sc-find <words>`: search
- `/sc-todos`: what to do now
- `/sc-tidy <what>`: bulk kind/tag changes
- `/sc-undo`: revert a recent change (kinds, tags or text)
- `/sc-write <what>`: write one new page from instructions (selective extraction)
- `/sc-answer <question>`: answer a question from scrap only, citing pages
- `/sc-edit <page> <change>`: change a page's text (dry run first)
- `/sc-done <todo>`: tick off a todo
- `/sc-recent [period]`: what changed lately

If the arguments are non-empty, behave as `/sc-find` with them as the query (a page URL is
read, not searched for). Otherwise list the
commands above in one short message.
