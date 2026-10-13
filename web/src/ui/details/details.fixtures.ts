// Данные для тестов листа «Подробнее»: презентация «Интеграл» в шаблоне VK Tech по образцу настоящей сборки
// (workspace/runs/20261008-173516-113d20) — урезанная до четырёх слайдов. Только для *.test.ts.
import type { AuditReport, Generation, OutlineSlide, Pattern, RunManifest, SlideContent, TemplateManifest, Variant } from "../../types";

const C = (over: Partial<SlideContent> = {}): SlideContent => ({
  bullets: [], paragraphs: [], items: [], numbers: [], table: null, chart: null, quote: null, quote_author: null, image_hint: null, columns: [], ...over,
});
const S = (id: string, kind: OutlineSlide["kind"], headline: string, content: SlideContent, over: Partial<OutlineSlide> = {}): OutlineSlide => ({
  id, kind, section: null, headline, subtitle: null, content, notes: "", fact_refs: [], ...over,
});

export const OUTLINE = {
  title: "Интеграл", subtitle: "Понятие, свойства, вычисление и приложения интеграла", audience: "студенты 1 курса", purpose: null, strategy: "structured", language: "ru",
  planned_by: "agent",
  slides: [
    S("sl1", "title", "Интеграл", C(), { subtitle: "Понятие, свойства, вычисление и приложения интеграла" }),
    S("sl2", "timeline", "История создания интеграла", C({
      bullets: ["Лейбниц заимствовал знак ∫ из латинского слова summa"],
      items: [
        { title: "1675", text: "Ньютон и Лейбниц сформулировали основные понятия", icon_hint: null, number: null, bullets: [] },
        { title: "1823", text: "Коши дал строгое определение", icon_hint: null, number: null, bullets: [] },
      ],
    })),
    S("sl3", "bullets", "Неопределённый интеграл — первообразная F(x) плюс C", C({
      paragraphs: ["Неопределённый интеграл функции f(x) — это первообразная F(x)."],
      formula: "$\\int f(x)\\,dx = F(x) + C$ — первообразная F(x) плюс произвольная постоянная C",
    })),
    S("sl4", "chart", "Интеграл равен площади криволинейной трапеции", C({
      bullets: ["Предел интегральных сумм Римана", "Коши (1823) — непрерывные функции"],
      chart: { type: "line", series_ids: ["s_sl4_1"], title: "Геометрический смысл интеграла", unit: null, highlight_index: null },
    })),
  ],
  facts: [
    { id: "f1", value: "1675", unit: null, label: "— Исаак Ньютон", source_span: null },
    { id: "f2", value: "1823", unit: null, label: "— Огюстен Коши сформулировал строгое определение интеграла", source_span: null },
  ],
  series: [{ id: "s_sl4_1", name: "f(x)", categories: ["a", "b"], values: [0, 4], unit: null }],
  tables: [],
};

export const AUDIT: AuditReport = {
  deck: "", template_id: "cbbe3aa6a21d23ce", strategy: "structured", per_slide: {}, iterations: 1, seconds: 1,
  issues: [
    { id: "orphan_opener-3-6", slide: 3, check_id: "orphan_opener", severity: "warn", kind: "deterministic", message: "строка начинается со ссылки «их»", bboxes: [], element_ids: [], suggestion: null, autofix: null, details: {}, outline_id: "sl3" },
    { id: "design_review-4-0", slide: 4, check_id: "design_review", severity: "warn", kind: "model", message: "Пустоты и перекос композиции", bboxes: [], element_ids: [], suggestion: null, autofix: null, details: {}, outline_id: "sl4" },
  ],
  summary: { errors: 0, warnings: 2, infos: 0, model_flags: 1, score: 89, checks_run: ["orphan_opener", "design_review"] },
  applied_fixes: [{ iteration: 1, action: "condense_text", outline_id: "sl3" }, { iteration: "eyes", action: "rematch", outline_id: "sl4", rolled_back: true }],
};

