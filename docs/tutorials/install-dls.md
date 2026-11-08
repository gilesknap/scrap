# Install scrap at DLS

Install scrap in your own namespace on argus, behind your DLS login, with Claude Code connected.
How it works, and the settings: [](../explanations/scrap-at-dls.md).

## 1. Load argus

```
module load argus
```

## 2. Run the installer

```
curl -fsSL https://raw.githubusercontent.com/gilesknap/scrap/main/deploy/install-dls.sh | sh
```

Paste your Claude API key when asked, or press Enter to skip. Save the `/mcp` bearer token it
shows in a password manager.

Check: it prints `scrap <version> is running in namespace <fedid>.`, and `kubectl get pods` shows
the `scrap-…` pod READY `3/3` and `scrap-public-…` `Running`.

## 3. Ask for the DNS names

Raise a request at <https://jira.diamond.ac.uk/servicedesk/customer/portal/2/create/90> for
`scrap-<fedid>.diamond.ac.uk` and `pages-<fedid>.diamond.ac.uk` on the argus ingress for your
namespace.

Check: `getent hosts scrap-<fedid>.diamond.ac.uk` prints an address.

## 4. Open it

On a DLS machine, open `https://scrap-<fedid>.diamond.ac.uk/` and log in with your DLS account.

Check: `claude mcp list` shows `scrap-dls` as connected. In claude-sandbox, first follow
{ref}`install-dls-sandbox`.

## 5. Put it on your phone

**Your phone must be on the DLS VPN.** Without it, the phone cannot reach scrap: no quick capture
with the camera and no sharing from other apps.

1. Join the DLS VPN on your phone.
2. Open `https://scrap-<fedid>.diamond.ac.uk/` in Chrome and log in.
3. Chrome menu, **Add to home screen** (or **Install app**), then **Install**.

Check: in another app (Photos, the browser), **Share** lists scrap. More:
[](../how-to/use-the-pwa.md).
