// The search screen's kind row: All, Notes, Todos, Later, Boards, Docs. On its own, out of
// terms.ts, so the app shell (main.ts, for /recent?kind=) needn't carry the query's helpers.

/** [label, the kind: it sets, every kind: value meaning it (what the server takes), the API's
 * kind] */
export const KIND_ROW: [string, string, string[], string][] = [
  ["Notes", "note", ["note"], "note"],
  ["Todos", "todo", ["todo"], "todo"],
  ["Later", "later", ["later", "read", "consume"], "consume"],
  ["Boards", "board", ["board", "whiteboard"], "whiteboard"],
  ["Docs", "doc", ["doc", "document"], "document"],
];
