import { test } from "node:test";
import assert from "node:assert/strict";
import { ringDash } from "../kit/ring";
import type { AgentEvent, AuditReport, AuditSummary, DeckOutline, DesignEye, Generation, Issue, OutlineSlide, Variant } from "../../types";
import {
  agentLines, deckPreset, deckStrip, docLine, docTitle, eyesCard, fileBase, latestWithModel, noteView, qualityCard, remarkCount, rewriteText,
  scoreOf, slidesOf, variantSegs, whyText,
} from "./resultView";

// Данные — как у сохранённой генерации «Интеграл» (workspace/runs/20261008-173516-113d20), сокращённо
const audit = (summary: Partial<AuditSummary> = {}, issues: Partial<Issue>[] = []): AuditReport => ({
  deck: "d", template_id: "t1", strategy: "structured", per_slide: {}, iterations: 1, applied_fixes: [], seconds: 1,
  issues: issues.map((i, k) => ({
    id: `i${k}`, slide: 1, check_id: "x", severity: "warn", kind: "deterministic", message: "", bboxes: [], element_ids: [], suggestion: null,
    autofix: null, details: {}, outline_id: null, ...i,
  })),
  summary: { errors: 0, warnings: 0, infos: 0, model_flags: 0, score: 100, checks_run: [], ...summary },
});
const slide = (headline: string, patch: Partial<OutlineSlide> = {}): OutlineSlide => ({
  id: headline, kind: "bullets", section: null, headline, subtitle: null, notes: "", fact_refs: [],
  content: { bullets: [], paragraphs: [], items: [], numbers: [], table: null, chart: null, quote: null, quote_author: null, image_hint: null, columns: [] },
  ...patch,
});
const outline = (title: string, slides: OutlineSlide[]): DeckOutline => ({
  title, subtitle: null, audience: null, purpose: null, strategy: "structured", language: "ru", slides, facts: [], series: [], tables: [],
});
const variant = (patch: Partial<Variant> = {}): Variant => ({ strategy: "structured", outline: null, plan: null, audit: null, run_manifest: null, slides: [], files: {}, ...patch });
const gen = (patch: Partial<Generation> = {}): Generation => ({ id: "g1", template_id: "t1", strategies: ["structured"], variants: [], ...patch });
const WRITER = {
  mode: "topic" as const, status: "written" as const, text: "Слайд 1. Титульный\nНазвание: «Интеграл».", topic: "сделай презентаицю про интегралы",
  slides: 12, asked: 12, source: { title: "Интеграл", url: "https://ru.wikipedia.org/wiki/Интеграл" },
};
const plain = (s: string | null | undefined) => (s ?? "").replace(/ /g, " ");

test("название: заголовок плана варианта, иначе генерации, иначе «Презентация»", () => {
  const g = gen({ title: "Интеграл: от площади к физике" });
  assert.equal(docTitle(g, variant({ outline: outline("  Интеграл ", []) })), "Интеграл");
  assert.equal(docTitle(g, variant()), "Интеграл: от площади к физике");
  assert.equal(docTitle(gen(), null), "Презентация");
});

test("строка под названием: «шаблон · N слайдов · когда»; пустые части не пишутся", () => {
  assert.equal(docLine("VK Tech", 12, "сегодня, 17:38"), "VK Tech · 12 слайдов · сегодня, 17:38");
  assert.equal(docLine("Кофейня", 3, ""), "Кофейня · 3 слайда");
  assert.equal(docLine("Кофейня", 0, "вчера, 09:05"), "Кофейня · вчера, 09:05");
});

test("число слайдов варианта: картинки, иначе план; без слайдов — 0", () => {
  assert.equal(slidesOf(variant({ slides: ["a", "b"] })), 2);
  assert.equal(slidesOf(variant({ outline: outline("t", [slide("1"), slide("2"), slide("3")]) })), 3);
  assert.equal(slidesOf(variant()), 0);
});

test("кольцо: дуга — доля оценки от окружности r = 19 (119.38)", () => {
  assert.equal(ringDash(89), "106.25 119.38");
  assert.equal(ringDash(100), "119.38 119.38");
  assert.equal(ringDash(140), "119.38 119.38");
  assert.equal(ringDash(-5), "0.00 119.38");
  assert.equal(ringDash(Number.NaN), "0.00 119.38");
});

