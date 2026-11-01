// The e2e servers' ports, all from one base (SCRAP_E2E_PORT, 8791 by default; CI's shards
// and a local split each give their own): scrap on it, the public site's receiver on
// base + 100 and the site itself (e2e/site.py) on base + 200.
export const BASE = Number(process.env.SCRAP_E2E_PORT) || 8791;
export const RECEIVER = BASE + 100;
export const SITE = BASE + 200;
