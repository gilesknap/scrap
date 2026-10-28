// DEBUG AID, off by default: a small panel of viewport numbers for a real phone, where the
// on-screen keyboard behaves unlike any emulator. Tap the build id at the bottom of the search
// screen five times to turn it on or off (kept in localStorage), or open scrap with ?debug=1
// (?debug=0 to turn it off: main.ts). The panel itself is
// debugpanel.ts, a chunk loaded only while it is on.
import { kept } from "./api";
export const KEY = "scrap.debug";
let taps = 0;

export function tapBuild() {
  if (++taps < 5) return;
  taps = 0;
  kept(KEY, kept(KEY) === "1" ? "0" : "1");
  location.reload();
}
