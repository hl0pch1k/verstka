// Шаг «02 Текст» без React: что поле скажет о тексте и о файле, печатающаяся подсказка, строки под полем, полоса 02 и
// заметка «Улучшить готовую». Правила и тексты — boards/V2.dc.html (модуль tx, `twTick`, C-text, C-improve, C-errors);
// разбор текста — lib/textFacts.ts и lib/writerMode.ts.
import { BRIEF_MIN, BRIEF_MIN_TOPIC } from "../../lib/createForm";
import { humanError } from "../../lib/errors";
import { templateStem } from "../../lib/templateFiles";
import { briefBody, factsLine, textFacts } from "../../lib/textFacts";
import { plural } from "../../lib/utils";
import { writerModeOf } from "../../lib/writerMode";
import type { ImproveSource } from "../../types";

/** Ошибка у поля. `empty` / `short` / `type` — правила `textError`; `file` — файл не прочитался или презентацию не
 *  удалось прочитать на сервере (причина — в `text`). */
export interface TextIssue { kind: "empty" | "short" | "type" | "file"; text: string }

export const EMPTY_TEXT = "Напишите, о чём презентация";
export const SHORT_TEXT = "Слишком коротко — напишите тему подробнее";
/** Сервер не пишет текст по теме (`health.writer` выключен): презентация строится из текста как есть. */
export const SHORT_NO_WRITER = `Нужен готовый текст от ${BRIEF_MIN} знаков — агент на этом сервере не пишет текст по теме`;

// ── файлы «Из файла»
const EXT_RE = /\.[a-z0-9]+$/i;
const ext = (name: string) => (name.match(EXT_RE)?.[0] ?? "").toLowerCase();
/** Текст в поле как есть. */
export const TEXT_EXTS = [".txt", ".md", ".markdown"];
/** Готовая презентация — «Улучшить готовую» (сервер переводит в .pptx сам: verstka/ingest/convert.py). Шаблоны
 *  оформления (.potx, .thmx …) — дело шага 01. */
export const DECK_EXTS = [".pptx", ".pptm", ".ppsx", ".ppsm", ".ppt", ".pps", ".odp"];
export const TEXT_ACCEPT = [...TEXT_EXTS, "text/plain", "text/markdown"].join(",");
export const DECK_ACCEPT = [
  ...DECK_EXTS,
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.ms-powerpoint",
  "application/vnd.oasis.opendocument.presentation",
].join(",");
/** Больше текст из файла не берём (как прежде, 2 МБ). */
export const MAX_TEXT_BYTES = 2 * 1024 * 1024;

export type FileKind = "text" | "deck" | "other";
export function fileKind(name: string): FileKind {
  const e = ext(name);
  return TEXT_EXTS.includes(e) ? "text" : DECK_EXTS.includes(e) ? "deck" : "other";
}

/** Что поле скажет о тексте (или о выбранном файле) — null, если сказать нечего.
 *  - С файлом проверяется только его тип: содержимое файла ещё заменит текст поля. `.txt`/`.md` и презентации поле
 *    берёт, остальное — «Файл «X.pdf» не подойдёт».
 *  - Пустой текст и одни пробелы — `empty` (настройки «---» в начале — не текст, сервер их не считает).
 *  - Текст короче `BRIEF_MIN_TOPIC` — `short`. Это когда сервер пишет текст по теме (`writer`, `health.writer`); без
 *    этого тема — не текст: нужен готовый текст от `BRIEF_MIN` знаков (как старый CreateScreen). */
export function textError(text: string, file: { name: string } | null | undefined, opts: { writer: boolean }): null | { kind: "empty" | "short" | "type"; text: string } {
  if (file) return fileKind(file.name) === "other" ? { kind: "type", text: `Файл «${file.name}» не подойдёт` } : null;
  const body = briefBody(text ?? "").trim();
  if (!body) return { kind: "empty", text: EMPTY_TEXT };
  if (!opts.writer && body.length < BRIEF_MIN) return { kind: "short", text: SHORT_NO_WRITER };
  if (body.length < BRIEF_MIN_TOPIC) return { kind: "short", text: SHORT_TEXT };
  return null;
}

/** Файл .txt/.md прочитан как UTF-8: на байтах другой кодировки (windows-1251, KOI8-R) браузер подставляет знак замены
 *  U+FFFD — такой текст в поле не кладём. */
