# 21. Ingest on a Claude seat: `claude -p` with a long-lived token

Date: 2026-10-22

## Status

Accepted. Amends [](0009-claude-ingest-via-messages-api.md): the Messages API stays the default,
and a locked-down `claude -p` is a second backend.

## Context

Ingest needs an `ANTHROPIC_API_KEY` from the Claude Console. Colleagues on a corporate Claude seat
(Team or Enterprise) have no Console account, and a seat does not come with a key. ADR 0009 cut
the first design's `claude -p` backend because it needed the Read tool for images and ran an
agent harness, with unclear terms, beside the service's credentials.

Two things have changed. `claude setup-token` makes a long-lived OAuth token, which Claude Code
documents for CI and other headless use (the GitHub Action); whether an organisation lets a seat
be used that way, unattended, is its own policy, to check with its Claude admin. And `claude -p
--input-format stream-json` takes the image as a base64 content block in the user message, as
the Agent SDK does, so no tool is needed. Verified with Claude Code 2.1.281 against a local fake
of the API (`ANTHROPIC_BASE_URL`): with `--tools ""` the only tool offered is the
`StructuredOutput` tool that `--json-schema` adds, and the answer comes back in the result's
`structured_output`. The CLI does not pass the image block through untouched: for Opus 5.5 it
rescales an image with an edge over 2000 px (2048×1536 became 2000×1500) and adds a text block
telling the model to multiply coordinates by 1.02, which would put drawings in two frames; it
re-encodes a JPEG over about 500 KB, at the same size in pixels; and it drops the block's
`transformations`, so `oversized_image: error` (ADR 0009) does not reach the API.

## Decision

- `SCRAP_LLM_BACKEND=api|cli`, default `api`. `cli` sends `complete()` to `claude_cli.py`, which
  returns the same `Completion`, so the schema check, sanitiser, `put_derived` and `model_run`
  rows are shared. The run's `request` records the backend.
- **Every Claude call takes it, photos and text.** Text enrichment
  ([](0020-text-enrichment.md): tags and summary on capture, save, backfill and *Ask Claude*; related pages on *Ask* and in the nightly `scrap enrich
  --related`) is the same shape of call: one user turn, a schema, no tools, here text only, on
  the text model and effort with its own `max_tokens`, which the CLI gets as `--model`,
  `--effort` and `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. Links are fetched by scrap (`fetch.py`), not by
  the model, so no tool is needed. So everything Claude does in scrap works on a seat, through the
  same lock-down, error classes and pauses; `enrich_run.request` records the backend too, and
  `scrap enrich --related` counts the seat token as the credential.
- **Credential.** `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, in the mode-600
  `ingest.env`. It is passed to the CLI in its environment, never on the command line, and is
  redacted from error text like the API key. Ingest with `cli` but no token or no `claude`
  binary pauses at start (`auth`, until *Resume*) and logs why; no job is claimed.
- **Image size.** With `cli` the photo is sent with a long edge of at most 2000 px (not 2048),
  so the CLI passes it through at the size scrap recorded and drawing coordinates stay in sent
  pixels.
- **Lock-down, on every call.** No tools (`--tools ""`) and tool use refused outright
  (`--permission-mode dontAsk`), no MCP servers (`--strict-mcp-config` with an empty config), no
  settings files (`--setting-sources ""`) or CLAUDE.md, no slash commands, no session saved; a
  throwaway `HOME` and working directory, removed afterwards; our system prompt in place of
  Claude Code's (`--system-prompt`); model, effort and the output schema set explicitly. The CLI
  gets only `PATH`, the token, proxy and CA settings, never the service's environment. Its own
  retries are off (`CLAUDE_CODE_MAX_RETRIES=0`), so the queue does all retrying as in ADR 0010;
  the whole process (and anything it starts) is killed after 540 s, two request timeouts and
  start-up. A run whose start-up (`init`) message lists any tool but `StructuredOutput` or any
  MCP server, or that has no `init` message, is discarded and pauses ingest as `auth` (until
  *Resume*): the photo is not charged for a fault in the set-up.
