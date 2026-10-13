// Шаг 01 «Шаблон»: порядок ленты, подписи шаблона и ход разбора загруженного файла — чистые функции (V2, модуль tp:
// `tpAll`, `tpRibL`, `tpSteps`). React здесь не нужен: всё покрыто ribbon.test.ts.
import { hasCyrillic, humanError } from "../../lib/errors";
import { humanizeJobMessage } from "../../lib/jobText";
import { templateFileProblem } from "../../lib/templateFiles";
import { plural } from "../../lib/utils";
import type { TemplateListItem } from "../../types";

/** Время разбора для сравнения: сервер шлёт mtime манифеста числом, тесты и старые записи — строкой даты. */
const at = (t: Pick<TemplateListItem, "analyzed_at">): number => {
  const v = t.analyzed_at as unknown;
  if (typeof v === "number") return v;
  const ms = Date.parse(String(v ?? ""));
  return Number.isFinite(ms) ? ms : 0;
};

/** Все шаблоны в порядке ленты и раздела «Шаблоны»: свои — загруженные позже — первыми (по `analyzed_at`);
 *  `first` — только что загруженный: он встаёт первым, даже если сервер нашёл его разбор в кэше. */
export function orderTemplates(templates: TemplateListItem[], first?: string | null): TemplateListItem[] {
  const out = templates.slice().sort((a, b) => at(b) - at(a));
  const i = first ? out.findIndex((x) => x.template_id === first) : -1;
  if (i > 0) out.unshift(...out.splice(i, 1));
  return out;
}

/** Лента шага 01: `max` обложек (V2 `tpRibL`), выбранный всегда виден — если он дальше, встаёт последним;
 *  `rest` — сколько осталось за плиткой «Все шаблоны». */
export function ribbonItems(templates: TemplateListItem[], selectedId: string | null, max = 6, first?: string | null): { shown: TemplateListItem[]; rest: number } {
  const all = orderTemplates(templates, first);
  let shown = all.slice(0, max);
  const sel = all.findIndex((x) => x.template_id === selectedId);
  if (sel >= max) shown = shown.slice(0, max - 1).concat(all[sel]);
  return { shown, rest: all.length - shown.length };
}

/** «54 слайда» — подпись обложки в ленте. */
export const tplShort = (t: Pick<TemplateListItem, "n_slides">): string => (t.n_slides ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "");

/** «54 слайда · Play» — подпись шаблона в шапке шага, полосе 01 и разделе «Шаблоны». */
export const tplMeta = (t: Pick<TemplateListItem, "n_slides" | "font">): string => [tplShort(t) || null, t.font || null].filter(Boolean).join(" · ");

// ── Ход разбора (C-analyzing): восемь строк доски
export type StepState = "done" | "cur" | "pend";
export const ANALYSIS_STEPS = 8;

/** Сообщение задачи `analyze` (как его показывает activeJob — по-русски, lib/jobText) → какой шаг идёт (0..7;
 *  8 — все готовы), и где сервер шлёт это сообщение (`frac`, verstka/analysis/manifest.py: `report(…, frac)`).
 *  Сообщение говорит, что этап закончился: идёт шаг после него. */
const STEP_OF: Array<{ re: RegExp; step: number; frac: number | null }> = [
  { re: /^Открываю файл/, step: 0, frac: null }, // только у не-.pptx, до «opened package» и с тем же frac
  { re: /^открыт файл/, step: 1, frac: 0.02 },
  { re: /^фигуры и тексты прочитаны/, step: 2, frac: 0.3 },
  { re: /^найдено картинок и иконок/, step: 3, frac: 0.38 },
  { re: /^слайды отрисованы/, step: 3, frac: 0.2 },
  { re: /^цвета, шрифты и сетка собраны/, step: 4, frac: 0.45 },
  { re: /^типы слайдов определены/, step: 5, frac: 0.8 },
  { re: /^найдено \d+ макет/, step: 6, frac: 0.86 },
  { re: /^правила оформления собраны/, step: 7, frac: 0.95 },
  { re: /^(готово|этот шаблон уже разобран раньше)$/i, step: 8, frac: null },
];

/** Сообщение сервера или уже переведённое — к виду activeJob (переводы — lib/jobText, русский остаётся как есть). */
const ru = (message: string) => humanizeJobMessage(message ?? "", (s) => s).replace(/^Шаблон: /, "");

/** Состояния восьми шагов по сообщению и доле задачи. Шаг сообщения идёт, предыдущие готовы. Сервер отрисовывает слайды
 *  раньше, чем читает фигуры, поэтому доля задачи (она не убывает) держит нижнюю границу: шаги не отматываются назад. */
export function analysisSteps(message: string, progress: number): StepState[] {
  const m = ru(message);
  const hit = STEP_OF.find((s) => s.re.test(m));
  let cur = hit ? hit.step : 0;
  for (const s of STEP_OF) if (s.frac !== null && s.frac < progress) cur = Math.max(cur, s.step);
  return Array.from({ length: ANALYSIS_STEPS }, (_, i) => (i < cur ? "done" : i === cur ? "cur" : "pend"));
}

