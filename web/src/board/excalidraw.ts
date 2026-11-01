// The lazy chunk's entry: what drawing.ts may call once it has loaded.

// Excalidraw's own reader of a file, as excalidraw.com opens one: the publish mode checks a
// drawing's SVG with it (board.tsx publishSvg), and e2e opens a published drawing with it
export { loadFromBlob } from "@excalidraw/excalidraw";
export { preview, publishSvg } from "./board";
export { openDrawing } from "./viewer";
