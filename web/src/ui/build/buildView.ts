// Экран «Сборка» как данные: из задачи сборки (ActiveJob — поток событий, свёрнутый foldJobEvent) и готовых превью
// слайдов — что пишет заголовок плиты 03 (фаза), часы и полоса хода, раскадровка выбранного варианта (карточка на
// слайд: заглушка → эскиз → «Замечание» → «Переделан» → сверстан → превью), девять ролей агента со статусом и строками,
// неудача. Чистые функции, без React; разметку и движение даёт BuildPlate (boards/V2.dc.html, модуль bd).
import { buildTimeline, eventParts, laterPhase, PHASES, phaseOfStep, phaseOrder, type PhaseKey, type TimelineEvent, type TimelineRow } from "../../lib/agent";
import { humanError } from "../../lib/errors";
import type { ActiveJob } from "../../lib/jobState";
import { failReason } from "../../lib/narrate";
import { clock as clockText, KIND_LABEL, railSlides, sketchOf, STAGE_TITLE, type RailSlide, type SketchKind } from "../../lib/stage";
import { plural } from "../../lib/utils";
import { START_FAILED } from "../create/params";
import type { AgentEvent } from "../../types";

/** Фаза сборки на экране: очередь, одна из девяти ролей, готово или остановилась. */
export type BuildPhase = PhaseKey | "queued" | "done" | "failed";
/** Порядок, в котором фазы сменяют друг друга в заголовке (V2 `PH`): прошедшие уходят вверх, следующие ждут снизу. */
export const PHASE_ROLL: BuildPhase[] = ["queued", ...PHASES.map((p) => p.key), "done", "failed"];

/** Карточка раскадровки: пусто → эскиз формы → замечание критика → переделан → сверстан → настоящее превью. */
export type CardState = "empty" | "sketch" | "critic" | "revised" | "laid" | "done";
export interface CardView {
  n: number;
  state: CardState;
  /** Форма эскиза (lib/stage `sketchKind`); null — дизайнер слайд ещё не продумал. */
  kind: SketchKind | null;
  /** На слайде формула (строка дизайнера её называет): эскиз текста рисуется с формулой. */
  formula: boolean;
  /** Подпись под карточкой — название формы («Карточки»). */
  form: string | null;
  /** Заголовок слайда из строки дизайнера («…» в кавычках). */
  title: string | null;
  /** Превью сверстанного слайда (состояние done). */
  preview: string | null;
  /** О нём сейчас говорит агент или он сейчас верстается: рамка 2 px. */
  focus: boolean;
  /** Сейчас верстается: бегущая полоска по нижнему краю. */
  work: boolean;
}

export type RoleStatus = "queue" | "now" | "done" | "skip" | "error";
/** Мысль агента под ролью: «Слайд 4: нет обозначений → подписи a, b, f(x)». */
export interface RoleLine { key: string; slide: number | null; text: string; fix: string | null }
export interface RoleView {
  key: PhaseKey;
  /** Номер роли 1..9. */
  n: number;
  title: string;
  /** Полная подсказка роли (лента очереди B-start). */
  hint: string;
  status: RoleStatus;
  /** Строка рядом с именем: «· 3 замечания · слайды 4, 9», подсказка, пока роль впереди, или «в этой сборке не
   *  запускалась». */
  note: string;
  /** Последние мысли роли (не больше трёх), пока она работает или после. */
  lines: RoleLine[];
}

/** Сегмент варианта над раскадровкой: «продумываю», «продумано», «верстаю», «сверстано» (null — плана ещё нет). */
export interface VariantView { name: string; status: string | null; done: boolean; tip: string }

export interface BuildView {
  phase: BuildPhase;
  title: string;
  /** «1:12» — от начала сборки; у законченной стоит на конце. */
  clock: string;
  /** Доля хода 0..1; null — хода ещё нет (бежит отрезок). */
  progress: number | null;
  /** Сколько ролей готово (полоса хода для чтения с экрана: из девяти). */
  doneRoles: number;
  /** Справа от «Как думает агент»: «в очереди», «шаг 5 из 9», «9 из 9 готово», «ошибка на шаге 5 из 9». */
  step: string;
  /** Вариант, чья раскадровка показана. */
  variant: string | null;
  variants: VariantView[];
  /** План есть: у карточек номера (до плана — безымянные заглушки). */
  planned: boolean;
  /** «план ещё не готов», «продумано 7 из 12», «сверстано 3 из 12». */
  board: string;
  cards: CardView[];
  roles: RoleView[];
  /** Сборка остановилась: роль, на которой, и почему — простыми словами. */
  failed: { role: PhaseKey; text: string } | null;
}

