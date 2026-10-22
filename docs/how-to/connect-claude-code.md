# Connect a Claude Code session

Claude Code sessions can search, read and write scrap through its MCP server (see
[](../reference/mcp.md)). Nothing is installed on the session's machine: it talks to `/mcp`
over HTTPS on the tailnet.

Before you start you need:

- scrap running and published on your tailnet, so that the machine running Claude Code can open
  it (see [](deploy-single-server.md), "Publish on your tailnet", or {ref}`k8s-tailscale`);
- the Claude Code CLI on that machine;
- optionally, ingest on (`SCRAP_INGEST=on`) if you want Claude to describe photos (see step 2).

## 1. Tell scrap its address

`/mcp` answers only requests addressed to loopback or to `SCRAP_PUBLIC_URL`. Put the address
that Tailscale Serve gives scrap (the `--https` port you chose when you published it; `8446` is
only an example) in `~/.config/scrap/ingest.env`, scrap's own settings file (keep it mode 600;
`install.sh` creates it so), for example:

```
SCRAP_PUBLIC_URL=https://myhost.my-tailnet.ts.net:8446
```

then `systemctl --user restart scrap`. Run both as the dedicated `scrap` user, in a real login
session (`ssh scrap@<host>`, or `sudo machinectl shell scrap@`; see [](deploy-single-server.md)).

The address must be a full URL with the scheme, and must match what clients use, port included:
a request whose `Host` differs gets `421 Invalid Host header`. You can give several addresses,
comma separated; the first makes the page links the tools return. Without it, those links are
bare `/p/<slug>` paths that cannot be clicked.

On Kubernetes the chart has no setting of its own for it: pass it with `extraEnv`, using the
Tailscale operator's address (no port, since it serves on 443):

```yaml
extraEnv:
  - name: SCRAP_PUBLIC_URL
    value: https://scrap.<tailnet>.ts.net
```

## 2. Add the server to Claude Code

On a machine on the tailnet:

```
claude mcp add --transport http --scope user scrap https://myhost.my-tailnet.ts.net:8446/mcp
```

The default scope is `local` (this project, only you); `--scope user` makes it available in all
your projects. Avoid `--scope project`: it writes the tailnet hostname into a `.mcp.json` that
you would commit. `claude mcp list` should show `scrap` as connected. `claude mcp remove scrap`
takes it out again.

The server has ten tools, which appear as `mcp__scrap__search`, `mcp__scrap__read`,
`mcp__scrap__recent`, `mcp__scrap__todos`, `mcp__scrap__tags`, `mcp__scrap__write`,
`mcp__scrap__edit_meta`, `mcp__scrap__rename_tag`, `mcp__scrap__revisions` and
`mcp__scrap__revert`; the Tools table in [](../reference/mcp.md) says what each takes and
returns.

