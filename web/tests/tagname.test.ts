import { expect, it } from "vitest";
import { matching } from "../src/tagname";

it("matches those starting with the text first (a part after a / counts), then holding it", () => {
  const all = ["home/bedroom", "garden/beds", "flowerbed", "work", "bedding"];
  expect(matching(all, "bed", (t) => t)).toEqual([
    "home/bedroom",
    "garden/beds",
    "bedding",
    "flowerbed",
  ]);
  expect(matching(all, "zzz", (t) => t)).toEqual([]);
  // rows ([tag, count]) keep their order within each kind of match
  const rows: [string, number][] = [
    ["tech/epics/thoth", 4],
    ["tech/epics", 8],
    ["other/epicsish", 1],
  ];
  expect(matching(rows, "epics", ([t]) => t).map(([t]) => t)).toEqual([
    "tech/epics/thoth",
    "tech/epics",
    "other/epicsish",
  ]);
});
