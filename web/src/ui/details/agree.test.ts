import { test } from "node:test";
import assert from "node:assert/strict";
import { auditCounts } from "../../lib/auditCounts";
import type { Generation, Issue, Variant } from "../../types";
import { qualityCard } from "../result/resultView";
import { GEN } from "./details.fixtures";
import { checkTiles } from "./files";
import { chipsOf, qualitySummary, splitIssues } from "./quality";

const I = (id: string, slide: number, severity: Issue["severity"], kind: Issue["kind"] = "deterministic"): Issue => ({
  id, slide, check_id: id, severity, kind, message: id, bboxes: [], element_ids: [], suggestion: null, autofix: null, details: {}, outline_id: null,
});

// одна презентация: ошибка, два предупреждения правил, замечания модели (предупреждение и заметка), мелкая заметка;
// сводка сервера посчитана по-своему (замечание модели — ещё и предупреждение) и в числа не идёт
const base = GEN.variants[0];
const v: Variant = {
  ...base,
  audit: {
    ...base.audit!,
    issues: [I("e-1", 1, "error"), I("w-2", 2, "warn"), I("w-3", 3, "warn"), I("m-4", 4, "warn", "model"), I("m-0", 0, "info", "model"), I("i-2", 2, "info")],
    summary: { ...base.audit!.summary, errors: 1, warnings: 3, infos: 2, model_flags: 2, score: 71 },
  },
};
const g: Generation = { ...GEN, variants: [v, ...GEN.variants.slice(1)], summary: { ...GEN.summary, structured: { score: 71, errors: 1, warnings: 3 } } };

test("одни числа везде: карточка результата, сводка и чипы «Качества», «Итог проверки» во «Файлах»", () => {
  const counts = auditCounts(v.audit)!;
  assert.deepEqual(counts, { errors: 1, warnings: 2, model: 2, infos: 1 });

  const card = qualityCard(g, v)!;
  const sheet = qualitySummary(71, counts);
  const chips = chipsOf(splitIssues(v.audit!.issues).main, "all");
  const tiles = Object.fromEntries(checkTiles(g, v).tiles.map((t) => [t.label, t.v]));

  // ошибки
  assert.equal(card.verdict, "1 ошибка");
  assert.equal(sheet.nErr, "1 ошибка");
  assert.equal(chips.find((c) => c.key === "err")!.n, 1);
  assert.equal(tiles["Ошибки"], "1");
  // предупреждения (без замечаний модели)
  assert.equal(card.warnings, "2 предупреждения");
  assert.equal(sheet.nWarn, "2 предупреждения");
  assert.equal(chips.find((c) => c.key === "warn")!.n, 2);
  assert.equal(tiles["Предупреждения"], "2");
  // замечания модели: в сводке листа, в «Файлах» («По картинке») и в подсказке карточки
  assert.equal(sheet.nModel, "2 замечания модели");
  assert.equal(tiles["По картинке"], "2");
  assert.ok(card.title.endsWith("1 ошибка, 2 предупреждения, 2 замечания модели"), card.title);
  // мелкие заметки
  assert.equal(tiles["Заметки"], "1");
});
