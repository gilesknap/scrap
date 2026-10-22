# 19. Ingest on a Claude seat: `claude -p` with a long-lived token

Date: 2026-10-22

## Status

Accepted. Amends [](0009-claude-ingest-via-messages-api.md): the Messages API stays the default,
and a locked-down `claude -p` is a second backend.

## Context

Ingest needs an `ANTHROPIC_API_KEY` from the Claude Console. Colleagues on a corporate Claude seat
(Team or Enterprise) have no Console account, and a seat does not come with a key. ADR 0009 cut
the first design's `claude -p` backend because it needed the Read tool for images and ran an
agent harness, with unclear terms, beside the service's credentials.

Two things have changed. `claude setup-token` makes a long-lived OAuth token for headless use (CI,
the GitHub Action), so a seat can run Claude Code unattended in a supported way. And `claude -p
--input-format stream-json` takes the image as a base64 content block in the user message, as
the Agent SDK does, so no tool is needed. Verified with Claude Code 2.1.281: with `--tools ""`
the only tool offered is the `StructuredOutput` tool that `--json-schema` adds, the answer comes
back in the result's `structured_output`, and a 2048×1536 JPEG cost about 4900 input tokens, so
it reached the model unscaled and drawing coordinates stay in sent pixels.

## Decision

- `SCRAP_LLM_BACKEND=api|cli`, default `api`. `cli` sends `complete()` to `claude_cli.py`, which
  returns the same `Completion`, so the schema check, sanitiser, `put_derived` and `model_run`
  rows are shared. The run's `request` records the backend.
- **Credential.** `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, in the mode-600
  `ingest.env`. It is passed to the CLI in its environment, never on the command line, and is
  redacted from error text like the API key. Ingest with `cli` but no token or no `claude`
  binary pauses at start (`auth`, until *Resume*) and logs why; no job is claimed.
- **Lock-down, on every call.** No tools (`--tools ""`), no MCP servers (`--strict-mcp-config`
  with an empty config), no settings files (`--setting-sources ""`) or CLAUDE.md, no slash
  commands, no session saved; a throwaway `HOME` and working directory, removed afterwards; our
  system prompt replaces Claude Code's (`--system-prompt`); model, effort and the output schema
  set explicitly. The CLI gets only `PATH`, the token, proxy and CA settings, never the service's
  environment. Its own retries are off (`CLAUDE_CODE_MAX_RETRIES=0`), so the queue does all
  retrying as in ADR 0010; the whole process has 300 s. A call whose start-up message lists any
  tool but `StructuredOutput`, or any MCP server, is discarded.
- **Errors** map onto ADR 0010's classes from the CLI's error kind and HTTP status: login and
  organisation problems and an unknown model are `auth`; `billing_error` is `credit`; rate
  limits, overload, server and connection errors are `outage`; a request timeout is `timeout`;
  a bad request or refusal is `content`; cut-off or unparseable output is `invalid`. **A seat's
  usage limit** (a rejected `rate_limit_event`) is an `outage` that waits for the limit's reset
  time, at most an hour at a time. A run that gives no result at all is `internal`.
- **Budget.** `SCRAP_BUDGET_DAY_USD` counts the CLI's own `total_cost_usd`: what the call would
  cost at API prices, not a charge to anyone. It keeps runaway use in check against the seat's
  limits with no new setting. Prompt caching is off (each photo is sent once).
- **Image.** The CLI is not in the main image. `Dockerfile.claude` builds `FROM` it and adds only
  the CLI's native binary (no Node), pinned and checked against the release's SHA-256: about
  240 MB more. `SCRAP_IMAGE` names that image when `SCRAP_LLM_BACKEND=cli`.

## Consequences

- The token is **seat-wide**: whoever holds it can use the seat for anything, with no spend cap,
  until it expires or is revoked. Keep `ingest.env` mode 600 and out of the repo. `podman
  inspect scrap` shows it in plain text, as it does the API key.
- Calls draw on the same usage limits as the user's own Claude use. A limit hit pauses ingest
  until the reset, and heavy ingest can bring the user's interactive limit closer.
- Users must check their organisation's policy (ask its Claude admin) before using a seat
  unattended; the docs say so.
- What the model saw is our prompt plus Claude Code's framing (its structured-output tool and any
  text it adds), so a CLI run is not a byte-for-byte replay of the API request; `request` holds
  what scrap sent, and the CLI version is pinned.
- Usage and cost are as the CLI reports them; served model, content blocks and usage are stored as
  for the API.
- A published `-claude` image tag is a possible follow-up; for now it is built locally.
