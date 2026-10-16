import { test } from "node:test";
import assert from "node:assert/strict";
import { diffSigs, morph0, morphCls, morphNext, relMove, sigsKey, type MorphState } from "./morph";

test("подписи частей: изменившиеся, появившиеся и пропавшие; ключ не зависит от порядка", () => {
  assert.deepEqual(diffSigs({ a: "1", b: "2", c: "3" }, { a: "1", b: "x", d: "4" }).sort(), ["b", "c", "d"]);
  assert.deepEqual(diffSigs({ a: "1" }, { a: "1" }), []);
  assert.equal(sigsKey({ a: "1", b: "2" }), sigsKey({ b: "2", a: "1" }));
  assert.ok(sigsKey({ a: "1" }) !== sigsKey({ a: "2" }));
});

test("обновление на месте: гаснет только изменившееся, подмена невидимым, проявление, покой", () => {
  type V = { t: string };
  let s: MorphState<V> = morph0<V>();
  s = morphNext(s, { type: "start", held: { t: "old" }, heldSigs: { tag: "0", why: "a", data: "d" }, changed: ["tag", "why"] });
  assert.equal(s.phase, "out");
  assert.equal(morphCls(s, "tag"), "fx-out");
  assert.equal(morphCls(s, "data"), undefined); // «Данные» не мигают
  // пока гасло, изменилось ещё — гаснет и это (повтор — без новой перерисовки)
  const more = morphNext(s, { type: "more", changed: ["slot", "tag"] });
  assert.deepEqual(more.changed, ["tag", "why", "slot"]);
  assert.equal(morphNext(more, { type: "more", changed: ["tag"] }), more);
  // подмена: на виду новое, изменившееся невидимо; то, что отличается от удержанного, тоже в ходе
  s = morphNext(more, { type: "swap", view: { t: "new" }, sigs: { tag: "1", why: "b", data: "d", slot: "s", note: "n" } });
  assert.deepEqual([s.phase, s.held?.t], ["move", "new"]);
  assert.equal(morphCls(s, "note"), "fx-hold");
  assert.equal(morphCls(s, "data"), undefined);
  s = morphNext(s, { type: "in" });
  assert.equal(morphCls(s, "why"), "fx-in");
  s = morphNext(s, { type: "end" });
  assert.deepEqual([s.phase, s.held, s.changed], [null, null, []]);
  // шаги не по порядку ничего не меняют
  const rest = morph0<V>();
  assert.equal(morphNext(rest, { type: "in" }), rest);
  assert.equal(morphNext(rest, { type: "swap", view: { t: "x" }, sigs: {} }), rest);
  assert.equal(morphNext(rest, { type: "end" }), rest);
});

test("сдвиг вложенного — относительно сдвинутого предка; меньше полпикселя — не сдвиг", () => {
  assert.deepEqual(relMove({ dx: 0, dy: -44 }, null), { dx: 0, dy: -44 });
  assert.equal(relMove({ dx: 0, dy: -44 }, { dx: 0, dy: -44 }), null); // предок уже везёт
  assert.deepEqual(relMove({ dx: 0, dy: -64 }, { dx: 0, dy: -44 }), { dx: 0, dy: -20 });
  assert.equal(relMove({ dx: 0.2, dy: -0.3 }, null), null);
});
