// Помощник без React (boards/G-helper, G-helper-open, V2 модуль `hp`): что делает действие ответа сервера с экраном,
// как лента собирается из сообщений и задач, как пузырь ответа делится на абзацы и список, какие подсказки и какое
// приветствие стоят, тексты неудач. Логика действий — из версии до «Слоёв» (79c6f81), переписанная под `dispatch`.
import { ApiError } from "../../api";
import { hasCyrillic, humanError } from "../../lib/errors";
import { plural } from "../../lib/utils";
import type { ChatAction, ChatMessage, ChatResponse, EditResult, FixResult } from "../../types";
import type { Screen, SheetTab, UiAction } from "../deck/geometry";

// ── open_tab: имена вкладок сервера (старый интерфейс) → шаги экрана «Слоёв»
/** Вкладки листа «Подробнее» по старым именам: «Качество» звалось audit, «Файлы» — export и run. */
const SHEET_OF: Record<string, SheetTab> = { audit: "quality", why: "why", plan: "plan", agent: "agent", export: "files", run: "files" };

/** Шаги экрана для `open_tab` (бывший `store.setTab`): лист «Подробнее» — на результате (с другого экрана сначала
 *  результат); «template» — вкладка «Шаблон» открытой презентации, а на «Создать» — шаг «Шаблон» (там речь о выбранном
 *  шаблоне); «brief» — шаг «Текст»; «variants» — результат без листа. Без презентации листа нет. */
export function openTabSteps(tab: string, ctx: { screen: Screen; hasDeck: boolean }): UiAction[] {
  const toResult: UiAction[] = ctx.screen === "result" ? [] : [{ type: "go", screen: "result" }];
  if (tab === "template") {
    if (ctx.screen === "result" && ctx.hasDeck) return [{ type: "sheet", tab: "template" }];
    return ctx.screen === "create" ? [{ type: "open", step: "tpl" }] : [];
  }
  if (tab === "brief") return ctx.screen === "create" ? [{ type: "open", step: "text" }] : [{ type: "go", screen: "create" }];
  if (!ctx.hasDeck) return [];
  if (tab === "variants") return ctx.screen === "result" ? [{ type: "sheet", tab: null }] : toResult;
  const sheet = SHEET_OF[tab];
  return sheet ? [...toResult, { type: "sheet", tab: sheet }] : [];
}

// ── действия ответа: только для презентации, о которой ответ
export type EditAction = Extract<ChatAction, { type: "edit" }>;
/** Что делает ответ: `build` — экран «Сборка» ведёт новую сборку; `edit` — задача правки над своей презентацией;
 *  `fixes` — задачи «Исправь всё» над презентацией ответа; `open` — шаги экрана (лист «Подробнее» и слайд). */
export type Plan =
  | { kind: "build"; gid: string; job: string }
  | { kind: "edit"; action: EditAction }
  | { kind: "fixes"; jobs: { strategy: string; job_id: string }[]; gid: string | null }
  | { kind: "open"; steps: UiAction[]; slide: number | null };

export interface PlanCtx {
  /** Презентация, о которой спросили (открытая в момент вопроса). */
  sent: string | null;
  /** Презентация, открытая сейчас (ответ мог прийти, когда уже открыли другую). */
  open: string | null;
  screen: Screen;
  /** У открытой презентации есть варианты. */
  hasDeck: boolean;
}

/** Действия ответа по шагам. Ответ — о презентации, которую назвал сервер, а если не назвал — о той, про которую
 *  спросили. Пока ждали ответ, открыли другую — лист и слайд не открываются (они были бы о чужой); правка идёт над
 *  своей презентацией (её id — в действии), исправления — над презентацией ответа: о том, что она не открыта, скажет
 *  лента, когда задача кончится. */
/** О какой презентации вопрос помощнику — о той, что на экране: на результате — открытая, её вариант и слайд; на
 *  «Сборке» — собираемая (без варианта и слайда); на «Создать» — никакая (последняя открытая там не видна, и правка
 *  ушла бы в презентацию, которой на экране нет). */
export function chatTarget(o: { screen: Screen; open: string | null; strategy: string | null; slide: number | null; building: string | null }): {
  generation_id: string | null; strategy: string | null; slide: number | null;
} {
  if (o.screen === "result" && o.open) return { generation_id: o.open, strategy: o.strategy, slide: o.slide };
  if (o.screen === "build" && o.building) return { generation_id: o.building, strategy: null, slide: null };
  return { generation_id: null, strategy: null, slide: null };
}

