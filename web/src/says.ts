// What a capture holds, said one way on Capture's draft row, the upload queue's rows and Add
// photo's toasts (#403): its text's first line and its photos and files ("2 photos, 1 file").

const count = (n: number, one: string) => (n ? `${n} ${one}${n > 1 ? "s" : ""}` : "");

/** Its photos and files: "2 photos, 1 file", "1 file"; "" for none. */
export function holds(files: { type: string }[]) {
  const photos = files.filter((f) => f.type.startsWith("image/")).length;
  return [count(photos, "photo"), count(files.length - photos, "file")].filter(Boolean).join(", ");
}

/** Its first line of words (not a token placing a file, ⟦image 1⟧, nor a list's marks), then
 * what it holds: "Trip · 2 photos". */
export const says = (text: string | undefined, files: { type: string }[]) =>
  [
    (text ?? "")
      .replace(/⟦[^⟦⟧\n]*⟧/g, "")
      .trim()
      .split("\n")[0]
      .replace(/^[-*#>\s]*(\[.\]\s*)?/, ""),
    holds(files),
  ]
    .filter(Boolean)
    .join(" · ");
