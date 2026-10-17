import { test } from "node:test";
import assert from "node:assert/strict";
import { UI0 } from "../deck/geometry";
import { focusLost, lockClasses, scrollFor, SCROLL_GAP, stackTarget } from "./modal";

// заглушка элемента: `closest` знает только затемнение
const el = (dim = false) => ({ closest: (s: string) => (dim && s === ".p2-dim" ? {} : null) });

test("фокус потерян — ни на чём, в закрывшейся плите или на затемнении; увёл сам — не трогать", () => {
  const body = el();
  const inSheet = el();
  const other = el();
  const inside = (e: unknown) => e === inSheet;
  assert.equal(focusLost(null, body, inside), true);
  assert.equal(focusLost(body, body, inside), true);
  assert.equal(focusLost(inSheet, body, inside), true);
  assert.equal(focusLost(el(true), body, inside), true);
  assert.equal(focusLost(other, body, inside), false);
});

test("запертая страница: полоса прокрутки окна была — её место остаётся", () => {
  assert.deepEqual(lockClasses(15), ["p2-lock", "p2-lock-bar"]);
  assert.deepEqual(lockClasses(0), ["p2-lock"]);
});

test("какую плиту видеть после смены экрана или шага", () => {
  assert.equal(stackTarget(UI0), 1);
  assert.equal(stackTarget({ ...UI0, open: "tpl" }), 0);
  assert.equal(stackTarget({ ...UI0, more: true }), 2);
  assert.equal(stackTarget({ ...UI0, screen: "build" }), 2);
  assert.equal(stackTarget({ ...UI0, screen: "result" }), 3);
});

test("страница едет к плите, только если её верх выше окна (с зазором), и не выше начала страницы", () => {
  assert.equal(scrollFor(400, 900), 400 - SCROLL_GAP);
  assert.equal(scrollFor(4, 900), 0);
  assert.equal(scrollFor(900, 900), null);
  assert.equal(scrollFor(1400, 900), null);
});