export const MANIFEST_RUN: RunManifest = {
  verstka_version: "3.1.0", git_commit: null, created_at: "2026-10-08T17:37:47+0300", platform: "macOS",
  template: { id: "cbbe3aa6a21d23ce", file: "source.pptx" }, strategy: "structured", inputs: { brief_sha256: null, outline_sha256: "x" },
  skills: { deck_designer: { version: "2.2.0", sha256: "aaa" }, auditor: { version: "0.2.0", sha256: "bbb" } },
  providers: {
    llm: { backend: "chain", model: "qwen/qwen3.8-27b", chain: [{ backend: "polza", model: "qwen/qwen3.8-27b", label: "Qwen3.8-27B", off: false }, { backend: "polza", model: "qwen/qwen3.6-27b", label: "Qwen3.6-27B", off: false }] } as never,
    vlm: { backend: "chain", model: "qwen/qwen3.8-27b", chain: [{ backend: "polza", model: "qwen/qwen3.8-27b", label: "Qwen3.8-27B", off: false }] } as never,
    embed: { backend: "none" },
    audit: { backend: "none" },
  },
  timings_s: { analyze: 0.01, plan: 41.76, render: 3.45, audit: 0.53, eyes: 33.57, export: 5.36, total: 70.72 },
  usage: {}, applied_fixes: AUDIT.applied_fixes, audit: { ...AUDIT.summary }, slides: [],
  planner: { planned_by: "agent", model: "qwen/qwen3.6-27b" },
};

const variant = (strategy: string, score: number): Variant => ({
  strategy,
  outline: { ...OUTLINE, strategy },
  plan: {
    strategy, template_id: "cbbe3aa6a21d23ce", slides: [
      { outline_id: "sl1", mode: "clone", pattern_id: "p2", composition: null, fit: {}, score: 1.2, reasons: ["слайд 2 шаблона", "тип title для title: 1.0", "текст помещается"], alternatives: [["p1", 1.2], ["p4", 0.801]] },
      { outline_id: "sl2", mode: "synth", pattern_id: null, composition: "process", fit: {}, score: 0.744, reasons: ["композиция process: образцы шаблона не вместили содержимое"], alternatives: [] },
      { outline_id: "sl3", mode: "synth", pattern_id: null, composition: "formula", fit: {}, score: 0.445, reasons: ["ближайший образец — слайд 22 шаблона (0.45) не подходит по наполнению"], alternatives: [["p22", 0.445]] },
      { outline_id: "sl4", mode: "clone", pattern_id: "p14", composition: null, fit: {}, score: 0.82, reasons: ["тип cards для chart: 0.6", "текст помещается"], alternatives: [["p14", 0.82], ["p23", 0.74], ["p38", 0.62]] },
    ],
  },
  audit: { ...AUDIT, strategy, summary: { ...AUDIT.summary, score } },
  run_manifest: { ...MANIFEST_RUN, strategy },
  slides: [1, 2, 3, 4].map((k) => `/api/generations/g1/${strategy}/slides/slide-00${k}.jpg`),
  files: {
    "deck.pptx": `/api/generations/g1/${strategy}/files/deck.pptx`, "deck.pdf": `/api/generations/g1/${strategy}/files/deck.pdf`,
    "deck.html": `/api/generations/g1/${strategy}/files/deck.html`,
  },
  agent: {
    log: [],
    events: [
      { step: "writer", message: "Нашёл статью «Интеграл» в Википедии — сверю с ней даты, имена и цифры.", slide: null, variant: null },
      { step: "writer", message: "Написал текст: 4 слайда.", slide: null, variant: null },
      { step: "analyst", message: "Нашёл в тексте 4 слайда и 1 формулу.", slide: null, variant: null },
      { step: "designer", message: "Обложка «Интеграл».", slide: 1, variant: null },
      { step: "designer", message: "«История создания интеграла» — хронология (2).", slide: 2, variant: null },
      { step: "critic", message: "Заголовок повторяет тему слайда", slide: 2, variant: null, fix: "Заголовок: «Интеграл прошёл путь от Ньютона до Лебега»" },
      { step: "revise", message: "Хронология (2).", slide: 2, variant: strategy },
      { step: "compile", message: "Сверил цифры с текстом: все числа взяты из текста.", slide: null, variant: strategy },
    ],
    critic: [
      { step: "critic", message: "Заголовок повторяет тему слайда", slide: 2, variant: null, fix: "Заголовок: «Интеграл прошёл путь от Ньютона до Лебега»" },
      { step: "revise", message: "Хронология (2).", slide: 2, variant: strategy },
    ],
  },
  design: [
    { index: 1, kind: "title", rationale: "Обложка: название и подзаголовок из текста.", alternatives: [], takeaway: null, footnote: null, spec_ref: 1 },
    { index: 2, kind: "timeline", rationale: "Хронология из шести дат показывает последовательность событий.", takeaway: "Развитие интеграла заняло два столетия", footnote: "Даты — по статье", spec_ref: 2,
      alternatives: [{ kind: "table", label: "таблица", text: "Таблица позволит быстро просмотреть даты.", used_in: ["compact"] }, { kind: "bullets", label: "список", text: "Короткий список вех", used_in: [strategy] }] },
    { index: 3, kind: "bullets", rationale: "", alternatives: [], takeaway: null, footnote: null, spec_ref: 3 },
    { index: 4, kind: "chart", rationale: "Форма cards показывает площадь.", alternatives: [], takeaway: null, footnote: null, spec_ref: 4 },
  ],
  edits: [],
});