- **Errors** map onto ADR 0010's classes from the CLI's error kind and HTTP status: login and
  organisation problems and an unknown model are `auth`; `billing_error` is `credit`; rate
  limits, overload, server and connection errors are `outage`; a request timeout (which the CLI
  reports as a `server_error` with no status, so it is tested first) is `timeout`; a bad request
  or refusal is `content`; cut-off or unparseable output is `invalid`; an error kind not yet
  known, or a run that gives no result at all, is `internal`. A run counts as failed if **any**
  request in it failed, even one the CLI went on past: when the API rejects the image, the CLI
  drops it, asks again without it and may report a success, which would describe a photo the
  model never saw. **A seat's usage limit** (a rejected `rate_limit_event`) is an `outage` that
  waits for the limit's reset time, at most an hour at a time. **Overage** (a
  `rate_limit_event` with `isUsingOverage`: past the limit, where calls may be billed for real)
  is a `credit` pause, which waits for *Resume*: an outage would retry by itself every hour and
  could run up a bill, while a person can check the seat's overage setting first. That run's
  answer is not stored; the photo is sent again after *Resume*.
- **Budget.** `SCRAP_BUDGET_DAY_USD` counts the CLI's own `total_cost_usd`: what the call would
  cost at API prices, not a charge to anyone. It keeps runaway use in check against the seat's
  limits with no new setting. But only for a model the CLI knows the list price of
  (`modelUsage[…].costBasis` is `list`): 2.1.281 does not know Haiku or Sonnet 5.5 and guesses
  $2/$10 per million tokens, 20 times Haiku's, so for those scrap's own `PRICES` cost the usage,
  as on the API. Prompt caching is off (each input is sent once).
- **Image.** The CLI is not in the main image. `Dockerfile.claude` builds `FROM` it and adds only
  the CLI's native binary (no Node), pinned and checked against the release's SHA-256: about
  240 MB more. `SCRAP_IMAGE` names that image when `SCRAP_LLM_BACKEND=cli`.

## Consequences

- The token is **seat-wide**: whoever holds it can use the seat for anything, with no spend cap,
  until it expires or is revoked. Keep `ingest.env` mode 600 and out of the repo. `podman
  inspect scrap` shows it in plain text, as it does the API key.
- Calls draw on the same usage limits as the user's own Claude use. A limit hit pauses ingest
  (photos and text enrichment, which share the queue) until the reset, and heavy ingest can
  bring the user's interactive limit closer. Text enrichment adds a call per note or link saved,
  and the nightly related pass one per changed page; `SCRAP_ENRICH=off` keeps a seat to photos.
- Users must check their organisation's policy (ask its Claude admin) before using a seat
  unattended; the docs say so.
- The CLI's request is not the API backend's request, so a CLI run is not a replay of an API
  run. Seen with 2.1.281: the system prompt is prefixed with a billing-header block and an Agent
  SDK line ("You are a Claude agent, built on Anthropic's Claude Agent SDK."); a user message
  describing the environment (the throwaway working directory, platform, kernel, date) is added;
  adaptive thinking and `context_management` are sent; the image may be re-encoded and its
  `transformations` are dropped; and if the model does not call `StructuredOutput`, the CLI makes
  a second request telling it to (`CLAUDE_CODE_MAX_RETRIES` does not cover this), so one claim
  can be two billed requests. `request` holds what scrap sent, and the CLI version is pinned.
- Usage and cost are as the CLI reports them; served model, content blocks and usage are stored as
  for the API. A run killed at the deadline keeps the usage of the requests it got answers to
  (costed from their tokens, as the CLI's own cost never arrived); one killed mid-request
  records none.
- The CLI peaks at about 250 MB of memory beside scrap, so a higher `SCRAP_MEMORY_MAX` (1.5g)
  is advised with `cli`.
- A published `-claude` image tag is a possible follow-up; for now it is built locally.
