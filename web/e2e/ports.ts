// The e2e servers' ports, all from one base (SCRAP_E2E_PORT; CI's shards and a local split
// each give their own): scrap on it, the public site's receiver on base + 100 and the site
// itself (e2e/site.py) on base + 200. The default, 8781, and its +100 and +200 stay clear of
// the bases CONTRIBUTING.md and the pr-cycle skill use side by side (8791-8796, 8801-8806)
// and of theirs.
export const BASE = Number(process.env.SCRAP_E2E_PORT) || 8781;
export const RECEIVER = BASE + 100;
export const SITE = BASE + 200;
