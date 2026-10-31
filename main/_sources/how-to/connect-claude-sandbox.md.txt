# Connect Claude Code in claude-sandbox

Let Claude Code in [claude-sandbox](https://diamondlightsource.github.io/claude-sandbox/) use a
scrap running on the host, such as the one from "Try it" in the README on port 8000.

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

## Remote scrap

For a scrap on another machine, use `allow-ip = <that machine's IP address>` in
`~/.config/claude-sandbox.conf` instead of `local-port` (an IP address, not a hostname), then:

1. On that machine, make scrap listen beyond loopback (`--host 0.0.0.0`, as in [](../tutorials/install-lan.md)). An IP address is always accepted as a `Host`; to have page links in Claude's replies use it, also add `http://<IP address>:8000` to `SCRAP_PUBLIC_URL` and restart scrap.
2. Run `claude-sandbox --recreate`.
3. Add scrap with `http://<IP address>:8000/mcp`.

## Tokens and Cloudflare Access

For a scrap that needs a bearer token or Cloudflare Access service-token headers, send them with a
`headersHelper` and an env file under `~/.config/terminal-config`, which the jail already sees. See
{ref}`mcp-secrets`.
