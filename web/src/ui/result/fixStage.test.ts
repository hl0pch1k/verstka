import { test } from "node:test";
import assert from "node:assert/strict";
import { FX0, fixStageNext, fxPhase, holdLeft, MIN_MINI, type FxAction, type FxState } from "./fixStage";

const go = (s: FxState, ...as: FxAction[]) => as.reduce(fixStageNext, s);

test("исправление на виду: эскиз сжимается со следующего кадра, держится, разворачивается и снимается", () => {
  const pre = fixStageNext(FX0, { type: "sync", seq: 1, done: false });
  assert.equal(fxPhase(pre, 1), "pre");
  const mini = fixStageNext(pre, { type: "mini", seq: 1, at: 100 });
  assert.equal(fxPhase(mini, 1), "mini");
  // задача кончилась — фаза та же, пока эскиз держит свой минимум и декодируется новое превью
  assert.equal(fixStageNext(mini, { type: "sync", seq: 1, done: true }), mini);
  const post = fixStageNext(mini, { type: "post", seq: 1 });
  assert.equal(fxPhase(post, 1), "post");
  const end = fixStageNext(post, { type: "end", seq: 1 });
  assert.equal(fxPhase(end, 1), null);
  // сыгранное не играется снова
  assert.equal(fixStageNext(end, { type: "sync", seq: 1, done: true }), end);
  assert.equal(fxPhase(fixStageNext(end, { type: "sync", seq: 1, done: false }), 1), null);
});

test("ушли со слайда посреди работы — эскиза нет; вернулись, пока работа идёт, — он сжимается заново", () => {
  const mini = go(FX0, { type: "sync", seq: 1, done: false }, { type: "mini", seq: 1, at: 100 });
  const away = fixStageNext(mini, { type: "sync", seq: null, done: false });
  assert.equal(fxPhase(away, 1), null);
  assert.equal(fxPhase(fixStageNext(away, { type: "sync", seq: 1, done: false }), 1), "pre");
  // вернулись, когда работа уже кончилась, — без движения
  const back = fixStageNext(away, { type: "sync", seq: 1, done: true });
  assert.equal(fxPhase(back, 1), null);
  assert.equal(fixStageNext(back, { type: "sync", seq: 1, done: false }), back);
});

test("кончилось до первого кадра там, где его не видели, — без движения; чужие шаги прежнего запуска не трогают новый", () => {
  assert.equal(fxPhase(fixStageNext(FX0, { type: "sync", seq: 4, done: true }), 4), null);
  const two = go(FX0, { type: "sync", seq: 1, done: false }, { type: "sync", seq: 2, done: false });
  assert.equal(fxPhase(two, 2), "pre");
  assert.equal(fxPhase(two, 1), null);
  assert.equal(fixStageNext(two, { type: "mini", seq: 1, at: 5 }), two);
  assert.equal(fixStageNext(two, { type: "post", seq: 1 }), two);
});

test("сколько эскиз ещё держится: сжатие плюс запас с начала сжатия, не меньше нуля", () => {
  assert.equal(holdLeft("pre", 0, 5000), MIN_MINI);
  assert.equal(holdLeft("mini", 100, 500), MIN_MINI - 400);
  assert.equal(holdLeft("mini", 100, 5000), 0);
});
