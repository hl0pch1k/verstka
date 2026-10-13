// Экран «Результат» без React: что показывает плита 04 (boards/R-aside, V2 плита 04) по настоящей презентации —
// название и строка под ним, оценка и варианты, уведомление над рабочей областью, карточки колонки. Чего в данных нет,
// того нет и на экране: функция карточки отвечает null или пустым списком, и карточка не рисуется.
import { agentSummary, hasAgentWork, plainWords } from "../../lib/agent";
import { designEyeLine, problemsText } from "../../lib/designEye";
import { deckNotice, skeletonDeck, type LiveModel } from "../../lib/modelText";
import { figuresLine } from "../../lib/narrate";
import { fileSafe } from "../../lib/plain";
import { plural } from "../../lib/utils";
import type { ComposerPreset } from "../../store";
import type { Generation, GenerationMeta, Variant } from "../../types";
import type { IconName } from "../kit/icons";

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const noStop = (s: string) => s.replace(/[.\s]+$/, "");

/** Слайдов в варианте на самом деле: картинки, иначе план; 0 — слайдов нет (`slideCount` никогда не говорит 0). */
export const slidesOf = (v: Variant | null | undefined): number => (v ? v.slides.length || v.outline?.slides.length || v.plan?.slides.length || 0 : 0);

/** Заголовок слайда `n` (1-based) по плану варианта; нет — пусто. */
export const slideHeadline = (v: Variant | null | undefined, n: number): string => v?.outline?.slides[n - 1]?.headline?.trim() ?? "";

/** Название презентации (V2 `docTitle`): заголовок плана варианта, иначе генерации, иначе «Презентация». */
export function docTitle(g: Generation, v: Variant | null | undefined): string {
  return v?.outline?.title?.trim() || g.title?.trim() || "Презентация";
}

/** Строка под названием (V2 `docLine`): «VK Tech · 12 слайдов · сегодня, 17:38»; `when` — `fmtWhen(created_at)`. */
export function docLine(template: string, total: number, when: string): string {
  return [template, total > 0 ? plural(total, "слайд", "слайда", "слайдов") : null, when || null].filter(Boolean).join(" · ");
}

/** Полоса 02 на результате (V2 `docTitle` · `docSub`): название и откуда текст. */
export function deckStrip(g: Generation, v: Variant | null | undefined): { title: string; meta: string } {
  const meta = g.writer ? "тема · текст пишет агент" : g.improved_from ? "текст из презентации" : "готовый текст";
  return { title: docTitle(g, v), meta };
}

/** Оценка варианта: живой отчёт проверки сильнее меты генерации и паспорта запуска. Каркас темы без текста оценки не
 *  имеет: «100» читалось бы как успех. */
export function scoreOf(g: Generation, v: Variant): number | null {
  if (skeletonDeck(g, v)) return null;
  const score = v.audit?.summary.score ?? g.summary?.[v.strategy]?.score ?? v.run_manifest?.audit?.score ?? null;
  return typeof score === "number" && Number.isFinite(score) ? score : null;
}

/** Сегменты «Вариант оформления» (`p2-rseg`): название варианта и его оценка (null — оценки нет, число не пишется). */
export function variantSegs(g: Generation, titleOf: (name: string) => string): { key: string; label: string; score: number | null }[] {
  return g.variants.map((v) => {
    const s = scoreOf(g, v);
    return { key: v.strategy, label: titleOf(v.strategy), score: s === null ? null : Math.round(s) };
  });
}

/** Замечания на слайдах (переключатель «Замечания», R-remarks): ошибки, предупреждения и замечания модели на слайдах;
 *  мелкие заметки проверки и замечания ко всей презентации (слайд 0) — нет. `errors` — среди них есть ошибка. */
export function remarkCount(v: Variant | null | undefined): { count: number; errors: boolean } {
  const stage = (v?.audit?.issues ?? []).filter((i) => i.slide >= 1 && !(i.severity === "info" && i.kind !== "model"));
  return { count: stage.length, errors: stage.some((i) => i.severity === "error") };
}

