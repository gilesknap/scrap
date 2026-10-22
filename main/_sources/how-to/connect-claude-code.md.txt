# Connect a Claude Code session

Claude Code sessions can search, read and write scrap through its MCP server (see
[](../reference/mcp.md)). Nothing is installed on the session's machine: it talks to `/mcp`
over HTTPS on the tailnet.

## 1. Tell scrap its address

`/mcp` answers only requests addressed to loopback or to `SCRAP_PUBLIC_URL`. Put the address
Tailscale Serve gives scrap in `~/.config/scrap/ingest.env` (scrap's own settings), for example:

```
SCRAP_PUBLIC_URL=https://myhost.my-tailnet.ts.net:8446
```

then `systemctl --user restart scrap`. The same address makes the page links the tools return.
Without it a request through Serve gets `421 Invalid Host header`. On Kubernetes set it in the
chart's environment to the ingress host.

## 2. Add the server to Claude Code

On a machine on the tailnet:

```
claude mcp add --transport http --scope user scrap https://myhost.my-tailnet.ts.net:8446/mcp
```

`--scope user` makes it available in every session of that user; leave it out to add it to the
current project only. `claude mcp list` should show `scrap` as connected, and the tools appear as
`mcp__scrap__search`, `mcp__scrap__read`, `mcp__scrap__recent`, `mcp__scrap__todos`,
`mcp__scrap__tags` and `mcp__scrap__write`.

Try it: ask "get my recent photos". Search results say which pages hold images (`image_count`,
and the first image's kind, description and thumbnail URL), and `has:image` or `image:photo`
lists them newest first; see [](../reference/mcp.md).

Check it from a shell without Claude:

```
curl -s https://myhost.my-tailnet.ts.net:8446/mcp \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 3. Post findings with a skill

`skills/scrap-post/SKILL.md` in this repository is a Claude Code skill: "post this to scrap"
makes Claude summarise the useful findings of the conversation into one page, reusing existing
tags and linking related pages, and show you the title and tags before it writes. Copy it to
`~/.claude/skills/scrap-post/SKILL.md` unchanged: it uses the server added in step 2, and
`<SCRAP_URL>` in it is only a placeholder in the hint it gives when the server is missing.

Pages written this way carry a *Written by Claude* badge and the origin the session gave;
`is:claude` lists them. Claude can append to its own pages but never change the text of
yours, nor delete any page. It can change any page's kind and tags ("make these 15 notes
whiteboards"); each such change is a revision you can ask it to list and revert.

Mount scrap only in sessions where reading untrusted text is acceptable: pages may hold
injected instructions, and a session that runs with bypassed permissions could be steered by
them.
