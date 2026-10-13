// Экран «Результат» без React: что показывает плита 04 (boards/R-aside, V2 плита 04) по настоящей презентации —
// название и строка под ним, оценка и варианты, уведомление над рабочей областью, карточки колонки. Чего в данных нет,
// того нет и на экране: функция карточки отвечает null или пустым списком, и карточка не рисуется.
import { agentSummary, hasAgentWork, plainWords } from "../../lib/agent";
import { designEyeLine, problemsText } from "../../lib/designEye";
import { deckNotice, modelFailed, skeletonDeck, type LiveModel } from "../../lib/modelText";
import { figuresLine } from "../../lib/narrate";
import { fileSafe } from "../../lib/plain";
import { variantRev, withRev } from "../../lib/rev";
import { plural } from "../../lib/utils";
import type { ComposerPreset } from "../../store";
import type { Generation, GenerationMeta, ModelsStatus, Variant } from "../../types";
import type { IconName } from "../kit/icons";
import { isStage } from "./marks";

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const noStop = (s: string) => s.replace(/[.\s]+$/, "");

/** Слайдов в варианте на самом деле: картинки, иначе план; 0 — слайдов нет (`slideCount` никогда не говорит 0). */
export const slidesOf = (v: Variant | null | undefined): number => (v ? v.slides.length || v.outline?.slides.length || v.plan?.slides.length || 0 : 0);

/** Заголовок слайда `n` (1-based) по плану варианта; нет — пусто. */
export const slideHeadline = (v: Variant | null | undefined, n: number): string => v?.outline?.slides[n - 1]?.headline?.trim() ?? "";

/** Превью слайда `n` (1-based) варианта с ревизией файлов (`withRev`); у варианта короче — его последний слайд; нет
 *  картинок — null. Одно и то же для сцены, ленты и заблаговременного декодирования. */
export function slideSrc(v: Variant | null | undefined, n: number): string | null {
  if (!v?.slides.length) return null;
  const raw = v.slides[Math.min(Math.max(1, n), v.slides.length) - 1];
  return raw ? withRev(raw, variantRev(v)) : null;
}

/** Что декодировать до смены варианта на `target`, чтобы слайд, оценка и лента сменились вместе и без серых провалов:
 *  его превью слайда `n` и картинки миниатюр, которые в ленте уже показаны (`thumbs`, с 1); без повторов. */
export function switchShots(target: Variant, n: number, thumbs: number[]): string[] {
  const all = [slideSrc(target, n), ...thumbs.filter((k) => k >= 1 && k <= target.slides.length).map((k) => slideSrc(target, k))];
  return [...new Set(all.filter((u): u is string => !!u))];
}

/** Клавиши сцены: ←/→ — соседний слайд, Home/End — первый и последний (в пределах 1…total); чужая клавиша — null. */
export function slideForKey(key: string, n: number, total: number): number | null {
  const last = Math.max(1, total);
  const to = key === "ArrowRight" ? n + 1 : key === "ArrowLeft" ? n - 1 : key === "Home" ? 1 : key === "End" ? last : null;
  return to === null ? null : Math.min(Math.max(1, to), last);
}

/** Клавиши, которые поле или виджет держит себе: ←/→, Home/End и Esc в них не листают слайды и не закрывают колонку. */
export function ownsKeys(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null;
  if (!t || typeof t.closest !== "function") return false;
  return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable
    || !!t.closest('[role="tablist"], [role="dialog"], [role="radiogroup"], [role="menu"], [role="slider"]');
}

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
  const stage = (v?.audit?.issues ?? []).filter(isStage);
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
  // пустой довод дизайнера — как его нет: говорит план
  const raw = v?.design?.find((d) => d.index === n)?.rationale?.trim() || v?.outline?.slides[n - 1]?.rationale || null;
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
 *  всё, что на доске: «Показать текст», «Собрать ещё раз» (тот же запрос) и «Дописать текст». Сказать нечего — null.
 *  `label` — о чём уведомление (имя области для чтения с экрана). */
export interface NoteView {
  title: string;
  body: string;
  full: string;
  label: string;
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
  const label = written ? "Уведомление о тексте, который написал агент"
    : modelFailed(g) ? "Уведомление о сборке без модели"
      : v.outline?.planned_by === "skeleton" ? "Уведомление о каркасе презентации" : "Уведомление о числе слайдов";
  return {
    title: plainNotice(n.title, labels).replace(/\.\s*$/, ""),
    body: help || basis,
    full: [basis, help, n.owner ?? ""].filter(Boolean).join(" "),
    label,
    showText: n.showText,
    retry: n.retry || written,
    retryWait: n.retryWait,
    rewrite: n.rewrite || written,
  };
}

/** Секунд до конца паузы модели: `s` секунд паузы, полученных в момент `at`, к моменту `now` (мс), с округлением вверх;
 *  пауза кончилась или её нет — 0. Часы назад не идут. */
export function retryLeft(s: number, at: number, now: number): number {
  if (!(s > 0)) return 0;
  return Math.max(0, Math.ceil(s - Math.max(0, now - at) / 1000));
}

/** Через сколько миллисекунд пересчитать паузу: раз в 15 с (как старый экран), а последний раз — ровно к её концу, чтобы
 *  «Собрать ещё раз» ожил вовремя; пауза кончилась — null. */
export function retryTick(s: number, at: number, now: number): number | null {
  if (!retryLeft(s, at, now)) return null;
  return Math.min(15000, Math.max(0, s * 1000 - Math.max(0, now - at)));
}

/** Через сколько секунд перепросить состояние модели, пока она на паузе: через 2 с после конца паузы, но не позже чем
 *  через 10 минут; не на паузе — 0 (не перепрашивать). */
export function recheckIn(st: ModelsStatus | null | undefined): number {
  return st?.state === "down" && st.retry_in ? Math.min(st.retry_in + 2, 600) : 0;
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

/** Открытая презентация для полосы 01: загруженная, а пока она грузится (перезагрузка страницы) — её мета из списка;
 *  ничего не известно — null (полоса не говорит о шаблоне, выбранном раньше). */
export function openDeck(g: Generation | null, list: GenerationMeta[], id: string | null): GenerationMeta | null {
  if (g) return g;
  return id ? list.find((x) => x.id === id) ?? null : null;
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
