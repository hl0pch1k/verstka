// Шаг «03 Параметры и запуск» без React: черновик параметров, степпер слайдов (и его блокировка, когда число задано
// в тексте), варианты оформления, сводка в заголовке и запрос сборки. Тексты — boards/V2.dc.html (`VN`, `VD`, `VH`,
// `writesHint`, `imagesHint`, `summary`) и C-params; поля запроса — те, что принимает POST /api/generations.
import { PURPOSES, SLIDES_DEFAULT, SLIDES_MAX, SLIDES_MIN } from "../../lib/createForm";
import { readDraft } from "../../lib/draft";
import { humanError } from "../../lib/errors";
import type { ActiveJob } from "../../lib/jobState";
import type { DataRequest } from "./dataRules";
import { dictatedByHeadings, dictatedSlides } from "../../lib/textFacts";
import { plural } from "../../lib/utils";
import type { ComposerPreset } from "../../store";
import type { GenerateRequest, ImproveSource, Notice, StrategyInfo } from "../../types";

/** Параметры сборки — черновик рядом с текстом (`verstka.brief_draft`, ключ `params`).
 *  - `slides`: null — степпер не трогали (12).
 *  - `strategies`: выбранные варианты; пусто — все.
 *  - `purpose`: значение `PURPOSES` или `OWN` («Свой вариант…»: тип — `ownPurpose`).
 *  - `eyes`: «Модель проверяет слайды по картинке» — взгляд дизайнера; null — не трогали: как модель (`eyesOn`).
 *  - `pictures`: «С изображениями»; null — не трогали: как у сервера (`picturesOn`).
 *  - `fonts`: «Подобрать шрифты» — шаблону со стандартными шрифтами пара под его характер (по умолчанию включён). */
export interface Params {
  slides: number | null; strategies: string[]; audience: string; purpose: string; ownPurpose: string;
  useModels: boolean; eyes: boolean | null; pictures: boolean | null; fonts: boolean;
}

/** «Свой вариант…» в списке типов. */
export const OWN = "own";

/** По умолчанию — как V2: 12 слайдов, все варианты, тип «Продукт», модель пишет тексты; взгляд дизайнера — как модель,
 *  изображения — как у сервера. */
export const PARAMS0: Params = { slides: null, strategies: [], audience: "", purpose: "product", ownPurpose: "", useModels: true, eyes: null, pictures: null, fonts: true };

const clampSlides = (n: number) => Math.min(SLIDES_MAX, Math.max(SLIDES_MIN, Math.round(n)));
const isPurpose = (v: unknown): v is string => v === OWN || PURPOSES.some((p) => p.value === v);

