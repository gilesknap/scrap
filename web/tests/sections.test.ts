import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { sections } from "../src/groups";

// The same cases tests/test_section_cases.py holds the server's ordering (store/grouping.py) to
type Case = { group: string; pages: Record<string, unknown>[]; order: string[] };
const data = JSON.parse(readFileSync("../tests/section_cases.json", "utf8")) as {
  today: string;
  cases: Case[];
};

describe("sections match the server's order", () => {
  for (const c of data.cases) {
    it(c.group, () => {
      const items = c.pages.map((p) => ({
        fields: {},
        due: null,
        priority: null,
        updated_at: "2026-10-01T00:00:00Z",
        tags: [],
        ...p,
      })) as never[];
      const how = c.group as "letter" | "type" | "due" | "now";
      const out = sections(how, items, { today: data.today, ranked: false });
      expect(out.flatMap((s) => s.items.map((i) => (i as { title: string }).title))).toEqual(
        c.order,
      );
    });
  }
});
