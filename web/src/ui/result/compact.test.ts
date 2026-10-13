import { test } from "node:test";
import assert from "node:assert/strict";
import type { AuditReport, AuditSummary, Generation, Issue, Variant } from "../../types";
import { compactChecks, sourceText } from "./compact";

const audit = (summary: Partial<AuditSummary> = {}, issues: Partial<Issue>[] = []): AuditReport => ({
  deck: "d", template_id: "t1", strategy: "structured", per_slide: {}, iterations: 1, applied_fixes: [], seconds: 1,
  issues: issues.map((i, k) => ({
    id: `i${k}`, slide: 1, check_id: "x", severity: "warn", kind: "deterministic", message: "", bboxes: [], element_ids: [], suggestion: null,
    autofix: null, details: {}, outline_id: null, ...i,
  })),
  summary: { errors: 0, warnings: 0, infos: 0, model_flags: 0, score: 100, checks_run: [], ...summary },
});
const variant = (patch: Partial<Variant> = {}): Variant => ({ strategy: "structured", outline: null, plan: null, audit: null, run_manifest: null, slides: [], files: {}, ...patch });
const gen = (patch: Partial<Generation> = {}): Generation => ({ id: "g1", template_id: "t1", strategies: ["structured"], variants: [], ...patch });
const plain = (s: string) => s.replace(/ /g, " ");

test("итоги проверки: «Ошибок нет · 2 предупреждения» и сверенные числа (G-helper)", () => {
  const v = variant({ audit: audit({ score: 89, figures: { checked: 9 } } as Partial<AuditSummary>, [{ severity: "warn" }, { severity: "warn" }]) });
  const [q, f] = compactChecks(gen(), v, null);
  assert.deepEqual({ ...q, lead: plain(q.lead), rest: plain(q.rest) }, { icon: "check-circle", tone: "ok", lead: "Ошибок нет", rest: " · 2 предупреждения", title: q.title, sheet: "quality" });
  assert.ok(/^Оценка качества 89 из 100/.test(q.title), q.title);
  assert.deepEqual({ icon: f.icon, tone: f.tone, lead: plain(f.lead), rest: f.rest }, { icon: "numbers", tone: "ok", lead: "9 чисел", rest: " сверены с текстом" });
});
test("итоги проверки: ошибка — красный значок; числа не найдены — предупреждение", () => {
  const v = variant({ audit: audit({ score: 70, figures: { checked: 5, unverified: 2 } } as Partial<AuditSummary>, [{ severity: "error" }]) });
  const [q, f] = compactChecks(gen(), v, null);
  assert.equal(q.icon, "alert");
  assert.equal(q.tone, "error");
  assert.equal(plain(q.lead), "1 ошибка");
  assert.equal(f.tone, "warn");
  assert.equal(plain(f.lead + f.rest), "2 числа не найдены в тексте");
});
test("итоги проверки: пункты о качестве открывают «Подробнее» на «Качестве», источник текста — нет", () => {
  const v = variant({ audit: audit({ score: 89, figures: { checked: 9 } } as Partial<AuditSummary>) });
  assert.deepEqual(compactChecks(gen(), v, null).map((x) => [x.icon, x.sheet ?? null]), [["check-circle", "quality"], ["numbers", "quality"], ["book", null]]);
});
test("итоги проверки: без оценки — ни качества, ни чисел; источник остаётся", () => {
  const items = compactChecks(gen(), variant(), null);
  assert.deepEqual(items.map((x) => x.icon), ["book"]);
});
test("источник: агент по статье, по статьям, по своим знаниям", () => {
  const w = { mode: "topic" as const, status: "written" as const, text: "Слайд 1. Титул", source: { title: "Интеграл", url: "u" } };
  assert.equal(sourceText(gen({ writer: w }), null), "Текст написал агент — по статье «Интеграл» в Википедии");
  assert.equal(sourceText(gen({ writer: { ...w, pages: [{ title: "A", url: "a" }, { title: "B", url: "b" }] } }), null),
    "Текст написал агент — по статьям «A» и «B» в Википедии");
  assert.equal(sourceText(gen({ writer: { ...w, source: null } }), null), "Текст написал агент по своим знаниям — проверьте даты и цифры");
});
test("источник: «Улучшить готовую» — исходная презентация; уведомление — его заголовок; иначе — свой текст", () => {
  assert.equal(sourceText(gen({ improved_from: { name: "Итоги квартала.pptx" } }), null), "Текст из презентации «Итоги квартала»");
  assert.equal(sourceText(gen({ improved_from: { name: "old_quarter_report.pptx" } }), null), "Текст из презентации «old quarter report»");
  assert.equal(sourceText(gen(), { title: "Собрано без модели" }), "Собрано без модели");
  assert.equal(sourceText(gen(), null), "Ваш текст — агент разложил его по слайдам");
});
