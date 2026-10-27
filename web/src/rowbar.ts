// The Retry, Split and Discard buttons on a capture that failed to upload (lists.ts's pending
// rows): a chunk of its own, loaded only when a capture has failed.
import { queue } from "./app";
import { h } from "./ui";

export const rowbar = (i: { id: string; files: unknown[]; error?: string }) => {
  // Each waits for an upload in progress (maybe in another tab), so say so.
  const act = (label: string, run: () => Promise<void>, sure = "") =>
    h(
      "button",
      {
        type: "button",
        className: label === "Discard" ? "danger" : "",
        onclick: (e: Event) => {
          if (sure && !confirm(sure)) return;
          const b = e.currentTarget as HTMLButtonElement;
          b.disabled = true;
          b.textContent = "Waiting for upload…";
          void run();
        },
      },
      label,
    );
  const tooBig = i.files.length > 1 && i.error?.startsWith("too large");
  return h(
    "span",
    { className: "rowbar" },
    tooBig
      ? act("Split and retry", () => queue.splitRetry(i.id))
      : act("Retry", () => queue.retry(i.id)),
    act(
      "Discard",
      () => queue.discard(i.id),
      "Discard this capture? It never reached the server, so it will be gone.",
    ),
  );
};
