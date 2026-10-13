// Помощник без React (boards/G-helper, G-helper-open, V2 модуль `hp`): что делает действие ответа сервера с экраном,
// как лента собирается из сообщений и задач, как пузырь ответа делится на абзацы и список, какие подсказки и какое
// приветствие стоят, тексты неудач. Логика действий — из старого ChatActions.ts (79c6f81), переписанная под `dispatch`.
import { ApiError } from "../../api";
import { hasCyrillic, humanError } from "../../lib/errors";
import { plural } from "../../lib/utils";
import type { ChatMessage, EditResult, FixResult } from "../../types";
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

/** Итог «Исправь всё» (старый describeFixes): строка на вариант — оценка было → стало, ошибки, предупреждения. */
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

/** Русская вёрстка ответа (старый ChatParts): «900 000», «слайд 5», «6 категорий», «в тексте», «— вывод» не
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
export type FeedItem = { kind: "msg"; msg: ChatMessage } | { kind: "job"; job: FeedJob };

/** Сообщения и задачи по времени; при равном — сообщение раньше («Меняю…» стоит перед своей полосой). */
export function feedItems(messages: ChatMessage[], jobs: FeedJob[]): FeedItem[] {
  const all: Array<FeedItem & { at: number; o: number }> = [
    ...messages.map((msg, i) => ({ kind: "msg" as const, msg, at: msg.ts, o: i })),
    ...jobs.map((job, i) => ({ kind: "job" as const, job, at: job.ts, o: messages.length + i })),
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
  /** Последняя правка изменила презентацию: её слайд (null — какой, неизвестно). */
  edited: { slide: number | null } | null;
  /** На экране — результат с презентацией; `slide` — открытый слайд. */
  deck: boolean;
  slide: number;
  template: boolean;
  /** Есть замечания, которые правятся сами («Исправь всё»). */
  fixable: boolean;
}

/** Подсказки под лентой (не больше двух): после правки — «Верни как было»; в пустой ленте — по месту. */
export function chipsFor(c: ChipCtx): string[] {
  if (c.pending || c.busy) return [];
  if (c.edited) return ["Верни как было", ...(c.edited.slide ? [`Почему слайд ${c.edited.slide} такой?`] : [])];
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