export const GEN: Generation = {
  id: "g1", template_id: "cbbe3aa6a21d23ce", template_file: "source.pptx", title: "Интеграл", strategies: ["structured", "visual", "compact"],
  brief: "сделай презентацию про интегралы", created_at: 1791470267, status: "done", use_models: true, audit_models: false, eyes: null,
  summary: { structured: { score: 89 }, visual: { score: 84 }, compact: { score: 89 } },
  planner: { planned_by: "agent", by_model: true, model: "qwen/qwen3.8-27b", model_label: "Qwen3.8-27B", reason_code: null, reason: null, advice: null },
  writer: { mode: "topic", status: "written", text: "Слайд 1. Титульный\nНазвание: «Интеграл».\n\nСлайд 2. История создания интеграла\nПонятие сложилось в XVII веке.", slides: 4, source: { title: "Интеграл", url: "https://ru.wikipedia.org/wiki/Интеграл" } },
  variants: [variant("structured", 89), variant("visual", 84), variant("compact", 89)],
};

const P = (id: string, slide: number, kind: Pattern["kind"], over: Partial<Pattern> = {}): Pattern => ({
  id, source_slide: slide, kind, family: "light", slots: [], repeat_groups: [], decor_assets: [], quality: 0.99, thumbnail: null,
  thumbnail_url: `/api/templates/cbbe3aa6a21d23ce/files/thumbs/slide-${String(slide).padStart(3, "0")}.jpg`,
  classification: { kind, heuristic: { kind, confidence: 0.75, rationale: null }, llm: null, vlm: null, agreement: 1, purpose: null }, layout_part: null, ...over,
});

