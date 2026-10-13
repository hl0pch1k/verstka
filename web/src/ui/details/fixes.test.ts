import { test } from "node:test";
import assert from "node:assert/strict";
import { appliedRows } from "./fixes";

const slideOf = (id: string) => ({ sl3: 3, sl10: 10 })[id] ?? null;
const tplSlide = (pid: string) => ({ p22: 22 })[pid] ?? null;

test("автоисправления словами: слайд, что сделано, подробность; повтор одного и того же — одной строкой ×N", () => {
  const rows = appliedRows([
    { iteration: 1, action: "condense_text", outline_id: "sl3" },
    { iteration: 1, action: "rematch", outline_id: "sl10", result: "rematch → p22" },
    { iteration: 1, action: "xml", kind: "refont", result: "slide 4: refont" },
    { iteration: 2, action: "xml", kind: "refont", result: "slide 4: refont" },
    { iteration: "eyes", outline_id: "sl3", action: "rematch", result: "kept", rolled_back: true },
  ], slideOf, tplSlide);
  assert.deepEqual(rows.map((r) => [r.slide, r.title, r.extra, r.n, r.pass]), [
    [3, "Сокращён текст", null, 1, "проход 1"],
    [10, "Подобран другой макет", "теперь по образцу слайда 22 шаблона", 1, "проход 1"],
    [4, "Заменён шрифт", null, 2, "проход 1"],
  ]);
});

test("правка на месте говорит сама за себя; без слайда — «Все слайды»", () => {
  const rows = appliedRows([{ iteration: 1, action: "xml", result: "Шрифт заменён на Play" }, { action: "recolor" }], slideOf, tplSlide);
  assert.deepEqual(rows.map((r) => [r.slide, r.title, r.extra, r.pass]), [[null, "Шрифт заменён на Play", null, "проход 1"], [null, "Поправлен цвет", null, null]]);
});

test("попытка, которая ничего не поменяла («skip», «kept»), — не исправление", () => {
  const rows = appliedRows([{ iteration: 1, outline_id: "sl3", action: "rematch", result: "skip" }, { iteration: "eyes", outline_id: "sl3", action: "rematch", result: "kept" }], slideOf, tplSlide);
  assert.deepEqual(rows, []);
});