export const NOT_UTF8 = "Файл не в кодировке UTF-8 — сохраните его в UTF-8 и загрузите снова";

/** Что поле скажет о прочитанном тексте файла: не UTF-8 (знак замены в тексте) или пустой; null — текст годится.
 *  `raw` — как вернул `File.text()`, `name` — имя файла для строки. */
export function fileTextIssue(raw: string, name: string): TextIssue | null {
  if (raw.includes("\uFFFD")) return { kind: "file", text: NOT_UTF8 };
  if (!raw.trim()) return { kind: "file", text: `Файл «${name}» пустой` };
  return null;
}

// ── печатающаяся подсказка (V2 `TW`, `twTick`)
/** Фразы после «Например: » — по кругу. */
export const TW = [
  "создай презентацию про историю VK",
  "питч стартапа доставки продуктов за 15 минут",
  "расскажи, как работает фотосинтез",
  "сделай презентацию про Российскую империю",
  "итоги квартала для отдела продаж",
  "создай презентацию про нейросети для школьников",
  "расскажи про чёрные дыры простыми словами",
  "сделай презентацию к защите курсовой по экономике",
  "питч мобильного приложения для изучения языков",
  "создай презентацию про реформы Петра I",
  "итоги года: что сделала команда маркетинга",
  "расскажи, как устроен блокчейн",
  "сделай презентацию про законы Ньютона для 9 класса",
  "питч сети кофеен для инвесторов",
  "создай презентацию про Вторую мировую войну",
  "расскажи, зачем компании переходят на микросервисы",
  "итоги хакатона и лучшие проекты команд",
  "сделай презентацию про Солнечную систему для 5 класса",
  "создай презентацию про интегралы с примерами",
];

/** Где печать: фраза `i`, видно `n` знаков; `type` — печатает, `hold` — держит (`k` — тики по 500 мс), `erase` —
 *  стирает, `pause` — пустая строка перед следующей фразой. */
export interface Tw { i: number; n: number; mode: "type" | "hold" | "erase" | "pause"; k: number }
/** Начало, как в V2: первая фраза уже напечатана и держится. */
export const TW0: Tw = { i: 0, n: TW[0].length, mode: "hold", k: 0 };
export const TW_FIRST_MS = 500;
/** Поле очистили — печать продолжается через 400 мс (V2 `twWake()`). */
export const TW_WAKE_MS = 400;

/** Один тик V2 `twTick`: печать 45 мс на знак → держим 3000 мс (курсор мигает) → стирание 25 мс на знак → пауза
 *  400 мс → следующая фраза. Возвращает новое место и через сколько следующий тик. */
export function twStep(s: Tw, list: string[] = TW): { s: Tw; ms: number } {
  const len = list[s.i].length;
  if (s.mode === "type") {
    const n = Math.min(len, s.n + 1);
    return n >= len ? { s: { ...s, n, mode: "hold", k: 0 }, ms: 500 } : { s: { ...s, n }, ms: 45 };
  }
  if (s.mode === "hold") {
    const k = s.k + 1;
    return { s: { ...s, k, mode: k >= 5 ? "erase" : "hold" }, ms: 500 };
  }
  if (s.mode === "erase") {
    const n = Math.max(0, s.n - 1);
    return n === 0 ? { s: { ...s, n, mode: "pause" }, ms: 400 } : { s: { ...s, n }, ms: 25 };
  }
  return { s: { i: (s.i + 1) % list.length, n: 1, mode: "type", k: 0 }, ms: 45 };
}
export const twText = (s: Tw, list: string[] = TW) => `Например: ${list[s.i].slice(0, s.n)}`;
/** Курсор мигает, пока фраза стоит (держим) и в паузе; пока печатает и стирает — горит. */
export const twBlink = (s: Tw) => s.mode === "hold" || s.mode === "pause";