export const TPL: TemplateManifest = {
  template_id: "cbbe3aa6a21d23ce", source_file: "source.pptx", title: "VK Tech", slide_size: { w: 9144000, h: 5143500 }, n_slides: 54,
  tokens: {
    colors: [
      { hex: "FAFCFF", role: "background.light", roles: ["background.light"], semantic: null, is_brand: false, weight: 5036, contexts: {} },
      { hex: "000000", role: "background.dark", roles: ["background.dark", "text.primary"], semantic: null, is_brand: false, weight: 490, contexts: {} },
      { hex: "FEFFFF", role: "surface", roles: ["surface"], semantic: null, is_brand: false, weight: 484, contexts: {} },
      { hex: "8F8F8F", role: "text.secondary", roles: ["text.secondary"], semantic: null, is_brand: false, weight: 61, contexts: {} },
      { hex: "0077FF", role: "accent.1", roles: ["accent.1"], semantic: null, is_brand: true, weight: 44, contexts: {} },
      { hex: "00D3E6", role: "accent.2", roles: ["accent.2"], semantic: null, is_brand: false, weight: 4, contexts: {} },
      { hex: "C4C4C4", role: "neutral.1", roles: ["neutral.1"], semantic: null, is_brand: false, weight: 3, contexts: {} },
    ],
    typography: { families: [{ family: "Play", weight: 0.95, bold_share: 0 }], scale: [{ role: "h1", size_pt: 24, weight_bold_share: 0, count: 1 }, { role: "body", size_pt: 9, weight_bold_share: 0, count: 1 }], sizes_used: [], left_align_share: 1, line_spacing: 1 },
    spacing: { safe_area: { x: 0.02, y: 0.055, w: 0.949, h: 0.819 }, columns: [], gutter: null },
  },
  patterns: [
    P("p1", 1, "title", { family: "dark" }), P("p2", 2, "title", { family: "dark" }), P("p4", 4, "thanks"),
    P("p14", 14, "cards", {
      decor_assets: ["a1", "a2", "a3", "a4"], note_slot: "note_1",
      slots: [
        { id: "title_1", role: "title", shape_id: "1", bbox: { x: 0.025, y: 0.063, w: 0.642, h: 0.143 }, group_id: null, sample_text: "Интеграл сохраняет линейные комбинации" },
        { id: "sub_1", role: "subtitle", shape_id: "2", bbox: { x: 0.025, y: 0.25, w: 0.67, h: 0.083 }, group_id: null, sample_text: "Определённый интеграл подчиняется правилам" },
        { id: "card_title_1", role: "card_title", shape_id: "3", bbox: { x: 0.026, y: 0.359, w: 0.3, h: 0.05 }, group_id: "g1", sample_text: "Линейность" },
        { id: "card_body_1", role: "card_body", shape_id: "4", bbox: { x: 0.026, y: 0.41, w: 0.3, h: 0.08 }, group_id: "g1", sample_text: "Интеграл от суммы" },
        { id: "card_title_2", role: "card_title", shape_id: "5", bbox: { x: 0.026, y: 0.511, w: 0.3, h: 0.05 }, group_id: "g1", sample_text: "Аддитивность" },
        { id: "card_body_2", role: "card_body", shape_id: "6", bbox: { x: 0.026, y: 0.56, w: 0.3, h: 0.08 }, group_id: "g1", sample_text: "Интеграл на отрезке" },
        { id: "icon_1", role: "icon", shape_id: "9", bbox: { x: 0.9, y: 0.05, w: 0.05, h: 0.05 }, group_id: null, sample_text: null },
        { id: "note_1", role: "body", shape_id: "7", bbox: { x: 0.025, y: 0.793, w: 0.9, h: 0.081 }, group_id: null, sample_text: "Линейность и аддитивность превращают интеграл" },
        { id: "list_1", role: "bullet_list", shape_id: "8", bbox: { x: 0.025, y: 0.681, w: 0.76, h: 0.081 }, group_id: null, sample_text: "Линейность позволяет вынести множители" },
      ],
      repeat_groups: [{ id: "g1", member_shape_ids: [["3", "4"], ["5", "6"]], min_n: 2, max_n: 4, axis: "column", rows: 2, cols: 1,
        cell_boxes: [{ x: 0.026, y: 0.359, w: 0.945, h: 0.139 }, { x: 0.026, y: 0.511, w: 0.945, h: 0.139 }] }],
      classification: { kind: "cards", heuristic: { kind: "cards", confidence: 0.88, rationale: null }, llm: { kind: "cards", confidence: 0.94, rationale: null }, vlm: { kind: "bullets", confidence: 0.6, rationale: null }, agreement: 0.66, purpose: null },
      quality: 0.92,
    }),
    P("p22", 22, "bullets"), P("p23", 23, "cards"), P("p38", 38, "freeform", { quality: 0.79 }),
  ],
  assets: [], warnings: [], analysis_version: "34", embedded_fonts: [], gallery_url: "", narration: "",
  style_rules: [
    { text: "Шрифты шаблона: Play. Другие шрифты не использовать.", source: "derived", confidence: 1 },
    { text: "Текст выравнивается по левому краю (исключения: схемы и таблицы).", source: "derived", confidence: 0.9 },
    { text: "Карточки и блоки со скруглёнными углами.", source: "derived", confidence: 0.96 },
    { text: "Основной цвет текста — #000000.", source: "derived", confidence: 1 },
    { text: "font-family: ‘MailSans Roman’,", source: "template_text", confidence: 0.5 },
  ],
};

export const titleOf = (s: string) => ({ structured: "Структурный", visual: "Визуальный", compact: "Компактный" })[s] ?? s;
