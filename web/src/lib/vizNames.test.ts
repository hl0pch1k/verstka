import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { GOAL_VIZ, VIZ_TITLES, vizName, vizNameLower } from "./vizNames";

// тесты идут из web/ (npm test): сервер — на уровень выше
const py = (rel: string) => readFileSync(join(process.cwd(), "..", rel), "utf8");
const block = (src: string, name: string) => src.slice(src.indexOf(`${name}:`), src.indexOf("}", src.indexOf(`${name}:`)));

test("названия графиков — те же, что на сервере (schemas/data.py VIZ_TITLES), одно на вид", () => {
  const b = block(py("verstka/schemas/data.py"), "VIZ_TITLES");
  const server = Object.fromEntries([...b.matchAll(/"(\w+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
  assert.deepEqual(VIZ_TITLES, server);
  assert.equal(vizName("bar"), "Полосы");
  assert.equal(vizName("что-то"), "Диаграмма");
  assert.equal(vizNameLower("line"), "линейный график");
});
test("цель → вид графика — как на сервере (data/goals.py GOAL_VIZ)", () => {
  const b = block(py("verstka/data/goals.py"), "GOAL_VIZ");
  const server = Object.fromEntries([...b.matchAll(/"(\w+)":\s*\("(\w+)"/g)].map((m) => [m[1], m[2]]));
  assert.deepEqual(GOAL_VIZ, server);
});
