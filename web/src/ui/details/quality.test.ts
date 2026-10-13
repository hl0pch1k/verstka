import { test } from "node:test";
import assert from "node:assert/strict";
import { auditCounts } from "../../lib/auditCounts";
import type { AuditReport, DesignEye, Issue, Variant } from "../../types";
import {
  checkRows, chipsOf, emptyOf, eyeView, fixableIds, fixedCount, fixingLabel, fixLabel, fixLock, fixedText, issueText, minorRows, qTone, qualityGroups,
  qualitySummary, splitIssues, TEMPLATE_GONE_FIX,
} from "./quality";

const I = (id: string, slide: number, severity: Issue["severity"], kind: Issue["kind"] = "deterministic", fix: string | null = null, message = `замечание ${id}`): Issue => ({
  id, slide, check_id: id.split("-")[0], severity, kind, message, bboxes: [], element_ids: [], suggestion: null,
  autofix: fix ? { action: fix, params: {}, description: "" } : null, details: {}, outline_id: null,
});

const ISSUES: Issue[] = [
  I("orphan_opener-10-6", 10, "warn"),
  I("contrast_low-12-1", 12, "info", "deterministic", null, "контраст 3.2:1 у «Площадь» (#8F8F8F на #FCFDFF)"),
  I("design_review-4-0", 4, "warn", "model"),
  I("move_inside-3-2", 3, "warn", "deterministic", "move_inside"),
  I("text_clipped-3-1", 3, "error", "deterministic", "shrink_text"),
  I("deck_coherence-0-9", 0, "warn", "model"),
  I("grid_alignment-5-3", 5, "info", "deterministic", "none"),
];

const audit = (issues: Issue[], over: Partial<AuditReport> = {}): AuditReport => ({
  deck: "", template_id: "t", strategy: "structured", issues, per_slide: {}, iterations: 1, applied_fixes: [], seconds: 1,
  summary: { errors: 1, warnings: 3, infos: 2, model_flags: 2, score: 89, checks_run: ["text_clipped", "contrast_low", "design_review"] },
  ...over,
});

const V = (issues: Issue[]): Variant => ({
  strategy: "structured", outline: { title: "Интеграл", subtitle: null, audience: null, purpose: null, strategy: "structured", language: "ru", facts: [], series: [], tables: [],
    slides: Array.from({ length: 12 }, (_, k) => ({ id: `sl${k + 1}`, kind: "bullets", section: null, headline: `Заголовок ${k + 1}`, subtitle: null, notes: "", fact_refs: [],
      content: { bullets: [], paragraphs: [], items: [], numbers: [], table: null, chart: null, quote: null, quote_author: null, image_hint: null, columns: [] } })) },
  plan: null, audit: audit(issues), run_manifest: null, slides: Array.from({ length: 12 }, (_, k) => `/s/slide-${k + 1}.jpg`), files: {},
});

test("тон замечания: ошибка — красный при любом виде, модель — серый, остальное — предупреждение", () => {
  assert.equal(qTone(ISSUES[4]), "err");
  assert.equal(qTone(ISSUES[2]), "model");
  assert.equal(qTone(ISSUES[0]), "warn");
});

test("список и мелкие заметки: заметки правил (info, не модель) уходят в «Мелкие заметки»", () => {
  const { main, minor } = splitIssues(ISSUES);
  assert.deepEqual(main.map((i) => i.id), ["orphan_opener-10-6", "design_review-4-0", "move_inside-3-2", "text_clipped-3-1", "deck_coherence-0-9"]);
  assert.deepEqual(minor.map((i) => i.id), ["contrast_low-12-1", "grid_alignment-5-3"]);
});

test("сводка: «Есть что поправить», ошибки, предупреждения и замечания модели — по числам отчёта (auditCounts), с правильными окончаниями", () => {
  const s = qualitySummary(89.4, auditCounts(audit(ISSUES))!);
  assert.equal(s.score, 89);
  assert.equal(s.head, "Есть что поправить");
  assert.equal(s.nErr, "1 ошибка");
  assert.equal(s.nWarn, "2 предупреждения");
  assert.equal(s.nModel, "2 замечания модели");
  assert.equal(s.dash, "223.7 251.3");
  // сводка сервера (warnings 3 — с замечанием модели) на числа не влияет
  const clean = qualitySummary(100, auditCounts(audit([I("x-1-1", 1, "warn", "model")]))!);
  assert.equal(clean.head, "Ошибок и предупреждений нет");
  assert.equal(clean.nErr, "0 ошибок");
  assert.equal(clean.nWarn, "0 предупреждений");
  assert.equal(clean.nModel, "1 замечание модели");
});

test("сводка: оценка 0 — у кольца нет дуги (нулевая дуга с круглым концом рисуется точкой)", () => {
  const counts = auditCounts(audit(ISSUES))!;
  assert.equal(qualitySummary(0, counts).dash, null);
  assert.equal(qualitySummary(0.4, counts).dash, null);
  assert.equal(qualitySummary(1, counts).dash, "2.5 251.3");
});

