# Use scrap on your phone over Tailscale

[Tailscale Serve](https://tailscale.com/kb/1312/serve) gives scrap an HTTPS address on your
tailnet, which is what lets the phone install it as an app ([](use-the-pwa.md)).

You need [Tailscale](https://tailscale.com/download) on the computer running scrap and on the
phone, both on the same tailnet, with [HTTPS and
MagicDNS](https://tailscale.com/kb/1153/enabling-https) enabled for it.

1. With scrap listening on `127.0.0.1:8000`, as in "Try it" in the README, run on that computer:

   ```
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
   tailscale serve status
   ```

2. Open the address it prints, `https://<host>.<tailnet>.ts.net`, in your phone's browser and
   choose *Add to Home screen* or *Install app*.

Never use `tailscale funnel`: it publishes scrap to the internet.

## Use the same address for Claude Code

Add the address to `SCRAP_PUBLIC_URL` and restart scrap, otherwise `/mcp` answers `421 Invalid
Host header` ([](connect-claude-code.md)). On the same computer, Claude Code can keep using
`http://localhost:8000/mcp`.
