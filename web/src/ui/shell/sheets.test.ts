import { test } from "node:test";
import assert from "node:assert/strict";
import { UI0 } from "../deck/geometry";
import { dimClose, layerOpen, oneSheet, openSheets } from "./sheets";

test("плиты поверх колоды — сверху вниз", () => {
  assert.deepEqual(openSheets(UI0), []);
  assert.deepEqual(openSheets({ ...UI0, sect: "tpls", tplPreview: "t1", helper: true }), ["tplPreview", "sect", "helper"]);
  assert.deepEqual(openSheets({ ...UI0, sheet: "template", pattern: 3 }), ["pattern", "sheet"]);
});

test("затемнение закрывает верхнюю плиту", () => {
  assert.equal(dimClose(UI0), null);
  assert.deepEqual(dimClose({ ...UI0, helper: true }), { type: "set", patch: { helper: false } });
  assert.deepEqual(dimClose({ ...UI0, sect: "hist" }), { type: "sect", sect: null });
  assert.deepEqual(dimClose({ ...UI0, sheet: "why", pattern: 2 }), { type: "pattern", n: null });
  assert.deepEqual(dimClose({ ...UI0, sheet: "why" }), { type: "sheet", tab: null });
  // «Удалить шаблон?» закрывается своим затемнением — под ним «Слайды шаблона»
  assert.deepEqual(dimClose({ ...UI0, tplPreview: "t", tplDelete: "t" }), { type: "set", patch: { tplPreview: null } });
});

test("слой открыт — не помощник", () => {
  assert.equal(layerOpen({ ...UI0, helper: true }), false);
  assert.equal(layerOpen({ ...UI0, lightbox: true }), true);
});

test("одна плита поверх колоды: открылся слой — помощник закрывается", () => {
  const was = { ...UI0, helper: true };
  assert.deepEqual(oneSheet(was, { ...was, sheet: "quality" }), [{ type: "set", patch: { helper: false } }]);
});

test("одна плита поверх колоды: открылся помощник — слои закрываются", () => {
  const was = { ...UI0, sect: "hist" as const };
  assert.deepEqual(oneSheet(was, { ...was, helper: true }), [{ type: "sect", sect: null }]);
  const w2 = { ...UI0, sheet: "template" as const, pattern: 2 };
  assert.deepEqual(oneSheet(w2, { ...w2, helper: true }), [{ type: "sheet", tab: null }]);
});

test("ничего нового — ничего не закрывается", () => {
  const s = { ...UI0, helper: true };
  assert.deepEqual(oneSheet(s, s), []);
  assert.deepEqual(oneSheet(UI0, { ...UI0, sect: "tpls" }), []);
  // слой над слоем (просмотр шаблона из раздела) при закрытом помощнике — ничего
  const g = { ...UI0, sect: "tpls" as const };
  assert.deepEqual(oneSheet(g, { ...g, tplPreview: "x" }), []);
});