export function planActions(res: ChatResponse, ctx: PlanCtx): Plan[] {
  const gid = res.generation_id ?? ctx.sent;
  const same = !gid || gid === ctx.open;
  const out: Plan[] = [];
  for (const a of res.actions ?? []) {
    if (a.type === "generation_started") out.push({ kind: "build", gid: a.generation_id, job: a.job_id });
    else if (a.type === "edit") out.push({ kind: "edit", action: a });
    else if (a.type === "jobs") {
      if (a.jobs?.length) out.push({ kind: "fixes", jobs: a.jobs, gid });
    } else if (a.type === "open_tab" && same) {
      const hasDeck = ctx.hasDeck;
      const steps = openTabSteps(a.tab, { screen: ctx.screen, hasDeck });
      const slide = a.slide && hasDeck ? a.slide : null;
      if (steps.length || slide) out.push({ kind: "open", steps, slide });
    }
  }
  return out;
}

// ── результаты задач, начатых из чата
/** Ответ задачи правки (`edit`) или изображения (`picture`): у обеих — reply, changed, slide, strategy. */
export function asEditResult(value: unknown): EditResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Partial<EditResult>;
  return typeof r.reply === "string" ? { reply: r.reply, changed: !!r.changed, slide: r.slide ?? null, strategy: r.strategy, score: r.score ?? null, kind: r.kind } : null;
}

/** Результат задачи исправлений (`fix`) — только когда он и правда похож на FixResult. */
export function asFixResult(value: unknown): FixResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Partial<FixResult>;
  if (typeof r.score !== "number") return null;
  return { score: r.score, errors: Number(r.errors ?? 0), warnings: Number(r.warnings ?? 0), applied: Array.isArray(r.applied) ? r.applied : [] };
}

export interface FixOutcome { strategy: string; before: number | null; done: boolean; result: FixResult | null; error: string | null }

/** Причина неудачи для ленты: по-русски, без технического хвоста; не осталось русского — пусто. */
const reasonOf = (raw: string | null | undefined): string => {
  const t = humanError(raw, "");
  return t ? t[0].toLowerCase() + t.slice(1) : "";
};

/** Итог «Исправь всё» (как прежде): строка на вариант — оценка было → стало, ошибки, предупреждения. */
export function describeFixes(list: FixOutcome[], title: (name: string) => string): string {
  const ok = list.filter((o) => o.done).length;
  const rows = list.map((o) => {
    if (!o.done) {
      const why = humanError(o.error, "");
      return `• ${title(o.strategy)} — не получилось${why ? `: ${why}` : ""}`;
    }
    if (!o.result) return `• ${title(o.strategy)} — исправления применены`;
    const after = Math.round(o.result.score);
    const before = o.before === null ? null : Math.round(o.before);
    const parts = [before !== null && before !== after ? `оценка ${before} → ${after}` : `оценка ${after}`];
    parts.push(o.result.errors === 0 ? "без ошибок" : plural(o.result.errors, "ошибка", "ошибки", "ошибок"));
    if (o.result.warnings) parts.push(plural(o.result.warnings, "предупреждение", "предупреждения", "предупреждений"));
    return `• ${title(o.strategy)} — ${parts.join(", ")}`;
  });
  const head = ok === list.length
    ? `Исправления готовы: ${list.length === 1 ? "вариант обновлён" : `${plural(list.length, "вариант", "варианта", "вариантов")} обновлены`}.`
    : ok > 0 ? `Исправлено ${ok} из ${list.length} вариантов.` : "Исправить автоматически не получилось.";
  const tail = ok > 0 ? "Слайды и файлы пересобраны, оставшиеся замечания — в «Подробнее» на вкладке «Качество»."
    : "Попробуйте исправить замечания по одному — в режиме «Замечания» на слайде.";
  return [head, ...rows, tail].join("\n");
}

/** Неудача правки или изображения из чата: причина по-русски (humanError), без технического хвоста. */
export function editFailText(raw: string | null | undefined): string {
  const why = reasonOf(raw);
  return `Не получилось поменять${why ? `: ${why}` : ""}. Попробуйте сказать иначе или повторите позже.`;
}

/** Правка или исправления готовы, а презентация не перечиталась (связь, сервер): причина по-русски; «это другая
 *  презентация» здесь не годится — она открыта. Рядом со строкой — «Обновить» (перечитать её ещё раз); «Мои
 *  презентации» тоже перечитывают такую презентацию (history `openPlan`). */