test("чипы: Все, Ошибки, Предупреждения, Исправимые — счёт по списку; выбранный отмечен", () => {
  const chips = chipsOf(splitIssues(ISSUES).main, "warn");
  assert.deepEqual(chips.map((c) => [c.key, c.label, c.n, c.on]), [
    ["all", "Все", 5, false], ["err", "Ошибки", 1, false], ["warn", "Предупреждения", 2, true], ["fix", "Исправимые", 2, false],
  ]);
});

test("группы по слайдам: слайды по порядку, «Вся презентация» последней; текущий слайд отмечен; «Показать» — только у слайдов", () => {
  const v = V(ISSUES);
  const groups = qualityGroups(v, splitIssues(ISSUES).main, "all", 3, new Set(), null);
  assert.deepEqual(groups.map((g) => [g.slide, g.label, g.sub, g.count, g.current]), [
    [3, "Слайд 3", " · Заголовок 3", "2 замечания", true],
    [4, "Слайд 4", " · Заголовок 4", "1 замечание", false],
    [10, "Слайд 10", " · Заголовок 10", "1 замечание", false],
    [0, "Вся презентация", "", "1 замечание", false],
  ]);
  assert.equal(groups[0].aria, "Слайд 3: Заголовок 3 — открыт сейчас");
  assert.ok(/^\/s\/slide-3\.jpg\?v=/.test(groups[0].img ?? ""));
  assert.equal(groups[3].img, null);
  // внутри слайда — по важности: ошибка раньше предупреждения
  assert.deepEqual(groups[0].items.map((i) => [i.id, i.tone, i.label, i.fixable, i.checked]), [
    ["text_clipped-3-1", "err", "Ошибка", true, true], ["move_inside-3-2", "warn", "Предупреждение", true, true],
  ]);
});

test("группы: фильтр, снятые флажки и занятые исправлением", () => {
  const v = V(ISSUES);
  const main = splitIssues(ISSUES).main;
  const fix = qualityGroups(v, main, "fix", 1, new Set(["move_inside-3-2"]), ["text_clipped-3-1"]);
  assert.equal(fix.length, 1);
  assert.deepEqual(fix[0].items.map((i) => [i.id, i.checked, i.busy]), [["text_clipped-3-1", true, true], ["move_inside-3-2", false, false]]);
  const all = qualityGroups(v, main, "fix", 1, new Set(), "all");
  assert.ok(all[0].items.every((i) => i.busy));
  assert.equal(qualityGroups(v, main, "err", 1, new Set(), null).length, 1);
});

test("текст замечания — по-человечески: без кодов цветов, с десятичной запятой", () => {
  const g = qualityGroups(V(ISSUES), [ISSUES[1]], "all", 1, new Set(), null);
  assert.equal(g[0].items[0].msg, "Контраст 3,2:1 у «Площадь»");
});

test("отмеченные и исправимые: по умолчанию отмечено всё исправимое, снятые флажки не считаются", () => {
  const main = splitIssues(ISSUES).main;
  assert.deepEqual(fixableIds(main), ["move_inside-3-2", "text_clipped-3-1"]);
  assert.deepEqual(fixableIds(main, new Set(["move_inside-3-2"])), ["text_clipped-3-1"]);
});

test("подписи исправления: «Исправить отмеченные (N)», ход и итог", () => {
  assert.equal(fixLabel(2), "Исправить отмеченные (2)");
  assert.equal(fixingLabel(1), "Исправляю 1 замечание…");
  assert.equal(fixedText(5), "Исправлено 5 замечаний");
});

test("сколько исправлено: запрошенные замечания, которых в новом отчёте больше нет", () => {
  const after = audit([ISSUES[0], ISSUES[3]]);
  assert.equal(fixedCount(["move_inside-3-2", "text_clipped-3-1"], after), 1);
  assert.equal(fixedCount(["move_inside-3-2"], after), 0);
});

test("пустой список: свой текст для каждого фильтра; «Показать все» — когда замечания есть в других", () => {
  assert.deepEqual(emptyOf("all", 0), { title: "Замечаний нет", text: "Проверка не нашла на слайдах ни ошибок, ни предупреждений.", showAll: false });
  assert.equal(emptyOf("err", 3).title, "Ошибок нет");
  assert.equal(emptyOf("err", 3).showAll, true);
  assert.equal(emptyOf("fix", 2).title, "Исправимых нет");
});

test("мелкие заметки: «Слайд N» или «Все», текст по-человечески, по порядку слайдов", () => {
  const rows = minorRows([ISSUES[1], I("grid_alignment-0-4", 0, "info"), ISSUES[6]]);
  assert.deepEqual(rows.map((r) => r.tag), ["Все", "Слайд 5", "Слайд 12"]);
  assert.equal(rows[2].c, "Контраст 3,2:1 у «Площадь»");
});

