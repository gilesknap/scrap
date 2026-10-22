# 10. Queue error classes: outages pause, charged failures count, spend is capped

Date: 2026-10-19 (design), built 2026-10-20

## Status

Accepted. Supersedes the first design's "retry five times with doubling delays". See also
[](0020-text-enrichment.md): text enrichment uses the same queue pause and the same daily budget.

## Context

Fixed retries burn attempts, and money, during an outage, a bad key or a spent-up credit balance,
failing jobs that were never at fault. A paid API in a personal tool needs a hard ceiling and a way
to tell the owner.

## Decision

- Every failure is classified (`credit`, `auth`, `outage`, `budget`, `timeout`, `invalid`, `content`,
  `image`, `internal`, `crashed`).
- Credit, auth, outage and budget **pause the queue** (`queue_state`): the claimed job is refunded and
  stays queued, so an outage fails nothing. Credit and auth wait for **Resume**; outages back off
  1, 2, 4 ... 60 minutes or follow `retry-after`; budget waits for UTC midnight.
- All other failures are **charged**: `job.failures` +1, retry in 10 minutes (invalid output
  immediately), dead on the third. A job found `running` at start-up is charged as `crashed`, so a
  poison photo cannot crash-loop the service.
- The SDK runs with `max_retries=0` and a 240 s timeout; the queue does all retrying.
- Daily budget `SCRAP_BUDGET_DAY_USD` (default $3) from a price table; the Console spend limit is
  the hard cap. A monthly budget, circuit breaker and rate-limit class were cut as redundant.
- The first pause of an episode POSTs once to `SCRAP_NOTIFY_URL` (e.g. an ntfy topic) with fixed
  text naming only the reason, never titles, OCR or API errors. Error text is redacted for keys.
- The PWA shows each capture's state, a banner with Resume, Retry and per-photo Reprocess.

## Consequences

- Operators must set a notify URL or a pause can go unnoticed.
- The daily budget is one budget for everything that calls the API: `spent_today` sums the cost of
  photo runs (`model_run`) and text runs (`enrich_run`), so text enrichment can use up what photos
  would have had.
- Classification relies on error shapes from provider docs; the credit wording was not provoked
  in testing.