test("оценка: живой отчёт проверки сильнее меты; у каркаса без текста оценки нет", () => {
  const v = variant({ audit: audit({ score: 89 }) });
  assert.equal(scoreOf(gen({ summary: { structured: { score: 70 } } }), v), 89);
  assert.equal(scoreOf(gen({ summary: { structured: { score: 70 } } }), variant()), 70);
  assert.equal(scoreOf(gen(), variant()), null);
  const skeleton = variant({ audit: audit({ score: 100 }), outline: { ...outline("t", []), planned_by: "skeleton" } });
  assert.equal(scoreOf(gen({ writer: { ...WRITER, status: "failed", text: "" } }), skeleton), null);
});

test("варианты: название сервера и оценка каждого", () => {
  const g = gen({
    strategies: ["structured", "visual"],
    variants: [variant({ audit: audit({ score: 89 }) }), variant({ strategy: "visual", audit: audit({ score: 84.4 }) })],
  });
  const titles: Record<string, string> = { structured: "Структурный", visual: "Визуальный" };
  assert.deepEqual(variantSegs(g, (n) => titles[n] ?? n), [
    { key: "structured", label: "Структурный", score: 89 },
    { key: "visual", label: "Визуальный", score: 84 },
  ]);
});

test("замечания на слайдах: ошибки, предупреждения и замечания модели; мелкие заметки и замечания ко всей презентации — нет", () => {
  const v = variant({
    audit: audit({}, [
      { slide: 2, severity: "warn" },
      { slide: 3, severity: "info", kind: "model" },
      { slide: 3, severity: "info" },
      { slide: 0, severity: "error" },
      { slide: 5, severity: "warn" },
    ]),
  });
  assert.deepEqual(remarkCount(v), { count: 3, errors: false });
  assert.deepEqual(remarkCount(variant({ audit: audit({}, [{ slide: 1, severity: "error" }]) })), { count: 1, errors: true });
  assert.deepEqual(remarkCount(variant()), { count: 0, errors: false });
});

test("карточка «Качество»: кольцо, ошибки и предупреждения, сверенные числа, как считается оценка", () => {
  const v = variant({ audit: audit({ score: 89, errors: 0, warnings: 3, model_flags: 1, figures: { checked: 20, derived: 0, unverified: 0 } }) });
  const q = qualityCard(gen(), v);
  if (!q) throw new Error("карточки нет");
  assert.equal(q.score, 89);
  assert.equal(q.verdict, "Ошибок нет");
  assert.equal(q.warnings, "3 предупреждения");
  assert.deepEqual(q.figures, { text: "20 чисел сверены с текстом", tone: "ok", title: undefined });
  assert.equal(q.title, "Оценка качества 89 из 100 · 100 − 10 за ошибку − 3 за предупреждение − 2 за замечание модели");
  const bad = qualityCard(gen(), variant({ audit: audit({ score: 70, errors: 2, warnings: 0, figures: { checked: 9, derived: 0, unverified: 3 } }) }));
  assert.equal(bad?.verdict, "2 ошибки");
  assert.equal(bad?.warnings, null);
  assert.deepEqual(bad?.figures, { text: "3 числа не найдены в тексте", tone: "warn" });
  // оценки нет — карточки нет (пустых карточек не бывает)
  assert.equal(qualityCard(gen(), variant()), null);
  // только мета: оценка есть, сколько ошибок — неизвестно
  const meta = qualityCard(gen({ summary: { structured: { score: 92 } } }), variant());
  assert.deepEqual([meta?.score, meta?.verdict, meta?.figures], [92, null, null]);
});

const ev = (step: string, message: string, slide: number | null = null, variant: string | null = null, fix: string | null = null): AgentEvent =>
  ({ step, message, slide, variant, fix });