test("что проверяется: категории в порядке доски, число запущенных проверок и пометка «моделью»", () => {
  const checks = [
    { id: "text_clipped", title: "Текст обрезан", severity: "error" as const, kind: "deterministic" as const, category: "layout", description: "" },
    { id: "design_review", title: "Взгляд дизайнера (VLM)", severity: "warn" as const, kind: "model" as const, category: "layout", description: "" },
    { id: "contrast_low", title: "Контраст", severity: "warn" as const, kind: "deterministic" as const, category: "template", description: "" },
    { id: "slide_missing", title: "Слайда нет", severity: "error" as const, kind: "deterministic" as const, category: "integrity", description: "" },
  ];
  const rows = checkRows(checks, ["text_clipped", "contrast_low", "design_review"]);
  assert.deepEqual(rows.map((r) => r.b), ["Компоновка", "Соответствие шаблону"]);
  assert.ok(/^ · 2 — .+ · моделью$/.test(rows[0].c));
  assert.ok(/^ · 1 — /.test(rows[1].c));
  assert.ok(!/моделью/.test(rows[1].c));
});

test("взгляд дизайнера: строка итога, пересобранные с «было/стало», оставленные и мелкие", () => {
  const eye: DesignEye = { looked: 12, slides: [
    { outline_id: "sl9", slide: 9, status: "fixed", reason: "вывод поднят под заголовок.", before: "/b.jpg", after: "/a.jpg",
      problems: [{ code: "lost", label: "вывод теряется", severity: "major", where: "низ слайда", evidence: "" }] },
    { outline_id: "sl4", slide: 4, status: "kept", reason: "модель выбрала новую вёрстку только в одном порядке сравнения", before: null, after: null,
      problems: [{ code: "unbalanced", label: "пустоты и перекос композиции", severity: "major", where: "левая половина слайда", evidence: "" }] },
    { outline_id: "sl2", slide: 2, status: "seen", reason: "", before: null, after: null,
      problems: [{ code: "tight", label: "тесно", severity: "minor", where: "", evidence: "" }] },
  ] };
  const view = eyeView(eye, V([]))!;
  assert.ok(view);
  assert.equal(view.line, "посмотрел на 12 слайдов · пересобрал 1 · 1 оставил как было");
  assert.ok(view.intro.startsWith("Модель с компьютерным зрением посмотрела на каждый готовый слайд, как арт-директор"));
  assert.deepEqual(view.fixed.map((f) => [f.slide, f.title, f.text, f.pics?.before, f.why]), [
    [9, "Заголовок 9", "Вывод теряется (низ слайда) — собрал заново.", "/b.jpg", "вывод поднят под заголовок."],
  ]);
  assert.deepEqual(view.kept.map((k) => [k.tag, k.text]), [
    ["Слайд 4", "Пустоты и перекос композиции (левая половина слайда) — пробовал другую вёрстку, оставил прежнюю: модель выбрала новую вёрстку только в одном порядке сравнения."],
  ]);
  assert.deepEqual(view.seen.map((k) => [k.tag, k.text]), [["Слайд 2", "Тесно"]]);
  assert.equal(eyeView({ looked: 0, slides: [] }, V([])), null);
  assert.equal(eyeView(null, V([])), null);
});

test("взгляд дизайнера посмотрел не на все слайды — «посмотрела на N из M слайдов», а не «на каждый»", () => {
  const view = eyeView({ looked: 9, slides: [] }, V([]))!;
  assert.ok(view.intro.startsWith("Модель с компьютерным зрением посмотрела на 9 из 12 готовых слайдов, как арт-директор"), view.intro);
  assert.ok(eyeView({ looked: 1, slides: [] }, V([]))!.intro.includes("посмотрела на 1 из 12 готовых слайдов"));
});

test("«Исправить всё автоматически» — исправимые замечания списка, без мелких заметок (D-4)", () => {
  const issues = [I("contrast_low-3-1", 3, "warn", "deterministic", "recolor"), I("brand-0-2", 0, "info", "deterministic", "recolor"), I("fill-4-3", 4, "error", "deterministic", null)];
  const { main } = splitIssues(issues);
  // заметка о контрасте акцента бренда исправима, но в «Мелких заметках» — «Исправить всё» её не трогает
  assert.deepEqual(fixableIds(main), ["contrast_low-3-1"]);
});

test("исправления выключены, пока идёт работа или шаблона больше нет — тогда с причиной (D-9)", () => {
  assert.deepEqual(fixLock(false, false), { off: false, why: null });
  assert.deepEqual(fixLock(true, false), { off: true, why: null });
  assert.deepEqual(fixLock(false, true), { off: true, why: TEMPLATE_GONE_FIX });
});

test("упавшая проверка в старых отчётах — по-русски, без исключения (D-11)", () => {
  assert.equal(issueText(I("contrast-0-1", 0, "info", "deterministic", null, "проверка contrast упала: KeyError 'slot_7'")), "Проверка не выполнилась — её замечаний в отчёте нет.");
  assert.equal(issueText(I("new-0-1", 0, "info", "deterministic", null, "Проверка «Контраст текста» не выполнилась — её замечаний в отчёте нет")), "Проверка «Контраст текста» не выполнилась — её замечаний в отчёте нет");
});
