# Connect Claude Code in claude-sandbox

Let Claude Code in [claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/) use
scrap.

## scrap on Kubernetes or at DLS

For scrap installed as in [](../tutorials/install-kubernetes.md) or
[](../tutorials/install-dls.md), scrap is at an HTTPS name, so `claude-sandbox.conf` needs no
`local-port` or `allow-ip` line. Add scrap's address as in [](connect-claude-code.md), with a
`headersHelper` and an env file under `~/.config/terminal-config`, which the jail already sees
(see {ref}`mcp-secrets`).

The DLS installer, run on the host, puts the token in that env file (`SCRAP_DLS_MCP_TOKEN`), but
cannot reach the container's own `~/.claude`: inside the container, save the helper as
`~/.claude/scrap-dls-headers.sh` and add the server as `scrap-dls`, as in
{ref}`install-dls-claude`.

Then install the `sc` commands and the skills as in [](connect-claude-code.md).

## scrap on the host

For a scrap running on the host, such as the one from "Try it" in the README on port 8000:

1. On the host, add this line to `~/.config/claude-sandbox.conf`, keeping any lines already in
   it ([details](https://diamondlightsource.github.io/claude-sandbox/how-to/network-egress-jail.html)):

   ```ini
   local-port = 8000
   ```

2. If `~/.config/claude-sandbox.conf` did not exist before, run `claude-sandbox --recreate` in
   each project that already has a container.

3. In the container (`claude-sandbox shell`), add scrap:

   ```
   claude mcp add --transport http --scope user scrap http://localhost:8000/mcp
   claude mcp list
   ```

4. Install the `sc` commands and the skills as in [](connect-claude-code.md).

## scrap on another machine on your LAN

For a trial on your LAN ([](../tutorials/install-lan.md)), use `allow-ip = <that machine's IP
address>` in `~/.config/claude-sandbox.conf` instead of `local-port` (an IP address, not a
hostname), then:

1. On that machine, make scrap listen beyond loopback (`--host 0.0.0.0`, as in
   [](../tutorials/install-lan.md)), add `http://<IP address>:8000` to `SCRAP_PUBLIC_URL`
   (`/mcp` answers only loopback and the addresses listed there) and restart scrap.
2. Run `claude-sandbox --recreate`.
3. Add scrap with `http://<IP address>:8000/mcp`.

## Tokens and Cloudflare Access

For a scrap that needs a bearer token or Cloudflare Access service-token headers, send them with a
`headersHelper` and an env file under `~/.config/terminal-config`, which the jail already sees. See
{ref}`mcp-secrets`.