test("«Как работал агент»: три строки из ленты агента со значками ролей; без ленты — карточки нет", () => {
  assert.deepEqual(agentLines(variant()), []);
  assert.deepEqual(agentLines(variant({ agent: { log: [], events: [], critic: [] } })), []);
  const events = [
    ev("writer", "Написал текст на 12 слайдов — по статье «Интеграл»"),
    ev("analyst", "Нашёл в тексте 11 слайдов, 9 формул."),
    ev("designer", "«Интеграл» — титул.", 1),
    ev("designer", "«История» — хронология (6).", 2),
    ev("critic", "Заголовок слишком длинный.", 2, "structured", "Сократить заголовок"),
    ev("revise", "Хронология (6).", 2, "structured"),
  ];
  const lines = agentLines(variant({ agent: { log: [], events, critic: [] } }));
  assert.deepEqual(lines.map((l) => [l.step, l.icon]), [["Автор", "pen"], ["Дизайнер", "layout"], ["Критик", "chat-check"]]);
  assert.equal(plain(lines[0].text), "Написал текст на 12 слайдов");
  assert.equal(plain(lines[2].text), "1 замечание, исправлен 1 слайд");
  // взгляд дизайнера — всегда одна из трёх строк (самый новый шаг агента)
  const eyes: DesignEye = { looked: 12, slides: [] };
  const withEyes = agentLines(variant({ agent: { log: [], events, critic: [] }, eyes }));
  assert.deepEqual(withEyes.map((l) => [l.step, l.icon]), [["Автор", "pen"], ["Дизайнер", "layout"], ["Взгляд дизайнера", "eye"]]);
});

test("«Почему так»: довод дизайнера о текущем слайде словами интерфейса; нет довода — карточки нет", () => {
  const v = variant({
    outline: outline("t", [slide("1"), slide("2", { rationale: "bullets — по порядку" }), slide("3")]),
    design: [{ index: 1, rationale: "  четыре карточки соответствуют структуре источника. ", alternatives: [], takeaway: null, footnote: null, spec_ref: 1 }],
  });
  assert.equal(whyText(v, 1), "Четыре карточки соответствуют структуре источника.");
  assert.equal(whyText(v, 2), "Пункты — по порядку");
  assert.equal(whyText(v, 3), null);
  assert.equal(whyText(variant(), 1), null);
});

test("«Взгляд дизайнера»: что модель увидела на текущем слайде, иначе итог по презентации; не смотрела — карточки нет", () => {
  const kept = {
    outline_id: "sl4", slide: 4, status: "kept" as const, reason: "модель выбрала новую вёрстку только в одном порядке сравнения", before: null, after: null,
    problems: [{ code: "unbalanced", label: "пустоты и перекос композиции", severity: "major", where: "левая половина слайда", evidence: "" }],
  };
  const fixed = { ...kept, outline_id: "sl3", slide: 3, status: "fixed" as const, before: "/b.jpg", after: "/a.jpg", reason: "" };
  const v = variant({ eyes: { looked: 12, slides: [kept, fixed] } });
  const four = eyesCard(v, 4);
  assert.equal(four?.tag, "оставил как было");
  assert.equal(four?.text, "Увидел: пустоты и перекос композиции (левая половина слайда)");
  assert.equal(four?.pics, null);
  assert.equal(four?.title, "Увидел: пустоты и перекос композиции (левая половина слайда). Пробовал другую вёрстку, оставил прежнюю: модель выбрала новую вёрстку только в одном порядке сравнения");
  const three = eyesCard(v, 3);
  assert.equal(three?.tag, "пересобрал");
  assert.deepEqual(three?.pics, { before: "/b.jpg", after: "/a.jpg" });
  assert.equal(three?.title, "Увидел: пустоты и перекос композиции (левая половина слайда). Собрал слайд заново");
  // слайд переделан после сборки: картинки «было / стало» уже не о нём
  assert.equal(eyesCard(variant({ eyes: { looked: 12, slides: [{ ...fixed, redone: true }] } }), 3)?.pics, null);
  const other = eyesCard(v, 1);
  assert.deepEqual([other?.tag, other?.text, other?.pics], [null, "Посмотрел на 12 слайдов · пересобрал 1 · 1 оставил как было", null]);
  assert.equal(eyesCard(variant(), 1), null);
  assert.equal(eyesCard(variant({ eyes: { looked: 0, slides: [] } }), 1), null);
  assert.equal(eyesCard(variant({ eyes: { looked: 5, skipped: "нет модели", slides: [] } }), 1), null);
});