/** Карточка «Качество» (R-aside): кольцо по оценке, «Ошибок нет» / «2 ошибки», предупреждения, сверенные с текстом
 *  числа и в подсказке — как считается оценка (AUDIT.md: 100 − 10·ошибок − 3·предупреждений − 2·замечаний модели).
 *  Нет оценки — нет карточки. `verdict` null — сколько ошибок, неизвестно (только мета). */
export interface QualityView {
  score: number;
  verdict: string | null;
  errors: boolean;
  warnings: string | null;
  figures: { text: string; tone: "ok" | "warn"; title?: string } | null;
  title: string;
}
export function qualityCard(g: Generation, v: Variant): QualityView | null {
  const raw = scoreOf(g, v);
  if (raw === null) return null;
  const score = Math.round(raw);
  const s = v.audit?.summary;
  const meta = g.summary?.[v.strategy];
  const errors = s?.errors ?? meta?.errors ?? null;
  const warnings = s?.warnings ?? meta?.warnings ?? null;
  return {
    score,
    verdict: errors === null ? null : errors > 0 ? plural(errors, "ошибка", "ошибки", "ошибок") : "Ошибок нет",
    errors: (errors ?? 0) > 0,
    warnings: warnings ? plural(warnings, "предупреждение", "предупреждения", "предупреждений") : null,
    figures: figuresLine(s?.figures),
    title: `Оценка качества ${score} из 100 · 100 − 10 за ошибку − 3 за предупреждение − 2 за замечание модели`,
  };
}

/** Значки ролей в «Как работал агент» (R-aside `AG`; аналитик и взгляд дизайнера — из набора «Слоёв»). */
const ROLE_ICON: Record<string, IconName> = { Автор: "pen", Аналитик: "search", Дизайнер: "layout", Критик: "chat-check", "Взгляд дизайнера": "eye" };

/** «Как работал агент»: три строки из ленты агента (lib/agent `agentSummary`); взгляд дизайнера, если модель смотрела,
 *  — всегда одна из трёх (самый новый шаг). Ленты нет — пусто, карточки нет. */
export function agentLines(v: Variant | null | undefined): { step: string; text: string; icon: IconName }[] {
  if (!hasAgentWork(v)) return [];
  const all = agentSummary(v);
  const k = all.findIndex((l) => l.step === "Взгляд дизайнера");
  const three = k > 2 ? [...all.slice(0, 2), all[k]] : all.slice(0, 3);
  return three.map((l) => ({ ...l, icon: ROLE_ICON[l.step] ?? "list" }));
}

/** «Почему так»: довод дизайнера о слайде `n` словами интерфейса (`plainWords`); довода нет — null, карточки нет. */
export function whyText(v: Variant | null | undefined, n: number): string | null {
  const raw = v?.design?.find((d) => d.index === n)?.rationale ?? v?.outline?.slides[n - 1]?.rationale ?? null;
  const t = raw?.trim() ? plainWords(raw).trim() : "";
  return t ? cap(t) : null;
}

/** Карточка «Взгляд дизайнера»: что модель увидела на текущем слайде (`tag` — что сделала, `pics` — «было → стало»
 *  пересобранного слайда), а на слайде, о котором ей сказать нечего, — итог по презентации. Модель не смотрела
 *  (`eyes` нет, пропущен или 0 слайдов) — null, карточки нет. */
export interface EyesView {
  tag: string | null;
  text: string;
  title?: string;
  pics: { before: string; after: string } | null;
}
const EYE_TAG = { fixed: "пересобрал", kept: "оставил как было", seen: "заметил" } as const;
export function eyesCard(v: Variant | null | undefined, n: number): EyesView | null {
  const eye = v?.eyes;
  if (!eye || eye.skipped || eye.looked <= 0) return null;
  const total = cap(designEyeLine(eye));
  const s = eye.slides.find((x) => x.slide === n);
  if (!s) return { tag: null, text: total, pics: null };
  const seen = problemsText(s, true);
  const saw = seen ? `Увидел: ${seen}` : null;
  const did = s.status === "fixed" ? "Собрал слайд заново"
    : s.status === "kept" ? `Пробовал другую вёрстку, оставил прежнюю${s.reason ? `: ${noStop(s.reason)}` : ""}` : null;
  return {
    tag: EYE_TAG[s.status as keyof typeof EYE_TAG] ?? null,
    text: saw ?? total,
    title: [saw, did].filter(Boolean).join(". ") || undefined,
    pics: s.status === "fixed" && !s.redone && s.before && s.after ? { before: s.before, after: s.after } : null,
  };
}