export function reloadFailText(e: unknown): string {
  const why = e instanceof ApiError && e.status === 0 ? "нет связи с сервером" : reasonOf(e instanceof Error ? e.message : String(e ?? "")).replace(/[.\s]+$/, "");
  return `Изменения сохранены, но презентация на экране не обновилась${why ? `: ${why}` : ""}.`;
}

/** Строка ленты после «Обновить»: презентация перечиталась, изменения на экране. */
export const REFRESHED = "Презентация на экране обновлена.";

/** Правка или исправления сделаны в презентации, которая сейчас не открыта: тихая строка в ленте. */
export const OTHER_DECK = "Это другая презентация — откройте её из «Мои презентации».";

/** Ответ не пришёл: нет связи — просьба повторить; иначе причина по-русски (английская — общая фраза). */
export function chatFailText(e: unknown): string {
  if (e instanceof ApiError && e.status === 0) return "Не получилось ответить: нет связи с сервером. Повторите, когда связь вернётся.";
  const raw = e instanceof Error ? e.message : String(e);
  if (!hasCyrillic(raw)) return "Не получилось ответить. Попробуйте ещё раз.";
  const why = reasonOf(raw).replace(/[.\s]+$/, "");
  return why ? `Не получилось ответить: ${why}.` : "Не получилось ответить. Попробуйте ещё раз.";
}

// ── пузырь ответа
export type Block = { kind: "p"; text: string } | { kind: "ul"; items: string[] };
const BULLET = /^\s*[•·-]\s+/;

/** Ответ помощника по блокам (G-helper `gh-ul`): строки «• », «· », «- » — пункты списка, остальные — абзацы;
 *  пустые строки — только разделители. Тире «— » в начале строки — речь, не пункт. */
export function bubbleBlocks(text: string): Block[] {
  const out: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const b = BULLET.exec(raw);
    if (b) {
      const item = raw.slice(b[0].length).trim();
      const last = out[out.length - 1];
      if (last && last.kind === "ul") last.items.push(item);
      else out.push({ kind: "ul", items: [item] });
    } else out.push({ kind: "p", text: line });
  }
  return out;
}

/** Русская вёрстка ответа (как прежде): «900 000», «слайд 5», «6 категорий», «в тексте», «— вывод» не
 *  разрываются переносом; одно- и двухбуквенное слово не остаётся в конце строки. */
