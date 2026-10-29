// What a zip of Markdown holds, read from its central directory alone (nothing unpacked), so
// Settings > Import Markdown can show what Claude would cost before the zip is sent.

export interface ZipCount {
  pages: number; // Markdown pages an import reads
  photos: number; // images among its other files
}

const SIG_END = 0x06054b50; // end of central directory
const SIG_FILE = 0x02014b50; // a central directory entry
const END_MIN = 22;
const END_MAX = END_MIN + 0xffff; // with the longest comment

/** The names of a zip's entries, or null if it is not a zip this can read (ZIP64: a zip that
 * large is over the upload limit anyway). */
export async function zipNames(file: Blob): Promise<string[] | null> {
  const tailSize = Math.min(file.size, END_MAX);
  if (tailSize < END_MIN) return null;
  const tail = new DataView(await file.slice(file.size - tailSize).arrayBuffer());
  let end = -1;
  for (let i = tailSize - END_MIN; i >= 0; i--) {
    if (tail.getUint32(i, true) === SIG_END) {
      end = i;
      break;
    }
  }
  if (end < 0) return null;
  const count = tail.getUint16(end + 10, true);
  const size = tail.getUint32(end + 12, true);
  const offset = tail.getUint32(end + 16, true);
  if (count === 0xffff || offset === 0xffffffff || offset + size > file.size) return null;
  const dir = new DataView(await file.slice(offset, offset + size).arrayBuffer());
  const names: string[] = [];
  const text = new TextDecoder();
  let at = 0;
  for (let n = 0; n < count; n++) {
    if (at + 46 > dir.byteLength || dir.getUint32(at, true) !== SIG_FILE) return null;
    const name = dir.getUint16(at + 28, true);
    const rest = dir.getUint16(at + 30, true) + dir.getUint16(at + 32, true);
    if (at + 46 + name > dir.byteLength) return null;
    names.push(text.decode(new Uint8Array(dir.buffer, dir.byteOffset + at + 46, name)));
    at += 46 + name + rest;
  }
  return names;
}

const HIDDEN = /(?:^|\/)[._][^/]*\//; // in a . or _ folder (.obsidian, _claude): not read
const DRAWING = /\.excalidraw(?:\.md)?$/i;
const STORED = /(?:^|\/)files\/[0-9a-f]{64}/; // a scrap export's file, never a page
const PHOTO = /\.(?:jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i; // the ones Claude reads

/** The pages and photos among a zip's names, as the import counts them. */
export function countNames(names: string[]): ZipCount {
  let pages = 0;
  let photos = 0;
  for (const name of names) {
    if (name.endsWith("/") || HIDDEN.test(name) || DRAWING.test(name)) continue;
    if (/\.md$/i.test(name) && !STORED.test(name)) pages++;
    else if (PHOTO.test(name)) photos++;
  }
  return { pages, photos };
}
