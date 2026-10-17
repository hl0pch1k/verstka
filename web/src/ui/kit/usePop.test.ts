import { test } from "node:test";
import assert from "node:assert/strict";
import { blurCloses } from "./usePop";

test("меню закрывается, когда фокус ушёл не в меню и не на кнопку; ушёл из окна — остаётся", () => {
  const inMenu = (n: string) => n === "item";
  const onBtn = (n: string) => n === "btn";
  assert.equal(blurCloses<string>("plate", inMenu, onBtn), true);
  assert.equal(blurCloses<string>("item", inMenu, onBtn), false);
  assert.equal(blurCloses<string>("btn", inMenu, onBtn), false);
  assert.equal(blurCloses<string>(null, inMenu, onBtn), false);
});