// ── строки поля
/** «1 551 знак» — тысячи через пробел (V2 `chars`). */
export function charsLabel(n: number): string {
  return plural(n, "знак", "знака", "знаков").replace(/^\d+/, String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "));
}

/** Строка слева под полем: `topic` — «Это тема — агент напишет полный текст…» (пустое поле и тема, которую агент
 *  распишет); `facts` — готовый текст: «В тексте: 6 слайдов, 14 чисел, 1 таблица» (`facts` null — ни слайдов, ни чисел,
 *  ни таблиц). `writer` — агент пишет текст по теме (сервер в режиме writer, модель пишет тексты). О своём проекте
 *  («наш», «мы») агент не пишет — такой текст строится как есть. */
export type TextLine = { kind: "topic" } | { kind: "facts"; facts: string | null };
export function textLine(text: string, writer: boolean): TextLine {
  if (!briefBody(text).trim()) return { kind: "topic" };
  const w = writerModeOf(text);
  if (writer && w.mode && !w.privateHint) return { kind: "topic" };
  return { kind: "facts", facts: factsLine(textFacts(text)) };
}

/** Строка, не длиннее `n` знаков: обрезается по слову, с многоточием. */
export function clipLine(s: string, n: number): string {
  if (s.length <= n) return s;
  let cut = s.slice(0, n);
  const space = cut.lastIndexOf(" ");
  if (space > n / 2) cut = cut.slice(0, space);
  return `${cut.trimEnd()}…`;
}
const firstLine = (text: string) => briefBody(text).trim().split("\n")[0].trim();

/** Свёрнутый шаг: «Интеграл» в кавычках или «Тема ещё не задана» (V2 `preview`). */
export function textPreview(text: string): { text: string; empty: boolean } {
  const line = firstLine(text);
  return line ? { text: `«${clipLine(line, 60)}»`, empty: false } : { text: "Тема ещё не задана", empty: true };
}

/** Имя презентации для людей: её заголовок или имя файла без расширения. */
export const deckName = (src: Pick<ImproveSource, "name" | "title">) => src.title?.trim() || templateStem(src.name);

/** «14 слайдов» или null, когда число слайдов неизвестно (презентация открыта из сборки без него): «0 слайдов» не пишем. */
const slidesLabel = (n: number | null | undefined) => (n && n > 0 ? plural(n, "слайд", "слайда", "слайдов") : null);
const joinDot = (parts: (string | null)[]) => parts.filter(Boolean).join(" · ");

/** Полоса 02 (сборка, «Все параметры»): тема и «тема · текст пишет агент» (V2 `docTitle`, `docSub`), готовый текст и
 *  его разбор, презентация «Улучшить готовую». `line` — уже разобранная строка текста (`textLine`): полоса её не
 *  считает, разбор текста делается один раз на изменение. */
export function textStrip(text: string, o: { line: TextLine; improve?: ImproveSource | null }): { title: string; meta?: string } {
  if (o.improve) return { title: deckName(o.improve), meta: joinDot(["текст из презентации", slidesLabel(o.improve.slides)]) };
  const first = firstLine(text);
  if (!first) return { title: "Тема ещё не задана" };
  const l = o.line;
  if (l.kind === "topic") return { title: clipLine(first, 60), meta: "тема · текст пишет агент" };
  return { title: clipLine(first, 60), meta: l.facts ? `готовый текст · ${l.facts}` : "готовый текст" };
}

// ── «Улучшить готовую»
export interface NotePart { t: string; b?: boolean }
/** Заметка над полем (C-improve): что пришло из презентации, её оценка и замечания модели, что будет дальше. Жирным —
 *  имя, оценка и число проблем. «А модель посмотрит на каждый новый слайд» — только когда модель подключена. */
export function improveNoteParts(src: ImproveSource, modelOn: boolean): NotePart[] {
  const held = [
    slidesLabel(src.slides),
    src.tables ? plural(src.tables, "таблица", "таблицы", "таблиц") : null,
    src.charts ? plural(src.charts, "диаграмма", "диаграммы", "диаграмм") : null,
    src.pictures ? plural(src.pictures, "изображение", "изображения", "изображений") : null,
  ].filter(Boolean).join(", ");
  const parts: NotePart[] = [{ t: "Текст и оформление — из презентации " }, { t: `«${deckName(src)}»`, b: true }, { t: held ? `: ${held}.` : "." }];
  if (src.audit) parts.push({ t: " Оценка исходной презентации — " }, { t: `${src.audit.score} из 100`, b: true }, { t: "." });
  const probs = src.problems?.length ?? 0;
  if (probs) parts.push({ t: " Модель нашла в ней " }, { t: `${plural(probs, "проблему", "проблемы", "проблем")} вёрстки`, b: true }, { t: "." });
  parts.push({ t: ` Слайды останутся те же, вёрстка соберётся заново${modelOn ? ", а модель посмотрит на каждый новый слайд" : ""}.` });
  return parts;
}

/** Подпись полосы 01 в «Улучшить готовую»: «14 слайдов · оформление из презентации» (число слайдов неизвестно — без него). */
export const improveStripMeta = (src: Pick<ImproveSource, "name" | "slides">) => joinDot([slidesLabel(src.slides), "оформление из презентации"]);

/** Число слайдов для читающего с экрана («14 слайдов») или null — полоса 01 называет его в `aria-label`. */
export const improveSlides = (src: Pick<ImproveSource, "name" | "slides">) => slidesLabel(src.slides);

// ── жизнь режима «Улучшить готовую»
/** Где режим сейчас: `tpl` — шаблон исходной презентации (null — шаблон не выбран), `hadText` — в поле уже был текст. */
export interface ImproveLive { tpl: string | null; hadText: boolean }
/** Начало режима. `sourceBrief` — текст презентации, который встаёт в поле: он есть с самого начала (`hadText`), даже если
 *  в поле не изменился (презентацию прочитали заново, «Изменить текст» после сборки с тем же текстом) — иначе очистка
 *  такого поля режим не кончала бы: «текст появился» эффект не увидел бы. */
export const improveLive = (tpl: string | null, sourceBrief: string): ImproveLive => ({ tpl, hadText: !!sourceBrief.trim() });

/** Кончается ли режим «Улучшить готовую» (V2 `txText`, `txImpOn`): другой шаблон выбран или поле очищено. Ввод в поле
 *  режим держит. У презентации без текста поле пусто с самого начала: это не очистка, режим кончится, когда текст
 *  появится и его сотрут (иначе он кончался бы на первом же проходе). Возвращает следующее состояние и итог. */
export function improveStep(live: ImproveLive, brief: string, templateId: string | null): { live: ImproveLive; ends: boolean } {
  const has = !!brief.trim();
  const hadText = live.hadText || has;
  return { live: hadText === live.hadText ? live : { ...live, hadText }, ends: templateId !== live.tpl || (hadText && !has) };
}

/** Сдвиг поля под заметку: на доске заметка в две строки (72 px) — поле уходит вниз на 88 px и вырастает вниз на 16
 *  (`.tx-fw-imp`). Заметка выше (при 1280 px или с помощником) — поле уходит на её высоту + 16, а растёт меньше, чтобы
 *  его низ не ушёл под плиту 03. */
export function improveShift(noteH: number): { shift: number; grow: number } {
  const shift = Math.max(88, Math.round(noteH) + 16);
  return { shift, grow: Math.max(0, 16 - (shift - 88)) };
}

/** Первое предложение текста (строка у поля — одна, без переноса). */
const firstSentence = (t: string) => t.split(/(?<=[.!?…])\s+/)[0];

/** Строка у поля, когда презентацию («Улучшить готовую») прочитать не удалось — по строке области «Текст»:
 *  - сервер не принял файл («Не удалось загрузить шаблон: <причина>») — причина, если это целая фраза (первое её
 *    предложение), иначе «Не удалось загрузить презентацию: <причина>»;
 *  - задача чтения упала («Не получилось: <причина>») — первое предложение причины;
 *  - презентация прочитана, но не загрузилась — так и сказано.
 *  Без русских слов в причине — «Не удалось прочитать презентацию «X»». */
export function deckError(notice: string, name: string): string {
  const fallback = name ? `Не удалось прочитать презентацию «${templateStem(name)}»` : "Не удалось прочитать презентацию";
  if (/^Шаблон разобран, но не загрузился/.test(notice)) return "Презентация прочитана, но не загрузилась — попробуйте ещё раз";
  const post = /^Не удалось загрузить шаблон:\s*/.exec(notice);
  const rest = notice.replace(/^(?:Не получилось|Не удалось загрузить шаблон):\s*/, "");
  const why = humanError(rest, fallback);
  if (why === fallback) return fallback;
  if (post && !/[.!?…]/.test(why)) return `Не удалось загрузить презентацию: ${why}`;
  return firstSentence(why);
}
