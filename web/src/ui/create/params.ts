// Шаг «03 Параметры и запуск» без React: черновик параметров, степпер слайдов (и его блокировка, когда число задано
// в тексте), варианты оформления, сводка в заголовке и запрос сборки. Тексты — boards/V2.dc.html (`VN`, `VD`, `VH`,
// `writesHint`, `imagesHint`, `summary`) и C-params; поля запроса — как в старом CreateScreen.
import { PURPOSES, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN } from "../../lib/createForm";
import { readDraft } from "../../lib/draft";
import { dictatedByHeadings, dictatedSlides } from "../../lib/textFacts";
import { plural } from "../../lib/utils";
import type { ComposerPreset } from "../../store";
import type { GenerateRequest, ImproveSource, StrategyInfo } from "../../types";

/** Параметры сборки — черновик рядом с текстом (`verstka.brief_draft`, ключ `params`).
 *  - `slides`: null — степпер не трогали (12).
 *  - `strategies`: выбранные варианты; пусто — все.
 *  - `purpose`: значение `PURPOSES` или `OWN` («Свой вариант…»: тип — `ownPurpose`).
 *  - `eyes`: «Модель проверяет слайды по картинке». */
export interface Params {
  slides: number | null; strategies: string[]; audience: string; purpose: string; ownPurpose: string;
  useModels: boolean; eyes: boolean; pictures: boolean;
}

/** «Свой вариант…» в списке типов. */
export const OWN = "own";

/** По умолчанию — как V2: 12 слайдов, все варианты, тип «Продукт», модель пишет тексты, взгляд по картинке выключен,
 *  изображения генерируются. */
export const PARAMS0: Params = { slides: null, strategies: [], audience: "", purpose: "product", ownPurpose: "", useModels: true, eyes: false, pictures: true };

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Math.round(n)));
const isPurpose = (v: unknown): v is string => v === OWN || PURPOSES.some((p) => p.value === v);

/** Параметры из черновика: испорченное поле — значение по умолчанию, годные остаются. */
export function readParams(raw: unknown): Params {
  const d = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const bool = (v: unknown, def: boolean) => (typeof v === "boolean" ? v : def);
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const slides = typeof d.slides === "number" && Number.isInteger(d.slides) && d.slides >= SLIDES_MIN && d.slides <= SLIDES_MAX ? d.slides : null;
  const strategies = Array.isArray(d.strategies) && d.strategies.every((x) => typeof x === "string") ? (d.strategies as string[]) : [];
  return {
    slides, strategies, audience: str(d.audience), purpose: isPurpose(d.purpose) ? d.purpose : PARAMS0.purpose, ownPurpose: str(d.ownPurpose),
    useModels: bool(d.useModels, PARAMS0.useModels), eyes: bool(d.eyes, PARAMS0.eyes), pictures: bool(d.pictures, PARAMS0.pictures),
  };
}

/** Параметры из черновика в localStorage. */
export const draftParams = (): Params => readParams(readDraft().params);

// ── слайды
export interface SlidesView {
  count: number;
  /** Число задано в тексте: степпер заблокирован («задано в тексте»). */
  locked: boolean;
  /** Можно ли убавить и прибавить. */
  dec: boolean; inc: boolean;
}
/** Степпер: число из текста (`dictated`, `textFacts().slides`) сильнее выбранного; иначе выбранное или 12. */
export function slidesView(slides: number | null, dictated: number | null): SlidesView {
  if (dictated !== null) return { count: dictated, locked: true, dec: false, inc: false };
  const count = clampSlides(slides ?? SLIDES_DEFAULT);
  return { count, locked: false, dec: count > SLIDES_MIN, inc: count < SLIDES_MAX };
}
/** Подсказка у степпера, когда число задано в тексте. */
export const SLIDES_LOCKED = "Число слайдов задано в тексте";
export const stepSlides = (slides: number | null, delta: number) => clampSlides((slides ?? SLIDES_DEFAULT) + delta);
/** «слайдов» под числом (V2 `slideWord`). */
export const slideWord = (n: number) => plural(n, "слайд", "слайда", "слайдов").slice(String(n).length + 1);

// ── варианты оформления
type Thumb = "s" | "v" | "c";
/** Три варианта сервера (configs/strategies.yaml) — тексты V2: `VN` название, `VD` подпись в ряду, `VH` подсказка в
 *  «Все параметры», миниатюра. */
const KNOWN: Record<string, { title: string; desc: string; hint: string; thumb: Thumb }> = {
  structured: { title: "Структурный", desc: "Схемы и списки", hint: "Одна мысль на слайд, по порядку", thumb: "s" },
  visual: { title: "Визуальный", desc: "Крупные изображения", hint: "Крупные цифры и диаграммы", thumb: "v" },
  compact: { title: "Компактный", desc: "Плотная вёрстка", hint: "Плотные композиции: колонки и таблицы", thumb: "c" },
};
/** Сервер ещё не ответил — три его варианта. */
const listOf = (list: StrategyInfo[]): StrategyInfo[] =>
  list.length ? list : Object.entries(KNOWN).map(([name, k]) => ({ name, title: k.title, description: k.hint }));

/** Варианты сборки в порядке сервера; ничего не выбрано (или выбранного у сервера больше нет) — все. */
export function chosenStrategies(list: StrategyInfo[], selected: string[]): string[] {
  if (!list.length) return selected;
  const names = list.map((s) => s.name);
  const chosen = names.filter((n) => selected.includes(n));
  return chosen.length ? chosen : names;
}

