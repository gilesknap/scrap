# Use scrap on your phone over Tailscale

[Tailscale](https://tailscale.com) gives scrap a private HTTPS address that only your own devices
can open, which is what lets your phone install it as an app ([how to use the PWA](use-the-pwa.md)).
Everything here runs without `sudo`.

## Make a tailnet and add your phone

1. Sign up, free, at <https://login.tailscale.com> with a Google, Microsoft, GitHub or Apple
   account. That account is your tailnet.
2. Open [DNS](https://login.tailscale.com/admin/dns) in the admin console and click **Enable
   HTTPS** (turn on MagicDNS first if it is off).
3. Install the Tailscale app on your phone and sign in with the same account.
4. Open [Keys](https://login.tailscale.com/admin/settings/keys), click **Generate auth key**, and
   leave **Reusable** and **Ephemeral** off. Keep the page open: the key is shown once.

## Put scrap on the tailnet

With scrap running as in "Try it" in the README, paste the key when prompted (it is not echoed or
kept in your shell history):

```
printf 'Tailscale auth key: '; read -rs TS_AUTHKEY; export TS_AUTHKEY
podman run -d --name scrap-ts --network=host -v scrap-ts:/var/lib/tailscale \
  -e TS_AUTHKEY -e TS_HOSTNAME=scrap -e TS_USERSPACE=true -e TS_STATE_DIR=/var/lib/tailscale \
  ghcr.io/tailscale/tailscale
unset TS_AUTHKEY
podman exec scrap-ts tailscale serve --bg --https=443 http://127.0.0.1:8000
podman exec scrap-ts tailscale serve status
```

scrap refuses a request whose `Host` is a name it does not know (`421 Invalid Host header`), so
tell it its address. Stop the container from "Try it" and run it again with
`-e SCRAP_PUBLIC_URL=https://scrap.<tailnet>.ts.net` added (use the address `serve status`
prints; the `scrap-data` volume keeps your pages). See [](../tutorials/install-lan.md) for the
full command.

Open the address it prints, `https://scrap.<tailnet>.ts.net`, in your phone's browser and choose
*Add to Home screen* or *Install app*. The first visit can take a minute while the certificate is
issued. If a device called `scrap` already exists, the new one is `scrap-1`; use the address
`serve status` prints.

The key works once and the volume remembers the login. After a reboot, start scrap again as in
"Try it", then run `podman start scrap-ts`.

```{warning}
Never use `tailscale funnel`: it publishes scrap to the internet.
```

Claude Code on the same computer needs nothing: it keeps using `http://localhost:8000/mcp`.

This is a trial setup for one computer and your phone. For a lasting install that other devices and
Claude Code can use, see [](../tutorials/install-server.md).
