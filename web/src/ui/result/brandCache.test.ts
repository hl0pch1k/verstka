import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError } from "../../api";
import type { BrandSpec } from "../../types";
import { BRAND_RETRIES, BRAND_RETRY_MS, brandRetry, makeBrandCache } from "./brandCache";

const spec = { id: "bb1", name: "VK Cloud" } as BrandSpec;

test("брендбук презентации: ответ помнится, «брендбука нет» (404) — тоже, неудача связи — нет", async () => {
  let calls = 0;
  let mode: "ok" | "gone" | "net" = "net";
  const ask = makeBrandCache(async () => {
    calls += 1;
    if (mode === "net") throw new ApiError(0, "Сеть недоступна");
    if (mode === "gone") throw new ApiError(404, "Нет такого брендбука");
    return { brand: spec };
  });
  assert.deepEqual(await ask("bb1", "t1"), { spec: null, final: false });
  mode = "ok";
  assert.deepEqual(await ask("bb1", "t1"), { spec, final: true }); // после неудачи — спросил снова
  assert.deepEqual(await ask("bb1", "t1"), { spec, final: true });
  assert.equal(calls, 2);
  mode = "gone";
  assert.deepEqual(await ask("bb2", "t1"), { spec: null, final: true });
  assert.deepEqual(await ask("bb2", "t1"), { spec: null, final: true });
  assert.equal(calls, 3);
});

test("спросить снова: только после неудачи связи и не больше трёх раз", () => {
  assert.equal(brandRetry({ spec: null, final: false }, 0), BRAND_RETRY_MS);
  assert.equal(brandRetry({ spec: null, final: false }, BRAND_RETRIES), null);
  assert.equal(brandRetry({ spec: null, final: true }, 0), null);
  assert.equal(brandRetry({ spec, final: true }, 0), null);
});