/** Числа, которые разбор называет по ходу: слайды файла, картинки и иконки, макеты. */
export interface AnalysisFacts { slides?: number; pics?: number; lays?: number }

export function analysisFacts(prev: AnalysisFacts, message: string): AnalysisFacts {
  const m = ru(message);
  let r: RegExpMatchArray | null;
  if ((r = m.match(/^открыт файл: (\d+)/))) return { ...prev, slides: Number(r[1]) };
  if ((r = m.match(/^найдено картинок и иконок: (\d+)/))) return { ...prev, pics: Number(r[1]) };
  if ((r = m.match(/^найдено (\d+) макет/))) return { ...prev, lays: Number(r[1]) };
  return prev;
}

/** Строка шага: `a` + жирное `b` + `c` (V2 `tpSteps`). */
export interface AnalysisRow { a: string; b?: string; c?: string; state: StepState }

const word = (n: number, one: string, few: string, many: string) => plural(n, one, few, many).replace(/^\d+ /, "");

export function analysisRows(states: StepState[], f: AnalysisFacts): AnalysisRow[] {
  const lays = states[6] === "done" && f.lays != null
    ? { a: "найдено ", b: String(f.lays), c: ` ${word(f.lays, "макет", "макета", "макетов")} слайдов` }
    : { a: "найдено … макетов слайдов" };
  const rows: Array<Omit<AnalysisRow, "state">> = [
    f.slides != null ? { a: "открыт файл: ", b: plural(f.slides, "слайд", "слайда", "слайдов") } : { a: "открыт файл" },
    { a: "фигуры и тексты прочитаны" },
    f.pics != null ? { a: "найдено картинок и иконок: ", b: String(f.pics) } : { a: "найдено картинок и иконок" },
    { a: "слайды отрисованы" },
    { a: "цвета, шрифты и сетка собраны" },
    { a: "типы слайдов определены" },
    lays,
    { a: "правила оформления собраны" },
  ];
  return rows.map((r, i) => ({ ...r, state: states[i] ?? "pend" }));
}

/** Подсказка плиток «Загрузить свой», пока файл уже разбирается: второй файл в очередь не ставится. */
export const UPLOAD_BUSY_TITLE = "Идёт разбор шаблона";
/** Плитка «Загрузить свой» занята, пока читается презентация для «Улучшить готовую» (и пункт «Улучшить готовую» — пока
 *  разбирается свой шаблон): обе выбирают свой шаблон. */
export const READING_DECK = "Читаю презентацию — дождитесь конца";
export const TEMPLATE_BUSY = "Идёт разбор шаблона — дождитесь конца";

/** Неудача загрузки шаблона — строка ошибки области «Шаблон», пришедшая после её начала (`since`, мс); прежняя строка
 *  (список шаблонов, манифест, давняя загрузка) — не её. */
export const uploadFailed = (note: { kind: string; at: number } | null | undefined, since: number): boolean =>
  !!note && note.kind === "error" && note.at >= since;

// ── Неудача разбора: только по-русски
/** Что сказать, когда причина пришла не по-русски (сообщение lxml, zipfile, Python): файл не прочитался. */
export const FILE_BROKEN = "Не удалось разобрать файл: он повреждён или сохранён в неподдерживаемом формате.";

/** Причина неудачи для человека и можно ли повторить. Русский текст остаётся (отказ по типу файла, ответ сервера с
 *  известной причиной), но без нерусских хвостов (`humanError`: «…не загрузился: Сеть недоступна: Failed to fetch» →
 *  «…не загрузился: Сеть недоступна»); английские сообщения библиотек («Couldn't find end of Start Tag…») не
 *  показываются никогда. Отказ по типу файла (`.pdf`, `.key`) повторять бессмысленно:
 *  «Попробовать ещё раз» отправил бы тот же файл, и ответ был бы тот же — тогда нужен другой файл. */
export function analysisError(err: string | null, file?: string): { text: string; retry: boolean } {
  const retry = !(file && templateFileProblem(file));
  // сервер дописывает трассировку после первой строки
  const first = (err ?? "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  const text = first.replace(/^Не получилось:\s*/, "");
  const sent = text.match(/^Не удалось загрузить шаблон:\s*(.*)$/); // сбой отправки файла: store.report(…, «Не удалось загрузить шаблон»)
  if (sent) {
    if (/^Сеть недоступна/.test(sent[1])) return { text: "Не удалось загрузить файл: нет связи с сервером. Проверьте соединение.", retry };
    if (!hasCyrillic(sent[1])) return { text: "Не удалось загрузить файл на сервер. Попробуйте ещё раз.", retry };
  }
  return { text: humanError(text, FILE_BROKEN), retry };
}