test("уведомление: текст написал агент — источник, «Показать текст», «Собрать ещё раз», «Дописать текст»", () => {
  const v = variant({ slides: Array(12).fill("s") });
  const n = noteView(gen({ writer: WRITER, slides: 12 }), v, 12, null);
  if (!n) throw new Error("уведомления нет");
  assert.equal(n.title, "Текст написал агент — проверьте факты");
  assert.equal(n.body, "По статье Википедии «Интеграл».");
  assert.deepEqual([n.showText, n.retry, n.rewrite, n.retryWait], [true, true, true, 0]);
  // сказать нечего — таблетки нет
  assert.equal(noteView(gen({ slides: 12 }), v, 12, null), null);
  // каркас о частной теме: только «Дописать текст»
  const sk = noteView(gen({ writer: { ...WRITER, status: "private", text: "" } }), variant({ outline: { ...outline("t", []), planned_by: "skeleton" } }), 4, null);
  assert.equal(sk?.title, "Это каркас: о вашей теме знаете только вы");
  assert.deepEqual([sk?.showText, sk?.retry, sk?.rewrite], [false, false, true]);
  assert.equal(sk?.body, "Допишите тезисы и цифры — слайды станут содержательнее.");
});

test("уведомление: модель не ответила — имя модели не звучит", () => {
  const g = gen({
    use_models: true, brief: "текст",
    planner: { by_model: false, model: "qwen", model_label: "Qwen3.8-27B", reason_code: "congested", reason: "Qwen3.8-27B перегружен", advice: "Соберите ещё раз через минуту.", retryable: true },
  });
  const n = noteView(g, variant({ slides: ["s"] }), 1, null);
  assert.equal(n?.title, "Модель не ответила: сервер модели перегружен");
  assert.equal(n?.retry, true);
  assert.ok(!/Qwen/.test(`${n?.title} ${n?.body} ${n?.full}`));
});

test("«Изменить текст»: параметры презентации — как она была собрана", () => {
  const g = gen({
    brief: "текст", audience: "студенты", purpose: "lecture", slides: 12, use_models: true, audit_models: false, eyes: true, pictures: null,
    strategies: ["structured", "compact"], improved_from: { name: "old.pptx", slides: 9 },
  });
  assert.deepEqual(deckPreset(g), {
    audience: "студенты", purpose: "lecture", slides: 12, useModels: true, eyes: true, pictures: null, strategies: ["structured", "compact"],
    improvedFrom: { name: "old.pptx", slides: 9 },
  });
  // взгляд «как у модели» (null) так и передаётся; `audit_models` — только у старых презентаций, где `eyes` нет
  assert.equal(deckPreset(gen({ eyes: null, audit_models: false })).eyes, null);
  assert.equal("auditModels" in deckPreset(gen({ eyes: null, audit_models: false })), false);
  assert.equal(deckPreset(gen({ audit_models: true })).auditModels, true);
});

test("«Дописать текст»: текст, который написал агент, иначе свой текст презентации", () => {
  assert.equal(rewriteText(gen({ brief: "про интегралы", writer: WRITER })), WRITER.text);
  assert.equal(rewriteText(gen({ brief: "про интегралы", writer: { ...WRITER, status: "failed", text: "" } })), "про интегралы");
  assert.equal(rewriteText(gen()), "");
});

test("полоса 02 на результате: название и откуда текст", () => {
  const v = variant({ outline: outline("Интеграл", []) });
  assert.deepEqual(deckStrip(gen({ writer: WRITER }), v), { title: "Интеграл", meta: "тема · текст пишет агент" });
  assert.deepEqual(deckStrip(gen({ improved_from: { name: "Итоги.pptx" } }), v), { title: "Интеграл", meta: "текст из презентации" });
  assert.deepEqual(deckStrip(gen({ brief: "Слайд 1. …" }), v), { title: "Интеграл", meta: "готовый текст" });
});

test("имя скачиваемого файла: название и вариант, без запрещённых знаков", () => {
  assert.equal(fileBase("Интеграл", "Структурный"), "Интеграл — Структурный");
  assert.equal(fileBase("Итоги: Q3 / 2026?", "Компактный"), "Итоги Q3 2026 — Компактный");
});

test("самая новая презентация с моделью: живое состояние модели говорит о той же неудаче", () => {
  const a = { id: "a", template_id: "t", strategies: [], use_models: true, status: "done", created_at: 100 };
  const b = { id: "b", template_id: "t", strategies: [], use_models: true, status: "done", created_at: 200 };
  const c = { id: "c", template_id: "t", strategies: [], use_models: false, status: "done", created_at: 300 };
  assert.equal(latestWithModel([a, b, c], b), true);
  assert.equal(latestWithModel([a, b, c], a), false);
  assert.equal(latestWithModel([a], b), false);
});