/** Таблетка уведомления над рабочей областью (R-aside `ra-note`): заголовок, строка-основание (одна строка; целиком —
 *  в подсказке `full`) и действия. Текст и наличие — `deckNotice`. Когда текст написал агент, таблетка предлагает
 *  всё, что на доске: «Показать текст», «Собрать ещё раз» (тот же запрос) и «Дописать текст». Сказать нечего — null. */
export interface NoteView {
  title: string;
  body: string;
  full: string;
  tone: "warn" | "info";
  showText: boolean;
  retry: boolean;
  /** Секунд до повтора, который имеет смысл (кнопка ждёт, выключенная); 0 — сейчас. */
  retryWait: number;
  rewrite: boolean;
}
/** Уведомление говорит «модель», без имени (имя — во вкладке «Файлы»); фразы о паузе поставщика человеку не нужны. */
function plainNotice(text: string, labels: string[]): string {
  let t = text;
  for (const l of labels) t = t.split(`модель ${l}`).join("модель").split(`Модель ${l}`).join("Модель").split(l).join("Модель");
  return t.split(/(?<=[.!?…])\s+/).filter((s) => !/пауз|через\s+\d/i.test(s)).join(" ").trim();
}
export function noteView(g: Generation, v: Variant, total: number, live: LiveModel | null): NoteView | null {
  const n = deckNotice(g, v, total, live);
  if (!n) return null;
  const labels = [g.planner?.tried_label, g.planner?.model_label].filter((x): x is string => !!x && x.length > 1);
  const basis = plainNotice(n.basis, labels);
  const help = n.help ? plainNotice(cap(n.help), labels) : "";
  const written = n.showText;
  return {
    title: plainNotice(n.title, labels).replace(/\.\s*$/, ""),
    body: help || basis,
    full: [basis, help, n.owner ?? ""].filter(Boolean).join(" "),
    tone: n.tone,
    showText: n.showText,
    retry: n.retry || written,
    retryWait: n.retryWait,
    rewrite: n.rewrite || written,
  };
}

/** Почему «Собрать ещё раз» ждёт (подсказка выключенной кнопки) — по состоянию модели на паузе. */
export const retryWaitTitle = (state?: string | null) =>
  state === "quota" ? "Дневной лимит запросов исчерпан — соберите после полуночи по московскому времени"
    : state === "rate" ? "Слишком много запросов — попробуйте через минуту"
      : "Модель перегружена — попробуйте через несколько минут";

/** Это самая новая презентация, собранная с моделью: живое состояние модели — о той же неудаче. */
export function latestWithModel(list: GenerationMeta[], g: GenerationMeta): boolean {
  if (!list.some((x) => x.id === g.id)) return false;
  const t = g.created_at ?? 0;
  return !list.some((x) => x.id !== g.id && x.use_models && x.status === "done" && (x.created_at ?? 0) > t);
}

/** «Изменить текст» / «Дописать текст»: параметры презентации — как её собрали (аудитория, тип, число слайдов,
 *  переключатели, варианты, «Улучшить готовую»). Взгляд дизайнера — `eyes` как есть (null — как модель); старые
 *  презентации без `eyes` — `audit_models` (переключатель тогда значил его). */
export function deckPreset(g: GenerationMeta): ComposerPreset {
  const preset: ComposerPreset = {
    audience: g.audience ?? null, purpose: g.purpose ?? null, slides: g.slides ?? null, useModels: g.use_models, eyes: g.eyes,
    pictures: g.pictures ?? null, strategies: g.strategies, improvedFrom: g.improved_from ?? null,
  };
  if (g.eyes === undefined) preset.auditModels = g.audit_models;
  return preset;
}

/** Текст для «Дописать текст»: написанный агентом (его и дописывают), иначе свой текст презентации. */
export function rewriteText(g: GenerationMeta): string {
  return g.writer?.status === "written" && g.writer.text ? g.writer.text : g.brief ?? "";
}

/** Имя скачиваемого файла без расширения: «Интеграл — Структурный». */
export const fileBase = (title: string, variantName: string) => `${fileSafe(title)} — ${variantName}`;