Try it: ask "get my recent photos". Search results say which pages hold images (`image_count`,
and the first image's kind, description and thumbnail URL), and `has:image` or `image:photo`
lists them newest first; see [](../reference/mcp.md). The kind and description are there only
once ingest has read the photo (`SCRAP_INGEST=on`), and the image URLs can be fetched only from
the tailnet (see "Images" in the reference).

Check it from a shell without Claude:

```
curl -si https://myhost.my-tailnet.ts.net:8446/mcp \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

It should print an HTTP `200` status and JSON with ten tools in `result.tools`.

Off the tailnet, or for a quick test, use the SSH tunnel fallback ({ref}`scrap-ssh-tunnel`) and
add `http://127.0.0.1:8790/mcp` instead; loopback needs no `SCRAP_PUBLIC_URL`. A session that
cannot reach the tailnet (a hosted or cloud Claude session, claude.ai) cannot use scrap this way.

### If it does not connect

- `421 Invalid Host header`: the `Host` the client used is not loopback or in `SCRAP_PUBLIC_URL`
  (unset, wrong, or a different port). Fix step 1 and restart scrap.
- `403`: the request carried an `Origin` that is not one of those addresses.
- `claude mcp list` shows `scrap` as failed: the machine is off the tailnet, nothing is
  published at that address, or the tailnet ACL blocks the port. Check the address itself with
  `./deploy/smoke.sh <url>`; see {ref}`scrap-troubleshooting` and the Tailnet ACL section of
  [](deploy-single-server.md).
- It worked and stopped after the address changed (a new `SCRAP_PUBLIC_URL`, another Tailscale
  Serve port, or a move to the Kubernetes ingress): scrap reads `SCRAP_PUBLIC_URL` only at
  startup, so restart it (`systemctl --user restart scrap`; on Kubernetes, `helm upgrade` rolls
  the pod) for the new address to be accepted. Claude Code keeps the URL you registered and does
  not rewrite it, so register the new one: `claude mcp remove scrap`, then the `claude mcp add`
  of step 2 with the new `<url>/mcp` (and the same `--scope`). A restart of scrap alone needs
  nothing in the session: `/mcp` keeps no session state, so the next call just works.
- `413`: a request over 2 MB.
- A tool error such as "only a page written over MCP can be appended to", or a title over 200
  characters, a body over 200 kB or more than 20 tags: the call is refused and nothing is saved.

## 3. Post findings with a skill

`skills/scrap-post/SKILL.md` in this repository is a Claude Code skill: "post this to scrap"
(also `/scrap-post`, "save this to scrap", "put this in scrap" or "write this up in scrap")
makes Claude summarise the useful findings of the conversation into one page, reusing existing
tags and linking related pages, and show you the title and tags before it writes; say "just
post" to skip the question. Copy it to `~/.claude/skills/scrap-post/SKILL.md` (for all your
projects) or `.claude/skills/scrap-post/SKILL.md` in a repository (for that project)
unchanged: it uses the server added in step 2. Both uses of `<SCRAP_URL>` in it are
placeholders (the hint it gives when the tools are missing, and the shape of the page URL it
reports); the real URL comes from the `write` tool, built from `SCRAP_PUBLIC_URL`.

The page has a fixed layout: a one-line summary, then Findings, Decisions, Details and Open
questions. It is a `note` unless it is a task (`todo`) or a longer reference (`doc`), carries
the repository and date as its origin, and is sent with a random `key` so that a retry does not
post twice. The skill tells Claude to leave out secrets, credentials and private data. It
appends to an earlier page only if that page was written by Claude (`written_by_claude` in
`read`); otherwise it links to your page.

Pages written this way carry a *Written by Claude* badge and the origin the session gave;
`is:claude` lists them. Claude never deletes a page. It can change any page's kind and tags
("make these 15 notes whiteboards", with `edit_meta`); each such change is a revision you can
ask it to list (`revisions`) and undo (`revert`). It can also edit the text of a page you name
("fix the typo in my trip notes", with `edit_page`): it replaces one passage it quotes exactly,
shows you a diff first if you ask, and refuses if the page changed since it read it. Each text
edit is a revision too, which `revert_text` undoes, and `is:claude-edited` finds the pages whose
text it changed. A bulk change
given as a search is refused if it finds more than 50 pages unless `limit` is raised (up to
200; naming the pages takes up to 200 as well), and Claude is told to try `dry_run` first. See "Kinds and tags" in [](../reference/mcp.md).

## Permissions and security

Claude Code asks before using an MCP tool unless you allow it, and the skill allows none. You
might allow the read tools (`mcp__scrap__search`, `read`, `recent`, `todos`, `tags`) and let
`write`, `edit_meta` and the rest keep asking.

To keep Claude off the text of your pages, set `SCRAP_MCP_CONTENT_EDIT=0` on the server
(`edit_page` and `revert_text` are then not offered at all), or deny the two tools in one
client's settings: `"permissions": {"deny": ["mcp__scrap__edit_page",
"mcp__scrap__revert_text"]}`.

scrap has no login: any device on the tailnet that can reach the port can use `/mcp`, so
restrict that with the tailnet ACL (see [](deploy-single-server.md)).

Mount scrap only in sessions where reading untrusted text is acceptable: pages may hold
injected instructions, and a session that runs with bypassed permissions could be steered by
them.
