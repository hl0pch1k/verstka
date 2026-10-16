import { test } from "node:test";
import assert from "node:assert/strict";
import { isChunkError, makeLoader } from "./sheetLoad";

test("кусок листа: один запрос на все вызовы; после неудачи — новый запрос", async () => {
  let calls = 0;
  let ok = false;
  const load = makeLoader(async () => {
    calls += 1;
    if (!ok) throw new TypeError("Failed to fetch dynamically imported module: /assets/SheetPanels-abc.js");
    return "кусок";
  });
  const a = load();
  assert.equal(load(), a); // тот же запрос, пока он идёт
  assert.equal(await a.then(() => "ok", () => "не загрузился"), "не загрузился");
  assert.equal(calls, 1);
  ok = true;
  assert.equal(await load(), "кусок"); // неудача не запомнилась
  assert.equal(await load(), "кусок");
  assert.equal(calls, 2); // удача запомнилась
});

test("неудача загрузки куска — не ошибка в нём", () => {
  assert.equal(isChunkError(new TypeError("Failed to fetch dynamically imported module: /assets/SheetPanels-abc.js")), true);
  assert.equal(isChunkError(new TypeError("Importing a module script failed.")), true);
  assert.equal(isChunkError(Object.assign(new Error("x"), { name: "ChunkLoadError" })), true);
  assert.equal(isChunkError(new TypeError("Cannot read properties of undefined (reading 'map')")), false);
  assert.equal(isChunkError(new Error("Minified React error #31")), false);
});
