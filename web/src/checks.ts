// The store's health checks (#262), as the server has them (scrap/store/health.py): each is a
// search term, so the Store health screen (health.ts) lists them with their counts and a tap
// runs the search, and the Filters' chip for one (refine.ts) says it in words. No DOM here.

/** [term, name, what it finds], in the screen's order (GET /api/health has the same). */
export const CHECKS: [term: string, name: string, about: string][] = [
  ["is:orphan", "Orphans", "No links either way, related pages or topic"],
  ["is:untagged", "Untagged", "No tags"],
  ["is:stale", "Stale todos", "Open, not edited for 60 days, not snoozed or due yet"],
  ["is:duplicate", "Duplicates", "A photo or file shared with another page"],
  ["has:dangling", "Dangling links", "A [[link]] to a page that isn't there"],
  ["is:outdated", "Outdated", "Claude's write-up, synthesis or related pages older than the page"],
];

/** A check's name ("Orphans"), by its term; undefined for any other term. */
export const checkName = (term: string) => CHECKS.find(([t]) => t === term)?.[1];

/** The search address that lists a check's pages. */
export const checkSearch = (term: string) => `/search?q=${encodeURIComponent(term)}`;
