import { afterEach, expect, it } from "vitest";
import { kept } from "../src/api";
import { added, forget, load, remember } from "../src/searches";
import { dropStorage, storage } from "./helpers";

afterEach(dropStorage);

it("keeps searches newest first, once each, at most ten", () => {
  expect(added([], "  kind:todo   tag:home ")).toEqual(["kind:todo tag:home"]);
  expect(added(["a", "b"], "b")).toEqual(["b", "a"]); // again: to the top, not twice
  expect(added(["a"], "A")).toEqual(["A", "a"]); // case kept
  expect(added(["a"], "   ")).toEqual(["a"]); // nothing typed: nothing kept
  const ten = Array.from({ length: 10 }, (_, i) => `q${i}`);
  expect(added(ten, "new")).toEqual(["new", ...ten.slice(0, 9)]);
});

it("remembers and forgets on this device", () => {
  const m = storage();
  remember("numbat");
  remember("quoll");
  remember("numbat");
  expect(load()).toEqual(["numbat", "quoll"]);
  forget("numbat");
  expect(load()).toEqual(["quoll"]);
  forget();
  expect(load()).toEqual([]);
  expect(m.has("scrap.searches")).toBe(false); // none kept: no key left behind
  m.set("scrap.searches", "not json");
  expect(load()).toEqual([]);
  m.set("scrap.searches", '{"a":1}');
  expect(load()).toEqual([]);
});

it("works without storage: nothing kept, nothing thrown", () => {
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: () => {
      throw new DOMException("blocked", "SecurityError");
    },
    setItem: () => {
      throw new DOMException("blocked", "SecurityError");
    },
    removeItem: () => {
      throw new DOMException("blocked", "SecurityError");
    },
  };
  expect(() => remember("numbat")).not.toThrow();
  expect(load()).toEqual([]);
  expect(kept("scrap.debug")).toBeNull();
  delete (globalThis as { localStorage?: Storage }).localStorage;
  expect(kept("scrap.debug")).toBeNull(); // no localStorage at all
});
