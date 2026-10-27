import { queue } from "./app";
import { toast } from "./ui";

/** Refused by the server once it tries (within 10 s): a second toast, "Kept on this phone"
 * (its row says why, with Retry), so a refused capture is never left at "Saved". */
export function refused(ids: string[]) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 10_000);
  stop.signal.addEventListener("abort", () => clearTimeout(timer));
  const look = async () => {
    if (stop.signal.aborted) return;
    const left = (await queue.items()).filter((i) => ids.includes(i.id));
    if (stop.signal.aborted) return; // another look finished while this one waited
    if (left.some((i) => i.failed)) toast("Kept on this phone");
    else if (left.length) return; // still uploading
    stop.abort(); // refused, or uploaded
  };
  document.addEventListener("queuechange", () => void look(), { signal: stop.signal });
  // The send began inside addAll: a refusal may have landed before the listener was on, and
  // would be the last event there is. The queue holds its state, so look once now.
  void look();
}
