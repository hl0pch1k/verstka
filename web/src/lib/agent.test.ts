import { test } from "node:test";
import assert from "node:assert/strict";
import { agentSummary } from "./agent";
import type { Variant } from "../types";

test("agentSummary: a skipped critic is not named twice («Критик Критик пропущен»)", () => {
  const v = {
    strategy: "structured",
    agent: {
      events: [
        { step: "analyst", message: "Нашёл в тексте 12 слайдов, 2 ряда данных и 2 заказанные диаграммы; нужно 12 слайдов.", slide: null, variant: null },
        { step: "designer", message: "«Итоги года» — столбчатая диаграмма (4 категории).", slide: 1, variant: null },
        { step: "critic", message: "Критик пропущен: слайды собраны по правилам, без модели.", slide: null, variant: null },
      ],
    },
  } as unknown as Variant;
  const critic = agentSummary(v).find((l) => l.step === "Критик");
  assert.equal(critic?.text.replace(/\u00a0/g, " "), "Пропущен: слайды собраны по правилам, без модели");
});
