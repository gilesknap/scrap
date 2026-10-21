// DEBUG AID, off by default: a small panel of viewport numbers for a real phone, where the
// on-screen keyboard behaves unlike any emulator. Tap the build id at the bottom of the search
// screen five times to turn it on or off (kept in localStorage). The panel itself is
// debugpanel.ts, a chunk loaded only while it is on.
export const KEY = "scrap.debug";
let taps = 0;

export function tapBuild() {
  if (++taps < 5) return;
  taps = 0;
  localStorage.setItem(KEY, localStorage.getItem(KEY) === "1" ? "0" : "1");
  location.reload();
}