export function typeset(text: string): string {
  return text
    .replace(/(\d) (?=\d{3}(?!\d))/g, "$1 ")
    .replace(/(слайд\S*) (\d)/gi, "$1 $2")
    .replace(/(\d) (?=[а-яё%₽])/gi, "$1 ")
    .replace(/(?<=^|[\s(«])(в|во|и|к|ко|с|со|на|не|но|по|о|об|у|за|из|от|до|а|я) /gi, "$1 ")
    .replace(/ ([—–]) /g, " $1 ");
}

// ── лента
/** Задача, начатая из чата (правка, изображение, исправления): полоса в ленте («Меняю презентацию 100 %»). */
export interface FeedJob { id: string; label: string; ts: number; progress: number; status: "run" | "done" | "failed" }
/** Тихая строка ленты (не ответ помощника): «Это другая презентация — откройте её из «Мои презентации»». `refresh` —
 *  презентация, которую изменили, а она не перечиталась: у строки «Обновить» (noteView). */
export interface FeedNote { id: string; text: string; ts: number; refresh?: string }

/** Самая новая строка ленты о неперечитанной презентации `gid` — только она живая (`noteView`). */
export function latestRefreshNote(notes: FeedNote[], gid: string | null | undefined): string | null {
  if (!gid) return null;
  for (let i = notes.length - 1; i >= 0; i--) if (notes[i].refresh === gid) return notes[i].id;
  return null;
}

/** Что показывает строка ленты. Живая — только самая новая строка о неперечитанной презентации (`latest`): пока
 *  хранилище держит её несвежей — последняя причина и «Обновить»; перечиталась и открыта — «обновлена»; открыта другая —
 *  как была записана. Прежние строки о ней остаются такими, какими были записаны (без «Обновить»): в ленте одна живая
 *  строка, а не несколько одинаковых. */
export function noteView(note: FeedNote, o: { stale: { gid: string; text: string } | null; open: string | null; latest: boolean }): { text: string; refresh: boolean } {
  if (!note.refresh || !o.latest) return { text: note.text, refresh: false };
  if (o.stale && o.stale.gid === note.refresh) return { text: o.stale.text, refresh: true };
  return { text: o.open === note.refresh ? REFRESHED : note.text, refresh: false };
}
export type FeedItem = { kind: "msg"; msg: ChatMessage } | { kind: "job"; job: FeedJob } | { kind: "note"; note: FeedNote };

/** Ход полос по идущим задачам хранилища (`liveJobs`): у каждой задачи своя полоса, и растёт она по своей задаче
 *  («Исправь всё» — по задаче на вариант, они идут рядом), не назад. Нечего менять — тот же список. */
export function feedProgress(jobs: FeedJob[], live: { id: string; progress: number }[]): FeedJob[] {
  let changed = false;
  const next = jobs.map((j) => {
    const l = j.status === "run" ? live.find((x) => x.id === j.id) : undefined;
    if (!l || !(l.progress > j.progress)) return j;
    changed = true;
    return { ...j, progress: l.progress };
  });
  return changed ? next : jobs;
}

/** Сообщения, задачи и тихие строки по времени; при равном — сообщение раньше («Меняю…» стоит перед своей полосой,
 *  ответ — перед строкой о нём). */
export function feedItems(messages: ChatMessage[], jobs: FeedJob[], notes: FeedNote[] = []): FeedItem[] {
  const all: Array<FeedItem & { at: number; o: number }> = [
    ...messages.map((msg, i) => ({ kind: "msg" as const, msg, at: msg.ts, o: i })),
    ...jobs.map((job, i) => ({ kind: "job" as const, job, at: job.ts, o: messages.length + i })),
    ...notes.map((note, i) => ({ kind: "note" as const, note, at: note.ts, o: messages.length + jobs.length + i })),
  ];
  all.sort((a, b) => a.at - b.at || a.o - b.o);
  return all.map(({ at: _a, o: _o, ...item }) => item as FeedItem);
}

/** Задержка появления элемента ленты при открытии (G-helper-open): сообщения 200…400 мс по 40; в длинной ленте
 *  каскад у последних шести — они на виду, верхние входят первыми (200). Закрытие — без каскада: всё гаснет с плитой,
 *  а через 240 мс (плита уже не видна) сбрасывается, чтобы каскад повторился. */
export function feedDelay(i: number, n: number, open: boolean): number {
  if (!open) return 240;
  const k = i - Math.max(0, n - 6);
  return 200 + Math.max(0, Math.min(5, k)) * 40;
}

// ── подсказки, приветствие, поле
export interface ChipCtx {
  /** Ответ ещё не пришёл. */
  pending: boolean;
  /** Идёт сборка или задача из чата. */
  busy: boolean;
  /** В ленте ещё ничего не написано. */
  empty: boolean;
  /** Последняя правка изменила презентацию `gid`: её слайд (null — какой, неизвестно). */
  edited: Edited | null;
  /** На экране — результат с презентацией; `slide` — открытый слайд. */
  deck: boolean;
  /** Презентация на экране (результат); null — её нет («Создать», «Сборка»). */
  open: string | null;
  slide: number;
  template: boolean;
  /** Есть замечания, которые правятся сами («Исправь всё»). */
  fixable: boolean;
}

/** Правка из чата изменила презентацию `gid` (её слайд; null — какой, неизвестно). */
export interface Edited { gid: string; slide: number | null }

/** Подсказки под лентой (не больше двух): после правки — «Верни как было», пока на экране та презентация, которую
 *  изменили (на другой или без презентации они были бы о чужой); в пустой ленте — по месту. */
export function chipsFor(c: ChipCtx): string[] {
  if (c.pending || c.busy) return [];
  if (c.edited && c.edited.gid === c.open) return ["Верни как было", ...(c.edited.slide ? [`Почему слайд ${c.edited.slide} такой?`] : [])];
  if (!c.empty) return [];
  if (c.deck) return [`Почему слайд ${c.slide} такой?`, c.fixable ? "Исправь всё" : "Как работал агент?"];
  return c.template ? ["Что в шаблоне?", "Что ты умеешь?"] : ["Что ты умеешь?"];
}

/** Первое сообщение ленты — что здесь можно спросить. */
export function introFor(c: { building: boolean; deck: boolean }): string {
  if (c.building) return "Собираю презентацию — спросите, что сейчас делает агент.";
  return c.deck ? "Спросите про любой слайд или попросите его изменить." : "Спросите про шаблон или пришлите текст — соберу три варианта.";
}

/** Подсказка в поле: на результате — про открытый слайд (G-helper «Что поменять на слайде 3?»). */
export function placeholderFor(c: { screen: Screen; deck: boolean; slide: number }): string {
  if (c.screen === "build") return "Вопрос о сборке";
  return c.screen === "result" && c.deck ? `Что поменять на слайде ${c.slide}?` : "Вопрос или текст презентации";
}