export interface BuildViewOptions {
  /** Вариант, который выбрали в сегментах; нет такого — первый. */
  variant?: string | null;
  /** Сейчас, мс (часы идущей сборки). */
  now?: number;
  /** Строка неудачи области «Сборка» («Не получилось: …») — она переживает задачу; без неё — сообщение задачи. */
  error?: string | null;
  /** Название варианта по имени («structured» → «Структурный»). */
  titleOf?: (name: string) => string;
}

/** Причины, сказанные не по-русски, — так же, как lib/narrate `failReason`. */
const FAIL_FALLBACK = failReason(null).replace(/[.\s]+$/, "");
const FAIL_PREFIX = /^(?:Не получилось|Не удалось начать сборку презентации):\s*/;
/** «Собрать ещё раз» не приняли (flows.ts `generationFlow` → `report`). */
const START_PREFIX = /^Не удалось начать сборку презентации:/;
/** До плана, пока число слайдов неизвестно, — десять заглушек (B-start). */
const GHOSTS = 10;
const LINES = 3;
const SHORT_HINT: Partial<Record<PhaseKey, string>> = { eyes: "смотрит, как арт-директор" };
const FEMININE = new Set<PhaseKey>(["revise", "layout", "check"]);
const notRun = (key: PhaseKey) => `в этой сборке не запускал${FEMININE.has(key) ? "ась" : "ся"}`;
const AGENT_AT = new Set<BuildPhase>(["designer", "critic", "revise"]);

const clamp01 = (n: number) => Math.min(1, Math.max(0, Number.isFinite(n) ? n : 0));
const at = (key: PhaseKey) => phaseOrder(key);

/** Варианты сборки: из запроса, иначе — какие назвал поток. */
function variantNames(job: ActiveJob): string[] {
  if (job.items?.length) return job.items;
  const seen = new Set<string>(Object.keys(job.variants ?? {}));
  for (const e of job.agent ?? []) if (e.variant) seen.add(e.variant);
  return [...seen];
}

/** Число слайдов из слов агента («Нашёл в тексте 11 слайдов», «Написал текст: 11 слайдов») — для заглушек до плана. */
function saidCount(events: AgentEvent[]): number | null {
  let n: number | null = null;
  for (const e of events) {
    const step = (e.step ?? "").toLowerCase();
    if (step !== "analyst" && step !== "writer") continue;
    const m = e.message.match(/(\d+)(?:\s| )+слайд/);
    if (m) n = Number(m[1]);
  }
  return n;
}

/** Слайды, у которых строка дизайнера или правки называет формулу (эскиз текста рисуется с формулой). */
function formulaSlides(events: AgentEvent[], variant: string | null): Set<number> {
  const said = new Map<number, boolean>();
  for (const e of events) {
    const step = (e.step ?? "").toLowerCase();
    if ((step !== "designer" && step !== "revise") || !e.slide || (e.variant != null && e.variant !== variant)) continue;
    if (step === "revise" && !sketchOf(e)) continue; // правка, которая не называет форму, эскиз не меняет
    said.set(e.slide, /формул/i.test(e.message));
  }
  return new Set([...said].filter(([, f]) => f).map(([n]) => n));
}

/** Превью варианта по номеру слайда: «…/slide-003.jpg» → 3. */
function previewMap(list: string[] | undefined): Map<number, string> {
  const out = new Map<number, string>();
  for (const url of list ?? []) {
    const n = Number(url.match(/slide-(\d+)/)?.[1] ?? NaN);
    if (Number.isFinite(n)) out.set(n, url);
  }
  return out;
}

const order = (e: TimelineEvent, i: number) => e.seq ?? e.t ?? i;

/** Последние мысли роли — по порядку, в каком они пришли. */
function recentLines(row: TimelineRow | undefined): RoleLine[] {
  if (!row) return [];
  const recent = row.events.map((e, i) => ({ e, k: order(e, i) })).sort((a, b) => a.k - b.k).slice(-LINES);
  const title = PHASES.find((p) => p.key === row.key)?.title ?? "";
  return recent.map(({ e, k }) => {
    const { text: said, fix } = eventParts(e);
    // «Вёрстка: слайд 3 — рисую изображение…» под ролью «Вёрстка» с меткой «Слайд 3»: имя роли и номер уже есть
    let text = said.startsWith(`${title}: `) ? said.slice(title.length + 2) : said;
    if (e.slide != null) text = text.replace(new RegExp(`^слайд(?:\\s|\\u00a0)+${e.slide}(?:\\s|\\u00a0)*[—–:-]\\s*`, "i"), "");
    text = text ? text.charAt(0).toUpperCase() + text.slice(1) : said;
    return { key: `${k}-${e.slide ?? ""}-${e.variant ?? ""}`, slide: e.slide ?? null, text, fix };
  });
}

