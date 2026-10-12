import { test } from "node:test";
import assert from "node:assert/strict";
import { OF0, ofClasses, ofStep, ofTimer, type OfState } from "./offline";

test("связь есть: полоски на месте, состояние не меняется — тот же объект", () => {
  assert.equal(ofStep(OF0, false), OF0);
});

test("связь пропала: полоски бегут", () => {
  assert.deepEqual(ofStep(OF0, true), { mode: "run", rest: false });
});

test("связь вернулась во время бега: возврат домой (land)", () => {
  assert.deepEqual(ofStep({ mode: "run", rest: false }, false), { mode: "land", rest: false });
});

test("связь снова пропала во время возврата: сначала дом, бег не начинается", () => {
  const land: OfState = { mode: "land", rest: false };
  assert.equal(ofStep(land, true), land);
});

test("возврат доигран (440 мс): покой и кадр отдыха; бег — только после отдыха, с начала цикла", () => {
  const landed = ofTimer({ mode: "land", rest: false });
  assert.deepEqual(landed, { mode: "idle", rest: true });
  assert.equal(ofStep(landed, true), landed);
  const rested = ofTimer(landed);
  assert.deepEqual(rested, { mode: "idle", rest: false });
  assert.deepEqual(ofStep(rested, true), { mode: "run", rest: false });
});

test("классы: без связи — красный бег и строка статуса", () => {
  const c = ofClasses(true, "run");
  assert.equal(c.brand, "p2-brand of-brand p2-offline");
  assert.equal(c.mv, "of-mv p2-lmove");
  assert.equal(c.tr, "of-tr p2-ltrain");
  assert.deepEqual(c.lb, ["p2-lb p2-lb1", "p2-lb p2-lb2", "p2-lb p2-lb3"]);
  assert.equal(c.line, "p2-in");
});

test("классы: возврат — бег на паузе (of-land), цвет уже синий, строка гаснет", () => {
  const c = ofClasses(false, "land");
  assert.equal(c.brand, "p2-brand of-brand of-land");
  assert.equal(c.mv, "of-mv p2-lmove");
  assert.equal(c.line, "of-gone p2-off");
});

test("классы: покой", () => {
  const c = ofClasses(false, "idle");
  assert.equal(c.brand, "p2-brand of-brand");
  assert.equal(c.mv, "of-mv");
  assert.equal(c.tr, "of-tr");
  assert.deepEqual(c.lb, ["p2-lb", "p2-lb", "p2-lb"]);
});