/** Клик по карточке: вариант снимается или ставится; последний выбранный не снимается (null — ничего не меняется,
 *  V2 `toggle`). */
export function toggleStrategy(list: StrategyInfo[], selected: string[], name: string): string[] | null {
  const names = listOf(list).map((s) => s.name);
  const cur = chosenStrategies(listOf(list), selected);
  const next = cur.includes(name) ? cur.filter((n) => n !== name) : names.filter((n) => n === name || cur.includes(n));
  return next.length ? next : null;
}

export interface VariantCard { name: string; title: string; desc: string; hint: string; full: string; thumb: Thumb; on: boolean }
export function variantCards(list: StrategyInfo[], selected: string[]): VariantCard[] {
  const all = listOf(list);
  const chosen = chosenStrategies(all, selected);
  return all.map((s) => {
    const k = KNOWN[s.name];
    const title = s.title || k?.title || s.name;
    const hint = k?.hint ?? s.description;
    return { name: s.name, title, desc: k?.desc ?? s.description, hint, full: `${title} — ${hint}`, thumb: k?.thumb ?? "s", on: chosen.includes(s.name) };
  });
}

// ── переключатели и подписи
/** Переключатель шага 03: включён ли, можно ли его трогать и почему нельзя (подсказка). */
export interface SwitchView { on: boolean; disabled: boolean; title?: string }
/** «VK Tech · 12 слайдов · 3 варианта» (V2 `summary`); без шаблона — без его имени. */
export function summaryLine(tpl: string | null, count: number, variants: number): string {
  return [tpl, plural(count, "слайд", "слайда", "слайдов"), plural(variants, "вариант", "варианта", "вариантов")].filter(Boolean).join(" · ");
}
export const writesHint = (on: boolean) => (on ? "Сокращает и переформулирует текст под слайды" : "Ваш текст дословно: только раскладка по слайдам шаблона");
export const imagesHint = (on: boolean) => (on ? "По описаниям в тексте, в палитре шаблона" : "Места под изображения останутся свободными");

// ── «Изменить текст»: параметры собранной презентации
/** Презентацию соберут так, как собрали: её аудитория, тип, число слайдов, переключатели и варианты. Чего в параметрах
 *  нет — остаётся как было. */
export function presetParams(p: Params, preset: ComposerPreset): Params {
  const out: Params = { ...p, audience: preset.audience ?? "" };
  const purpose = preset.purpose?.trim();
  if (purpose) {
    if (PURPOSES.some((x) => x.value === purpose)) out.purpose = purpose;
    else Object.assign(out, { purpose: OWN, ownPurpose: purpose });
  }
  if (preset.slides) out.slides = clampSlides(preset.slides);
  if (typeof preset.useModels === "boolean") out.useModels = preset.useModels;
  if (typeof preset.auditModels === "boolean") out.eyes = preset.auditModels;
  // null — как решит сервер: изображения есть, когда у модели изображений есть ключ
  if (preset.pictures !== undefined) out.pictures = preset.pictures ?? true;
  if (preset.strategies?.length) out.strategies = [...preset.strategies];
  return out;
}

// ── запуск
export interface RequestInput {
  templateId: string;
  brief: string;
  params: Params;
  /** Варианты сервера (`/api/strategies`). */
  strategies: StrategyInfo[];
  /** Модель подключена (`useModelOn`): без неё переключатели модели не действуют. */
  modelOn: boolean;
  /** У модели изображений есть ключ (`health.images.configured`); нет — решает сервер. */
  imagesOn: boolean;
  /** «Улучшить готовую»: исходная презентация, пока режим живёт. */
  improve: ImproveSource | null;
}

/** Запрос сборки (POST /api/generations) — поля как в старом CreateScreen:
 *  - число слайдов, заданное в тексте заголовками «Слайд N», отправляется; заданное фразой («не более 10 слайдов»)
 *    сервер читает сам по тем же правилам (planning/brief.py) — отправленное число перебило бы его чтение;
 *  - «Модель проверяет слайды по картинке» — проверки по картинке (`audit_models`) и взгляд модели (`eyes`);
 *  - «Улучшить готовую»: модель смотрит на каждый новый слайд (так говорит заметка над полем), исходная презентация —
 *    «было» оценки. */
export function buildRequest(i: RequestInput): GenerateRequest {
  const p = i.params;
  const dictated = dictatedSlides(i.brief);
  const { count } = slidesView(p.slides, dictated);
  const src = i.improve;
  return {
    template_id: i.templateId,
    brief: i.brief.trim(),
    audience: p.audience.trim() || null,
    purpose: p.purpose === OWN ? p.ownPurpose.trim() || null : p.purpose,
    slides: dictated !== null && !dictatedByHeadings(i.brief) ? null : count,
    strategies: chosenStrategies(i.strategies, p.strategies),
    use_models: p.useModels && i.modelOn,
    audit_models: p.eyes && i.modelOn,
    eyes: (p.eyes || !!src) && i.modelOn,
    pictures: i.imagesOn ? p.pictures : null,
    autofix: true,
    exports: ["pdf", "html"],
    improved_from: src ? { name: src.name, slides: src.slides, template_id: src.template_id, audit: src.audit ?? null } : undefined,
  };
}
