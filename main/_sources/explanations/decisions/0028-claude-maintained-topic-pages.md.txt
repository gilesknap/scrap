# 28. Claude-maintained topic pages

Date: 2026-10-25 (#261, migration 13)

## Status

Accepted. Builds on [](0027-claude-write-ups-of-boards-apart-from-the-text.md) (a versioned
write-up kept apart from the text) and [](0020-text-enrichment.md) (the enrich queue, related
pages). Stage 3 of the #104 roadmap ("Claude-written derived pages"), part of scrap as an LLM wiki
with a strict human/LLM split (#263).

## Context

Some things recur across many pages: a tool such as ibek, a family of systems such as RTEMS IOCs.
What the owner knows about one is spread over those pages, and nothing gathers it. Thoth had
entity and concept pages that did, but wrote them into the vault as if they were the owner's.
Here they should stay clearly Claude's: derived, regenerable, cited, and never in the owner's
text.

## Decision

- **A topic is a page with an empty body; the synthesis is its write-up.** A topic is a real
  page, so its slug, search, links, Related and the trash come for free. Its body is the owner's
  notes on the topic (empty at first), which Claude never writes. Claude's synthesis is stored in
  the `writeup` table, so versions, guidance, Regenerate, Restore and the `[[n]]` to `[[slug]]`
  mapping are reused; what was "a board page" for a write-up is now "a board page or a topic"
  (`writeups.shown`, `view`, `SHOWN`).
- **No new page kind.** A marker table, `topic(page_id, key UNIQUE, created_at)`, avoids
  rebuilding `page` for its kind `CHECK`. A topic page's kind is `reference` (chosen, so nothing
  changes it), and `is:topic` finds them.
- **Sources.** `topic_source(topic_id, page_id, added_by, added_at, excluded, changed_at)` holds a
  topic's sources, the synthesis's inputs. The owner taking one out sets `excluded` and queues the
  synthesis again (putting it back undoes that); discovery is shown the excluded ones and never
  adds one back. A source brought back from the trash makes its topics due again. `changed_at` (when it was added
  or excluded) is beyond the issue's sketch: freshness needs it.
- **The trash is the veto.** A topic in the trash keeps its key, so discovery never makes it
  again, and the discovery call is told those keys were rejected. There is no approval step: up to
  5 new topics a pass are made at once.
- **Discovery** (`scrap enrich --topics`, weekly). One Opus call (`SCRAP_VISION_MODEL`) sees a
  compact index of every page (number, title, tags, summary; at most 2,000, the most recently
  changed, as a bound), the existing topics with their sources' numbers, and the rejected keys,
  all quoted. It returns new topics and new sources for existing ones, citing pages only by
  number. A topic needs at least 3 sources, or 2 where it is central to both (Thoth's thresholds,
  asked of the model; scrap enforces 2). Its run is a new `topic_run` row, since it is of no one
  page (`enrich_run.page_id` is required), and `spent_today` counts it in the shared daily budget.
  `--dry-run` still makes the call (it is what is being judged) but writes nothing. A pass that
  stops at a pause or the budget queues no syntheses.
- **Synthesis.** An enrich job of a new reason, `topic`, run by the service's worker, on Opus. It
  sees each source (at most 40) with its title, kind, tags, summary, write-up, images' text and
  text, cut to fit 6,000 characters a source and 60,000 in all, and the owner's notes and
  guidance. It returns a lead and Markdown sections: Overview, Key facts (each cited), How the
  sources relate, Contradictions and open questions. It is due when it has none, its prompt
  version changed (unless the owner restored that version: a Restore is kept), or anything it
  was made from changed since: the topic page, a source added or
  excluded, or a source's text, trash, summary, write-up or photo reading (as the related pass's
  `STALE`; #262 generalises it). The weekly pass queues those due.
- **Never read as text.** A topic page gets no enrich call (tags, summary, task boxes): Ask
  Claude on one makes its synthesis, then its related pages, so Claude never touches its body.
- **Where it counts.** Its summary is the topic page's model summary; its text is indexed for
  search; a matching topic page ranks first; its citations show in Related both ways (`via:
  topic`). The page object has `topics` (the topics a page is a source of) and `topic` (a topic's
  key and sources). `GET /api/topics` and the MCP `topics` tool give the index, grouped by area
  (the top-level tag most common among a topic's sources), with no model call; MCP `read` gives
  a source's topics and a topic's sources, and its synthesis under `by_model`.
- **Migration 13** rebuilds `enrich_job` for its reason `CHECK` (as migrations 11 and 12 did,
  skipping it if the table takes `topic` already) and adds the three tables if missing.

## Consequences

- More leaves the machine, weekly: an index of every page (titles, tags, summaries), and each
  topic's sources in some detail. Discovery is about $0.30 a week for 1,000 pages; a synthesis
  about $0.10 to $0.30. Both come from the shared daily budget.
- A topic is as good as the model's judgement of what recurs. The owner vetoes a topic by
  trashing it, and a source by taking it out; the synthesis is labelled Claude's, versioned, and
  can be steered, regenerated or restored.
- The PWA does not show topics yet: the Topics tab, the topic page and the Topics line on a
  source come next (#261, PR 2). Until then they are read over MCP and the API, and judged
  there.
- The pass runs weekly, Sundays at 04:11, clear of the nightly related pass (03:41) and gc
  (04:30): a systemd timer on the single server (`scrap-enrich-topics.timer`) and a CronJob in
  the chart (`enrichTopics.*`, only with ingest on).
- `scrap gc` does not prune `topic_run` rows (about one a week).
- To roll back to 0.7.x (which refuses schema 13), with scrap stopped, run:

  ```sql
  PRAGMA user_version = 12;
  DELETE FROM enrich_job WHERE reason = 'topic' AND state IN ('queued', 'running');
  DELETE FROM writeup WHERE page_id IN (SELECT page_id FROM topic);
  DELETE FROM writeup_guidance WHERE page_id IN (SELECT page_id FROM topic);
  DELETE FROM chunk WHERE derived_id IS NULL AND ord = 1
    AND page_id IN (SELECT page_id FROM topic);
  DROP TABLE topic_source;
  DROP TABLE topic_run;
  DROP TABLE topic;
  ```

  The `DELETE` of jobs matters because older code would run a `topic` job as a full enrich. The
  topic pages stay, as plain `reference` pages with empty bodies (trash them by hand if wanted);
  their syntheses, guidance and search chunks go with the `DELETE`s, as older code would neither
  show nor index a synthesis for a page that is not a board. Upgrading again is safe, but discovery would make the
  topics again as new pages.