function cardState(s: RailSlide, preview: string | null): CardState {
  if (preview) return "done";
  if (s.laid) return "laid";
  if (s.mark === "fixed") return "revised";
  if (s.mark === "note") return "critic";
  return s.sketch ? "sketch" : "empty";
}

export function buildView(job: ActiveJob, previews: Record<string, string[]>, opts: BuildViewOptions = {}): BuildView {
  const now = opts.now ?? Date.now();
  const titleOf = opts.titleOf ?? ((n: string) => n);
  const events = job.agent ?? [];
  const names = variantNames(job);
  const done = job.status === "done";
  const failedJob = job.status === "failed";
  const running = !done && !failedJob;

  // варианты верстаются один за другим: проверка первого (и взгляд дизайнера на него) не заканчивает «Вёрстку»
  // остальных, пока сборка идёт
  const exporting = /^сохраняю файлы/i.test(job.message);
  const laying = running && !exporting && names.some((n) => (job.variants?.[n]?.frac ?? 0) < 0.75);
  // разбор шаблона («analyze: …») идёт раньше автора: пока аналитик не сказал ни слова, а автор пишет — работает автор
  const spoken = events.reduce<PhaseKey | null>((p, e) => laterPhase(p, phaseOfStep(e.step)), null);
  const reached = job.phase === "analyst" && spoken === "writer" ? "writer" : job.phase ?? null;
  const agentPhase: PhaseKey | null = (reached === "check" || reached === "eyes") && laying ? "layout" : reached;
  const phase: BuildPhase = failedJob ? "failed" : done ? "done" : agentPhase ?? "queued";
  const queued = phase === "queued";

  // ── роли: строки ленты (lib/agent buildTimeline) на все девять ролей
  const shownName = names.find((n) => n === opts.variant) ?? names[0] ?? null;
  const layingVariant = names.map((n) => ({ n, st: job.variants?.[n] })).find(({ st }) => st && st.of !== undefined && (st.laid ?? 0) < st.of && !st.done);
  // «Вёрстка»: какой вариант и сколько слайдов сверстано, а когда вёрстка позади — сколько вариантов собрано
  const layoutPast = !running || (!!agentPhase && at(agentPhase) > at("layout"));
  const layoutNote = agentPhase === "layout" && layingVariant?.st
    ? `${names.length > 1 ? `${titleOf(layingVariant.n)} · ` : ""}${layingVariant.st.laid ?? 0} из ${layingVariant.st.of}`
    : layoutPast && names.length ? plural(names.length, "вариант", "варианта", "вариантов") : undefined;
  const checkNote = agentPhase === "check" && /проверка качества|исправляю замечания|сохраняю файлы/i.test(job.message) ? job.message : undefined;
  const rows = buildTimeline({ events, phase: agentPhase, running: !done, notes: { layout: layoutNote, check: checkNote } });
  const rowOf = (key: PhaseKey) => rows.find((r) => r.key === key);
  const activeKey = rows.find((r) => r.status === "active")?.key ?? (running && agentPhase ? agentPhase : null);
  const failedKey: PhaseKey | null = failedJob ? activeKey ?? agentPhase ?? "analyst" : null;

  const roles: RoleView[] = PHASES.map((def, i) => {
    const row = rowOf(def.key);
    const hint = def.hint;
    const short = SHORT_HINT[def.key] ?? hint;
    let status: RoleStatus;
    if (queued) status = "queue";
    else if (failedKey) status = def.key === failedKey ? "error" : at(def.key) > at(failedKey) ? "skip" : row?.status === "done" ? "done" : "skip";
    else if (done) status = row && row.status !== "skipped" ? "done" : "skip";
    else if (row) status = row.status === "done" ? "done" : row.status === "active" ? "now" : row.status === "skipped" ? "skip" : "queue";
    else status = def.key === activeKey ? "now" : activeKey && at(def.key) < at(activeKey) ? "skip" : "queue";
    const lines = status === "queue" || status === "skip" ? [] : recentLines(row);
    const said = row?.note ? `· ${row.note}` : "";
    let note: string;
    if (status === "queue") note = short;
    else if (status === "skip") note = !failedKey && row?.status === "skipped" && row.note ? row.note : notRun(def.key);
    else if (status === "now") note = said || (lines.length ? "" : short);
    else note = said;
    return { key: def.key, n: i + 1, title: def.title, hint, status, note, lines };
  });
  const doneRoles = roles.filter((r) => r.status === "done").length;
  const nowIdx = roles.findIndex((r) => r.status === "now" || r.status === "error");
  const step = queued ? "в очереди" : done ? `${PHASES.length} из ${PHASES.length} готово`
    : failedKey ? `ошибка на шаге ${at(failedKey) + 1} из ${PHASES.length}`
    : `шаг ${(nowIdx >= 0 ? nowIdx : agentPhase ? at(agentPhase) : 0) + 1} из ${PHASES.length}`;

  // ── раскадровка выбранного варианта
  const own = shownName ? job.variants?.[shownName] : undefined;
  const exact = own?.of !== undefined;
  const count = own?.of ?? job.slides ?? saidCount(events) ?? 0;
  const laidN = done || exporting ? own?.of ?? own?.laid ?? 0 : own?.laid ?? 0;
  const rail = railSlides(events, shownName, count, laidN, exact);
  const planned = exact || rail.some((s) => s.sketch);
  const shots = previewMap(shownName ? previews[shownName] : undefined);
  const formulas = formulaSlides(events, shownName);
  const layingShown = running && agentPhase === "layout" && !!own && exact && !own.done && (own.laid ?? 0) < (own.of ?? 0);
  const line = job.line ?? null;
  const about = running && AGENT_AT.has(phase) && line?.slide && (line.variant == null || line.variant === shownName) ? line.slide : null;
  const workOn = layingShown ? (own?.laid ?? 0) + 1 : null;
  const cards: CardView[] = planned
    ? rail.map((s) => {
      const preview = shots.get(s.n) ?? null;
      const kind = s.sketch?.kind ?? null;
      return {
        n: s.n, state: cardState(s, preview), kind, formula: formulas.has(s.n), form: kind ? KIND_LABEL[kind] : null,
        title: s.sketch?.headline ?? null, preview, focus: s.n === (workOn ?? about), work: s.n === workOn,
      };
    })
    : Array.from({ length: rail.length || GHOSTS }, (_, i) => ({
      n: i + 1, state: "empty" as const, kind: null, formula: false, form: null, title: null, preview: null, focus: false, work: false,
    }));
  const layoutMode = exact || done || (!!agentPhase && at(agentPhase) >= at("layout"));
  const total = cards.length;
  const board = !planned ? "план ещё не готов"
    : layoutMode ? `сверстано ${rail.filter((s) => s.laid).length} из ${total}`
    : `продумано ${rail.filter((s) => s.sketch).length} из ${total}`;

  // ── сегменты вариантов
  const variants: VariantView[] = names.map((name) => {
    const st = job.variants?.[name];
    const own = st?.of !== undefined;
    let status: string | null;
    let fin = false;
    if (done) {
      status = "сверстано";
      fin = true;
    } else if (own || layoutMode) {
      fin = own && (st?.laid ?? 0) >= (st?.of ?? 0) && (st?.of ?? 0) > 0;
      status = fin ? "сверстано" : "верстаю";
    } else {
      const r = railSlides(events, name, st?.of ?? job.slides ?? 0, 0, false);
      const sk = r.filter((s) => s.sketch).length;
      fin = sk > 0 && sk >= r.length;
      status = sk ? (fin ? "продумано" : "продумываю") : null;
    }
    const tip = queued ? "в очереди"
      : status === null ? "ждёт плана"
      : status === "верстаю" ? "верстаю слайды"
      : status === "продумываю" ? "продумываю слайды"
      : status === "продумано" && phase === "critic" ? "проверяет критик"
      : status === "продумано" && phase === "revise" ? "правка по замечаниям"
      : status;
    return { name, status, done: fin, tip };
  });

  const why = opts.error ?? job.message ?? "";
  const fallback = START_PREFIX.test(why) ? START_FAILED : FAIL_FALLBACK;
  const failed = failedKey ? { role: failedKey, text: humanError(why.replace(FAIL_PREFIX, ""), fallback).replace(/[.\s]+$/, "") } : null;

  return {
    phase,
    title: STAGE_TITLE[phase],
    clock: clockText(((job.endedAt ?? now) - job.startedAt) / 1000),
    progress: queued ? null : done ? 1 : clamp01(job.progress),
    doneRoles,
    step,
    variant: shownName,
    variants,
    planned,
    board,
    cards,
    roles,
    failed,
  };
}
