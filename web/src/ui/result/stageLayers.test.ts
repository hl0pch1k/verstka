import { test } from "node:test";
import assert from "node:assert/strict";
import { pushShot, shotDone, shotReady, type Shot } from "./stageLayers";

const shot = (id: number, src: string, patch: Partial<Shot> = {}): Shot => ({ id, src, alt: src, ready: true, done: true, ...patch });

test("сцена: новое превью ложится сверху и ждёт своей картинки, прежнее лежит под ним", () => {
  const a = [shot(1, "A")];
  const b = pushShot(a, "B", "Слайд 2", 2);
  assert.deepEqual(b, [shot(1, "A"), { id: 2, src: "B", alt: "Слайд 2", ready: false, done: false }]);
  // тот же src — слой тот же, меняется только подпись
  assert.equal(pushShot(a, "A", "A"), a);
  assert.deepEqual(pushShot(a, "A", "Слайд 1", 5), [shot(1, "A", { alt: "Слайд 1" })]);
  // слайдов нет — сцена пустая
  assert.deepEqual(pushShot(a, null, "", 3), []);
  // пустая сцена: первое превью тоже ждёт картинки
  assert.deepEqual(pushShot([], "A", "A", 1), [{ id: 1, src: "A", alt: "A", ready: false, done: false }]);
});

test("сцена: быстрое листание — невидимые слои уходят, проявляющийся остаётся тем же элементом", () => {
  // B проявляется (ready), C ещё грузится: новое превью D снимает только невидимый C
  const ls = [shot(1, "A"), shot(2, "B", { done: false }), shot(3, "C", { ready: false, done: false })];
  const d = pushShot(ls, "D", "D", 4);
  assert.deepEqual(d.map((l) => l.id), [1, 2, 4]);
  assert.equal(d[1], ls[1]);
  // вернулись к слайду, который ещё виден сверху, — новый слой не нужен
  const back = pushShot([shot(1, "A"), shot(2, "B", { ready: false, done: false })], "A", "A", 3);
  assert.deepEqual(back.map((l) => l.id), [1]);
});

test("сцена: картинка готова — слой проявляется; проявился — слои под ним снимаются", () => {
  const ls = [shot(1, "A"), shot(2, "B", { ready: false, done: false })];
  const r = shotReady(ls, 2, false);
  assert.deepEqual(r[1], shot(2, "B", { done: false }));
  assert.equal(r.length, 2);
  // готова сразу (декодирована заранее) — перекрёстное затухание всё равно идёт: под слоем есть прежний слайд
  assert.equal(shotReady(ls, 2, true)[1].done, false);
  // проявился — под ним ничего не нужно
  assert.deepEqual(shotDone(r, 2), [shot(2, "B")]);
  // неизвестный слой — без изменений
  assert.equal(shotDone(r, 9), r);
  assert.equal(shotReady(r, 9, false), r);
});

test("сцена: первое превью, готовое сразу, стоит без затухания; без движения слой готов и проявлен сразу", () => {
  const first = [{ id: 1, src: "A", alt: "A", ready: false, done: false }];
  assert.deepEqual(shotReady(first, 1, true), [shot(1, "A")]);
  // грузилось — проявляется над пустой сценой
  assert.deepEqual(shotReady(first, 1, false), [shot(1, "A", { done: false })]);
  // «уменьшить движение»: затухания нет, прежний слой снимается сразу
  const ls = [shot(1, "A"), shot(2, "B", { ready: false, done: false })];
  assert.deepEqual(shotReady(ls, 2, false, true), [shot(2, "B")]);
});