/** Параметры из черновика: испорченное поле — значение по умолчанию, годные остаются. */
export function readParams(raw: unknown): Params {
  const d = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const bool = (v: unknown, def: boolean) => (typeof v === "boolean" ? v : def);
  const choice = (v: unknown) => (typeof v === "boolean" ? v : null);
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const slides = typeof d.slides === "number" && Number.isInteger(d.slides) && d.slides >= SLIDES_MIN && d.slides <= SLIDES_MAX ? d.slides : null;
  const strategies = Array.isArray(d.strategies) && d.strategies.every((x) => typeof x === "string") ? (d.strategies as string[]) : [];
  return {
    slides, strategies, audience: str(d.audience), purpose: isPurpose(d.purpose) ? d.purpose : PARAMS0.purpose, ownPurpose: str(d.ownPurpose),
    useModels: bool(d.useModels, PARAMS0.useModels), eyes: choice(d.eyes), pictures: choice(d.pictures), fonts: bool(d.fonts, PARAMS0.fonts),
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

/** «Модель проверяет слайды по картинке» (взгляд дизайнера, `eyes`). Пока человек его не трогал — как модель: включён,
 *  когда модель подключена и пишет тексты (так и сервер: `eyes` null — по `use_models`). Тронул — его выбор. Без модели
 *  выключен. */
export const eyesOn = (p: Params, modelOn: boolean): boolean => modelOn && (p.eyes ?? p.useModels);
/** Нажатие: выбор человека — противоположность тому, что он видел; дальше переключатель от модели не зависит. */
export const toggleEyes = (p: Params, modelOn: boolean): Params => ({ ...p, eyes: !eyesOn(p, modelOn) });

/** Модель изображений (`health.images`): есть ли ключ и генерирует ли сервер изображения по умолчанию. */
export interface ImagesInfo { configured: boolean; enabled: boolean }
/** «С изображениями»: пока человек не трогал — как у сервера (`enabled`); без модели изображений выключен. */
export const picturesOn = (p: Params, images: ImagesInfo): boolean => images.configured && (p.pictures ?? images.enabled);
export const togglePictures = (p: Params, images: ImagesInfo): Params => ({ ...p, pictures: !picturesOn(p, images) });
/** «VK Tech · 12 слайдов · 3 варианта» (V2 `summary`); без шаблона — без его имени. */
export function summaryLine(tpl: string | null, count: number, variants: number): string {
  return [tpl, plural(count, "слайд", "слайда", "слайдов"), plural(variants, "вариант", "варианта", "вариантов")].filter(Boolean).join(" · ");
}
/** Телефон (доска M-create): подпись строки «Параметры» — кто пишет тексты и будут ли изображения. */
export function paramsBrief(writes: boolean, pictures: boolean): string {
  return `${writes ? "тексты пишет модель" : "ваш текст дословно"} · ${pictures ? "с изображениями" : "без изображений"}`;
}
export const writesHint = (on: boolean) => (on ? "Сокращает и переформулирует текст под слайды" : "Ваш текст дословно: только раскладка по слайдам шаблона");
export const fontsHint = (on: boolean) => (on ? "Пара под характер шаблона; свой шрифт шаблона не меняется" : "Шрифты шаблона как есть");
export const imagesHint = (on: boolean) => (on ? "По описаниям в тексте, в палитре шаблона" : "Места под изображения останутся свободными");

// ── «Изменить текст»: параметры собранной презентации
/** Презентацию соберут так, как собрали: её аудитория, тип, число слайдов, переключатели и варианты.
 *  - Числа слайдов нет — его читали из текста: степпер «не трогали» (null), а не прежнее число черновика.
 *  - Вариантов нет — все.
 *  - Взгляд дизайнера — `eyes`; у старых презентаций его нет — `auditModels` (переключатель тогда значил его);
 *    `eyes` null без `auditModels` — как модель (null).
 *  - Изображения null — как решит сервер (null).
 *  Переключателей, которых в параметрах нет, — как было. */
export function presetParams(p: Params, preset: ComposerPreset): Params {
  const out: Params = { ...p, audience: preset.audience ?? "" };
  const purpose = preset.purpose?.trim();
  if (purpose) {
    if (PURPOSES.some((x) => x.value === purpose)) out.purpose = purpose;
    else Object.assign(out, { purpose: OWN, ownPurpose: purpose });
  }
  out.slides = preset.slides ? clampSlides(preset.slides) : null;
  out.strategies = preset.strategies?.length ? [...preset.strategies] : [];
  if (typeof preset.useModels === "boolean") out.useModels = preset.useModels;
  const eyes = preset.eyes ?? preset.auditModels;
  if (typeof eyes === "boolean") out.eyes = eyes;
  // взгляд «как у модели» (сервер решал сам) — так же и в параметрах, а не прежний выбор человека
  else if (preset.eyes === null) out.eyes = null;
  if (preset.pictures !== undefined) out.pictures = preset.pictures;
  if (typeof preset.pickFonts === "boolean") out.fonts = preset.pickFonts;
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
  /** Модель изображений (`health.images`): ключа нет — решает сервер. */
  images: ImagesInfo;
  /** «Улучшить готовую»: исходная презентация, пока режим живёт. */
  improve: ImproveSource | null;
  /** Вторая ступень: наборы данных, брендбук и что важнее (dataRules `dataRequest`; пусто — полей нет). */
  data?: DataRequest;
  /** База знаний (kbRules `kbRequest`): с документами — её id. */
  knowledge?: { knowledge_id?: string };
}

/** Запрос сборки (POST /api/generations):
 *  - число слайдов, заданное в тексте заголовками «Слайд N», отправляется; заданное фразой («не более 10 слайдов»)
 *    сервер читает сам по тем же правилам (planning/brief.py) — отправленное число перебило бы его чтение;
 *  - варианты — как у карточек: пока `/api/strategies` не ответил, три известных, а не пустой список;
 *  - «Модель проверяет слайды по картинке» — только взгляд дизайнера (`eyes`); проверки моделью (`audit_models`)
 *    выключены, как по умолчанию в Verstka 3.0;
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
    strategies: chosenStrategies(listOf(i.strategies), p.strategies),
    use_models: p.useModels && i.modelOn,
    audit_models: false,
    eyes: (eyesOn(p, i.modelOn) || !!src) && i.modelOn,
    pictures: i.images.configured ? picturesOn(p, i.images) : null,
    pick_fonts: p.fonts,
    autofix: true,
    exports: ["pdf", "html"],
    improved_from: src ? { name: src.name, slides: src.slides, template_id: src.template_id, audit: src.audit ?? null } : undefined,
    ...i.data,
    ...i.knowledge,
  };
}

/** Сборка уже идёт (задача `generate` в очереди или в работе): вторая не начинается поверх. */
export const buildRunning = (job: ActiveJob | null): boolean =>
  !!job && job.kind === "generate" && (job.status === "queued" || job.status === "running");

/** Сервер не начал сборку, а причину сказал не по-русски. */
export const START_FAILED = "Не удалось начать сборку — попробуйте ещё раз";
/** Так начинается строка области «Сборка», когда сервер не принял запрос (flows.ts `generationFlow` → `report`): запуск
 *  на «Создать» и «Собрать ещё раз» на экране «Сборка» (buildView) узнают отказ по ней. */
export const START_PREFIX = /^Не удалось начать сборку презентации:\s*/;

/** Неудача запуска для нажатия в `since` (Date.now()): только ответ сервера на этот запрос — строка «Не удалось начать
 *  сборку презентации: …», пришедшая после нажатия. Строка прежней сборки («Не получилось: …» — задача упала) и строка
 *  прежнего нажатия — не она. Причина — по-русски, без префикса; null — неудачи нет. */
export function startFailure(note: Notice | null | undefined, since: number | null): string | null {
  if (since === null || !note || note.kind !== "error" || note.at < since || !START_PREFIX.test(note.text)) return null;
  return humanError(note.text.replace(START_PREFIX, ""), START_FAILED);
}

/** Строка под сводкой: ошибка (поле пусто или коротко, нет шаблона, сервер не начал сборку; `echo` — она повторяет
 *  ошибку у поля «Текст», её читает та строка), тихая «Сборка уже идёт» со ссылкой «Вернуться к сборке» или тихий итог
 *  сборки, кончившейся без человека на её экране: «Сборка готова · Открыть», «Сборка не удалась · Посмотреть». */
export type HeadLine = { kind: "error"; text: string; echo: boolean } | { kind: "busy" } | { kind: "ended"; ok: boolean; failed: boolean };

/** Какая строка стоит под сводкой: «Сборка уже идёт» (нажали «Создать», пока идёт сборка) сильнее ошибки, ошибка —
 *  итога сборки, кончившейся в другом месте; итог — тихий, он ждёт, пока его увидят (`failed` — её презентация не
 *  открылась: «Не удалось открыть презентацию · Открыть ещё раз»). */
export function headLine(o: { busy: boolean; bad: string | null; echo: boolean; ended: { ok: boolean } | null; openFailed?: boolean }): HeadLine | null {
  if (o.busy) return { kind: "busy" };
  if (o.bad !== null) return { kind: "error", text: o.bad, echo: o.echo };
  return o.ended ? { kind: "ended", ok: o.ended.ok, failed: o.ended.ok && !!o.openFailed } : null;
}
