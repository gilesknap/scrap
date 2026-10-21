import { afterEach, expect, it, vi } from "vitest";
import { added, forget, load, MOST, remember } from "../src/searches";

const mem = () => {
  const m = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
  return m;
};
afterEach(() => vi.unstubAllGlobals());

it("puts the newest first, once, at most ten, tidying spaces", () => {
  let list: string[] = [];
  for (const q of ["a", "b", "  a  ", "tag:x  kind:todo", ""]) list = added(list, q);
  expect(list).toEqual(["tag:x kind:todo", "a", "b"]);
  for (let i = 0; i < 20; i++) list = added(list, `q${i}`);
  expect(list).toHaveLength(MOST);
  expect(list[0]).toBe("q19");
});

it("keeps them in localStorage, and forgets one", () => {
  mem();
  remember("fence");
  remember("tag:garden after:1m");
  remember("fence");
  expect(load()).toEqual(["fence", "tag:garden after:1m"]);
  forget("fence");
  expect(load()).toEqual(["tag:garden after:1m"]);
});

it("works without storage: nothing kept, nothing thrown", () => {
  vi.stubGlobal("localStorage", {
    getItem: () => {
      throw new Error("denied");
    },
    setItem: () => {
      throw new Error("full");
    },
    removeItem: () => {
      throw new Error("denied");
    },
  });
  expect(() => remember("x")).not.toThrow();
  expect(load()).toEqual([]);
  const m = mem();
  m.set("scrap.searches", "not json");
  expect(load()).toEqual([]);
  m.set("scrap.searches", JSON.stringify(["ok", 3, null]));
  expect(load()).toEqual(["ok"]);
});
