import { test } from "node:test";
import assert from "node:assert/strict";
import type { AuditReport, Issue } from "../types";
import { auditCounts, issueTone } from "./auditCounts";

const I = (id: string, severity: Issue["severity"], kind: Issue["kind"] = "deterministic"): Issue => ({
  id, slide: 1, check_id: id, severity, kind, message: "", bboxes: [], element_ids: [], suggestion: null, autofix: null, details: {}, outline_id: null,
});

const report = (issues: Issue[], summary: Partial<AuditReport["summary"]> = {}): AuditReport => ({
  deck: "", template_id: "t", strategy: "s", issues, per_slide: {}, iterations: 1, applied_fixes: [], seconds: 1,
  summary: { errors: 9, warnings: 9, infos: 9, model_flags: 9, score: 50, checks_run: [], ...summary },
});

test("тон замечания: ошибка — всегда ошибка, замечание модели — отдельно, остальное — предупреждение или заметка", () => {
  assert.equal(issueTone(I("a", "error")), "err");
  assert.equal(issueTone(I("b", "error", "model")), "err");
  assert.equal(issueTone(I("c", "warn")), "warn");
  assert.equal(issueTone(I("d", "warn", "model")), "model");
  assert.equal(issueTone(I("e", "info", "model")), "model");
  assert.equal(issueTone(I("f", "info")), "info");
});

test("числа проверки — по самим замечаниям, а не по сводке сервера (там замечание модели — ещё и предупреждение)", () => {
  const a = report([I("a", "error"), I("b", "warn"), I("c", "warn", "model"), I("d", "info", "model"), I("e", "info"), I("f", "error", "model")]);
  assert.deepEqual(auditCounts(a), { errors: 2, warnings: 1, model: 2, infos: 1 });
  // каждое замечание посчитано ровно один раз
  const c = auditCounts(a)!;
  assert.equal(c.errors + c.warnings + c.model + c.infos, a.issues.length);
});

test("отчёта нет — чисел нет; пустой отчёт — нули", () => {
  assert.equal(auditCounts(null), null);
  assert.equal(auditCounts(undefined), null);
  assert.deepEqual(auditCounts(report([])), { errors: 0, warnings: 0, model: 0, infos: 0 });
});
