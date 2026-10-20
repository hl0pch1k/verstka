// Правила «Данных» и «Брендбука» на «Создать» (вторая ступень; boards/V2.dc.html версии 105, модуль ds): что за файл,
// какая строка у карточки и у панели, цели из текста, полоса 02, шаги разбора брендбука по событиям задачи, расхождения
// с шаблоном, ширина панели «Данные» в узкой колоде, запрос сборки и манифест примера. Только чистые функции — их тесты
// в dataRules.test.ts; состояние — dataState.ts, разметка — DataPanel, GoalsBox, BrandMenu, BrandAnalysis, BrandLayer.
import type {
  BrandColorRole, BrandConflict, BrandPriority, BrandSpec, DatasetSummary, JobEvent, SourceKind, TaskKind,
} from "../../types";
import { plural } from "../../lib/utils";
import { GOAL_VIZ, vizNameLower } from "../../lib/vizNames";
import type { GoalNote, GoalsAnswer } from "../../api";
import { HELPER_COL, PLATE_PAD } from "../deck/layout";

// ── файлы с данными
const EXT: Record<string, SourceKind> = {
  ".csv": "csv", ".tsv": "tsv", ".tab": "tsv", ".xlsx": "xlsx", ".xlsm": "xlsx", ".json": "json", ".txt": "text", ".md": "text", ".markdown": "text",
};
/** Что принимает «Файлы с данными» (окно выбора и перетаскивание). */
export const DATA_ACCEPT = [...Object.keys(EXT), "text/csv", "application/json", "text/plain", "text/markdown",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"].join(",");
/** Пределы размера файла с данными — как у сервера (verstka/api/app.py: `max_data_bytes`, `max_xlsx_bytes`,
 *  `max_text_bytes`, по умолчанию 25 / 4 / 15 МБ): книга Excel и текст с таблицей читаются медленнее CSV — у них свои
 *  пределы. Больше — файл не отправляется: сервер ответил бы 413, а карточка говорит то же самое сразу. */
const MB = 1024 * 1024;
export const MAX_DATA_BYTES = { any: 25 * MB, xlsx: 4 * MB, text: 15 * MB } as const;
const mb = (bytes: number) => String(Math.round((bytes / MB) * 100) / 100).replace(".", ",");

/** Файл больше своего предела — что скажет карточка (слова сервера, `upload_datasets` и `_slow_format_limit`); null —
 *  размер годится. Сначала общий предел, потом предел медленного формата (как на сервере). Книга Excel — по
 *  расширению (сервер узнаёт её по байтам). */
export function sizeProblem(name: string, size: number): string | null {
  if (size > MAX_DATA_BYTES.any) return `«${name}» больше ${mb(MAX_DATA_BYTES.any)} МБ — оставьте в файле только нужные строки и листы`;
  const k = dataKind(name);
  if (k === "xlsx" && size > MAX_DATA_BYTES.xlsx) {
    return `Книга Excel «${name}» больше ${mb(MAX_DATA_BYTES.xlsx)} МБ — сохраните нужный лист как CSV (он прочитается быстрее) или оставьте в книге только нужные листы`;
  }
  if (k === "text" && size > MAX_DATA_BYTES.text) return `Текст «${name}» больше ${mb(MAX_DATA_BYTES.text)} МБ — сохраните таблицу из него как CSV (она прочитается быстрее)`;
  return null;
}

const extOf = (name: string) => {
  const m = /\.[^./\\]+$/.exec(name.toLowerCase());
  return m ? m[0] : "";
};

/** Формат файла данных по расширению; null — не файл данных. */
export const dataKind = (name: string): SourceKind | null => EXT[extOf(name)] ?? null;

/** Подпись формата в подсказке карточки: «CSV», «XLSX», «TXT». */
export const fmtLabel = (name: string): string => extOf(name).slice(1).toUpperCase() || "файл";

/** Таблица в тексте: строки Markdown «| … |» с разделителем «|---|» или три строки подряд, разделённые табуляцией или
 *  «;» (тот же признак, что у чтения текста на сервере, грубо): такой .txt/.md — данные, а не текст презентации. */
export function hasTable(text: string): boolean {
  const lines = text.split(/\r?\n/);
  const pipe = lines.filter((l) => /^\s*\|.*\|\s*$/.test(l));
  if (pipe.length >= 2 && lines.some((l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(l))) return true;
  let run = 0;
  for (const l of lines) {
    const cells = l.includes("\t") ? l.split("\t") : l.includes(";") ? l.split(";") : [];
    run = cells.length >= 2 && cells.every((c) => c.trim() !== "") ? run + 1 : 0;
    if (run >= 3) return true;
  }
  return false;
}

/** Куда идёт файл, отпущенный на плиту 02 («текст и данные вместе»): таблицы — в «Данные», презентация — в
 *  «Улучшить готовую», .txt/.md — смотря что в нём (`hasTable` по прочитанному тексту, решает вызывающий). */
export type DropKind = "data" | "text" | "deck" | "other";
export function dropKind(name: string): DropKind {
  const e = extOf(name);
  if ([".pptx", ".pptm", ".ppsx", ".ppsm", ".ppt", ".pps", ".odp"].includes(e)) return "deck";
  const k = EXT[e];
  if (!k) return "other";
  return k === "text" ? "text" : "data";
}

/** Карточка файла в панели «Данные»: ждёт очереди, разбирается, разобран (профиль) или не прочитан (причина). Один файл
 *  XLSX с несколькими листами даёт несколько карточек — по листу. */
export type DataStatus = "wait" | "run" | "done" | "fail";
export interface DataCard {
  /** Свой ключ карточки (не меняется, пока она на месте). */
  key: string;
  /** Имя файла (у листа — «Регионы.xlsx · Лист1»). */
  file: string;
  kind: SourceKind | null;
  status: DataStatus;
  summary: DatasetSummary | null;
  error: string | null;
}

/** Что карточка говорит, пока файл разбирается (природы ещё нет — по формату). */
export function runWord(kind: SourceKind | null): string {
  switch (kind) {
    case "xlsx": return "читаю листы…";
    case "json": return "читаю записи…";
    case "text": return "ищу таблицу в тексте…";
    default: return "читаю таблицу…";
  }
}

/** Размер таблицы: «21 строка · 3 колонки» в широкой колоде и «21 строка» в узкой (V2 `size`, `sizeN`). */
export function cardSize(rows: number, cols: number): { wide: string; narrow: string } {
  const r = plural(rows, "строка", "строки", "строк");
  return { wide: `${r} · ${plural(cols, "колонка", "колонки", "колонок")}`, narrow: r };
}

/** Имя карточки: имя файла, у листа книги — с листом. */
export const cardName = (s: Pick<DatasetSummary, "file" | "sheet">, many: boolean): string => (many && s.sheet ? `${s.file} · ${s.sheet}` : s.file);

/** Подсказка карточки: «Выручка по месяцам.csv · CSV · 21 строка · 3 колонки · Временной ряд» и что заметно в данных. */
export function cardTip(c: DataCard): string {
  const s = c.summary;
  if (c.status === "fail") return [c.file, c.error].filter(Boolean).join(" · ");
  if (!s) return [c.file, fmtLabel(c.file)].join(" · ");
  return [c.file, fmtLabel(s.file), cardSize(s.rows, s.cols).wide, s.nature_label, ...s.issues].filter(Boolean).join(" · ");
}

/** Строка в шапке панели: «разбираю 3 из 7…» (синим), «7 файлов разобраны», «5 из 7 разобраны» (часть не прочитана). */
export function panelStatus(cards: Pick<DataCard, "status">[]): { text: string; short: string; busy: boolean } {
  const n = cards.length;
  if (!n) return { text: "", short: "", busy: false };
  const done = cards.filter((c) => c.status === "done").length;
  const fail = cards.filter((c) => c.status === "fail").length;
  if (done + fail < n) {
    const k = Math.min(n, done + fail + 1);
    return { text: `разбираю ${k} из ${n}…`, short: `${k} из ${n}…`, busy: true };
  }
  if (!fail) return { text: plural(n, "файл разобран", "файла разобраны", "файлов разобраны"), short: `${n} готово`, busy: false };
  return { text: `${done} из ${n} разобраны`, short: `${done} из ${n} готово`, busy: false };
}
/** Панель в узкой колоде у́же 300 (окно около 1280 с помощником): строка в шапке — короткая («20 готово»). */
export const panelShort = (wrap: number): boolean => dataPanel(wrap).narrow < 300;

/** id наборов для сборки — разобранные карточки по порядку. */
export const datasetIds = (cards: DataCard[]): string[] => cards.filter((c) => c.status === "done" && c.summary).map((c) => c.summary!.id);

/** Файлы ещё разбираются: сборку рано начинать. */
export const dataBusy = (cards: Pick<DataCard, "status">[]): boolean => cards.some((c) => c.status === "wait" || c.status === "run");

// ── цели из текста (§2.3: «покажи рост», «сравни регионы», «из чего складывается», «как распределено», «есть ли связь»,
//    «справочно»): показывают, что текст влияет на выбор графика. Сам выбор — на сервере (verstka/data/goals.py)
export interface Goal { q: string; to: string; task: TaskKind }
const GOALS: { re: RegExp; to: string; task: TaskKind }[] = [
  { re: /(?:покажи(?:те)?|показать)\s+(?:рост|динамик|изменени|тренд|как\s+(?:рос|менял))[^,.;:!?\n]*/i, to: vizNameLower(GOAL_VIZ.dynamics), task: "dynamics" },
  { re: /(?:сравни(?:те)?|сравнить)\s+[^,.;:!?\n]+/i, to: vizNameLower(GOAL_VIZ.comparison), task: "comparison" },
  { re: /(?:из\s+чего\s+(?:складывается|состоит)|(?:покажи(?:те)?|показать)\s+(?:дол|структур))[^,.;:!?\n]*/i, to: vizNameLower(GOAL_VIZ.shares), task: "shares" },
  { re: /(?:как\s+распредел[её]н[аоы]?|(?:покажи(?:те)?|показать)\s+распределени)[^,.;:!?\n]*/i, to: vizNameLower(GOAL_VIZ.distribution), task: "distribution" },
  { re: /(?:есть\s+ли\s+связь|связь\s+между|зависит\s+ли)[^,.;:!?\n]*/i, to: vizNameLower(GOAL_VIZ.relationship), task: "relationship" },
  { re: /(?:справочно|для\s+справки)[^,.;:!?\n]*/i, to: vizNameLower(GOAL_VIZ.reference), task: "reference" },
];
/** Цели в тексте по порядку, у каждой задачи — первая; «покажи рост выручки» → линейный график (V2 `dtGoals`). */
export function goalsOf(text: string): Goal[] {
  const found: { m: RegExpExecArray; to: string; task: TaskKind }[] = [];
  for (const g of GOALS) {
    const m = g.re.exec(text);
    if (m) found.push({ m, to: g.to, task: g.task });
  }
  found.sort((a, b) => a.m.index - b.m.index);
  return found.map(({ m, to, task }, i) => {
    // цель кончается там, где начинается следующая («покажи рост выручки и сравни регионы» — две цели), без «и» на конце
    const next = found[i + 1]?.m.index ?? Infinity;
    const end = Math.min(m.index + m[0].length, next);
    const q = text.slice(m.index, end).replace(/\s+(?:и|а также|а)\s*$/i, "").trim().replace(/\s+/g, " ");
    return { q: q.charAt(0).toLowerCase() + q.slice(1), to, task };
  });
}

/** Таблетка «Цели из текста»: цитата, к чему ведёт («линейный график») и как цель понята (подсказка). */
export interface GoalChip { key: string; q: string; to: string | null; title: string }
const quoteOf = (s: string) => {
  const q = s.trim().replace(/\s+/g, " ").replace(/^[«"“]+|[»"”]+$/g, "").replace(/[\s.,;:!?…]+$/, "");
  return q.charAt(0).toLowerCase() + q.slice(1);
};
/** Таблетки целей: как их поняла сборка (POST /api/goals), а пока ответа нет (или без файлов, или запрос не удался) —
 *  мгновенная прикидка по тексту (`goalsOf`). Одинаковые (та же задача и цитата) — один раз. */
export function goalChips(server: Pick<GoalsAnswer, "goals"> | null, fallback: Goal[]): GoalChip[] {
  const out: GoalChip[] = [];
  const seen = new Set<string>();
  const push = (c: GoalChip) => {
    if (!c.q || seen.has(c.key)) return;
    seen.add(c.key);
    out.push(c);
  };
  if (server) {
    for (const g of server.goals) {
      const q = quoteOf(g.quote);
      // название вида — из одной таблицы интерфейса (как в «Почему так» и «Плане»), а не своё у целей
      push({ key: `${g.task}|${q}`, q, to: g.viz ? vizNameLower(g.viz) : g.viz_title || null, title: [g.label || g.task_title, g.file].filter(Boolean).join(" · ") });
    }
  } else {
    for (const g of fallback) push({ key: `${g.task}|${g.q}`, q: g.q, to: g.to, title: `«${g.q}» → ${g.to}` });
  }
  return out;
}
/** Прежний ответ, пока новый в пути: остаются цели и строки, чьи цитаты ещё есть в тексте (текст заменили — их нет,
 *  и показывается прикидка, а не цели прежнего текста). null — от ответа ничего не осталось. */
export function stillInText(a: GoalsAnswer, text: string): GoalsAnswer | null {
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е").replace(/[«»"“”.,;:!?…—–-]+/g, " ").replace(/\s+/g, " ").trim();
  const t = norm(text);
  const has = (q: string) => !!norm(q) && t.includes(norm(q));
  const goals = a.goals.filter((g) => has(g.quote));
  const notes = a.notes.filter((n) => has(n.quote));
  if (a.goals.length && !goals.length) return null;
  return { ...a, goals, notes };
}

/** Предложения брифа без ответа в данных — одной тихой строкой: первое и сколько ещё; целиком — в подсказке. */
export function goalNoteLine(notes: Pick<GoalNote, "quote" | "reason">[]): { line: string; all: string } | null {
  const ns = notes.filter((n) => n.quote.trim() && n.reason.trim());
  if (!ns.length) return null;
  const say = (n: Pick<GoalNote, "quote" | "reason">) => `«${quoteOf(n.quote)}» — ${n.reason.trim().replace(/[.\s]+$/, "")}`;
  return { line: say(ns[0]) + (ns.length > 1 ? ` · и ещё ${ns.length - 1}` : ""), all: ns.map(say).join("\n") };
}
/** Ключ запроса целей: текст (без лишних пробелов), наборы по порядку и пишет ли модель. */
export const goalsKey = (brief: string, ids: string[], models: boolean): string => `${models ? 1 : 0}|${ids.join(",")}|${brief.trim().replace(/\s+/g, " ")}`;

/** Подпись коробки целей: в широкой колоде и в узкой (V2 `dtGoalLbl`, `dtGoalLblN`). */
export const goalsLabel = (n: number): { wide: string; narrow: string } =>
  n ? { wide: "Цели из текста — влияют на выбор графика", narrow: "Цели из текста" } : { wide: "Целей в тексте нет — графики выберу по данным", narrow: "Целей в тексте нет" };

// ── полоса 02 с данными (V2 `brief`, `s2Sub`): первая фраза брифа до 44 знаков и сколько файлов
export function briefShort(text: string): string {
  const t = text.trim();
  if (!t) return "Тема ещё не задана";
  let f = t.split(/[.!?\n]/)[0].trim();
  if (f.length > 44) f = f.slice(0, 45).replace(/\s+\S*$/, "");
  return f + (f.length < t.length ? "…" : "");
}
export const dataFilesLabel = (n: number): string => `${plural(n, "файл", "файла", "файлов")} данных`;

// ── панель «Данные» в узкой колоде: 400 → 320 (V2); сайт: в тесной колоде (окно около 1280) поле не у́же 280 — панель
//    сжимается сильнее (не у́же 200). --hpd поля (стопка c-tad) — на сколько поле у́же в узкой раскладке
const BODY_LEFT = 192;
export const PANEL = 400;
export const PANEL_NARROW = 320;
export const PANEL_MIN = 200;
export const FIELD_MIN = 280;
const GAP = 16;
export function dataPanel(wrap: number): { wide: number; narrow: number; hpd: number } {
  const deck = wrap > 0 ? wrap : 1392;
  const body = deck - HELPER_COL - PLATE_PAD - BODY_LEFT;
  const narrow = Math.max(PANEL_MIN, Math.min(PANEL_NARROW, body - GAP - FIELD_MIN));
  return { wide: PANEL, narrow, hpd: HELPER_COL - (PANEL - narrow) };
}
/** Ширина поля «О чём презентация» рядом с панелью: без помощника и с ним. */
export function fieldWidths(wrap: number): { wide: number; narrow: number } {
  const deck = wrap > 0 ? wrap : 1392;
  const body = deck - PLATE_PAD - BODY_LEFT;
  return { wide: body - PANEL - GAP, narrow: body - HELPER_COL - dataPanel(wrap).narrow - GAP };
}

/** Как встают таблетки целей на компьютере: `full` — все в ряд с «→ видом графика»; `short` — все в ряд, вид — в
 *  подсказке таблетки; `two` — в два ряда в той же коробке (88): первый ряд — справа от подписи «Цели из текста» (отступ
 *  `lab.l`), второй — во всю ширину, в его конце — «ещё N» (`lab.more` с промежутком), если не поместились; вид — в
 *  подсказке. `wide`/`narrow` — ряд каждой таблетки без помощника и с ним (0 — не поместилась: она и следующие гаснут,
 *  счёт — «ещё N»); первая видна всегда. Таблетка —
 *  «цель» и поля 12 (с видом — ещё «→ вид»), с помощником — поля 10; промежуток 8. */
export interface GoalsLayout { mode: "full" | "short" | "two"; wide: number[]; narrow: number[] }
export function goalsLayout(w: { q: number; gt: number }[], wrap: number, lab: { l: number; more: number } = { l: 0, more: 0 }): GoalsLayout {
  const f = fieldWidths(wrap);
  const iw = f.wide - 48, inn = f.narrow - 32;
  const lay = (inner: number, width: (p: { q: number; gt: number }) => number, rows: number, indent = 0, tail = 0) => {
    let row = 1, x = 0, gone = false;
    return w.map((p, i) => {
      if (gone) return 0;
      const wd = width(p);
      for (;;) {
        const need = (x ? x + 8 : 0) + wd;
        if (need <= inner - (row === 1 ? indent : 0) - (row === rows ? tail : 0) + 0.5 || (i === 0 && row === rows)) {
          x = need;
          return row;
        }
        if (row < rows) {
          row += 1;
          x = 0;
          continue;
        }
        gone = true;
        return 0;
      }
    });
  };
  const all = (r: number[]) => r.every((x) => x > 0);
  const narrow1 = lay(inn, (p) => p.q + 20, 1);
  const full = lay(iw, (p) => p.q + 24 + p.gt, 1);
  if (all(full)) return { mode: "full", wide: full, narrow: narrow1 };
  const short = lay(iw, (p) => p.q + 24, 1);
  if (all(short)) return { mode: "short", wide: short, narrow: narrow1 };
  const two = (inner: number, pad: number) => {
    const r = lay(inner, (p) => p.q + pad, 2, lab.l);
    return all(r) ? r : lay(inner, (p) => p.q + pad, 2, lab.l, lab.more);
  };
  return { mode: "two", wide: two(iw, 24), narrow: two(inn, 20) };
}

/** Тесная колода с помощником (окно около 1366 и уже): в заголовке шага 01 у карточки брендбука остаётся плитка палитры —
 *  подпись сжимается и гаснет, место — шаблону и «Сменить». */
export const brandTight = (wrap: number): boolean => (wrap > 0 ? wrap : 1392) - HELPER_COL < 960;

// ── брендбук
export type BrandSource = "pdf" | "json" | "dir" | "figma";
/** Что выбирают в меню «Брендбук»: файл (PDF, токены, архив), папку целиком или ссылку Figma. */
export type BrandPick = "pdf" | "json" | "dir" | "zip" | "figma";
export const BRAND_ACCEPT: Record<"pdf" | "json" | "zip" | "fig", string> = {
  pdf: ".pdf,application/pdf",
  json: ".json,application/json",
  zip: ".zip,application/zip",
  // локальная копия Figma (Файл → Сохранить локальную копию): сервер читает её сам, без токена (brand/fig.py)
  fig: ".fig",
};
/** Пункты меню «Брендбук» (V2 `bbItems`; «Папка или архив» — двумя пунктами: окно выбора папки и файла разное);
 *  пример — отдельной строкой под чертой. */
export const BRAND_ITEMS: { key: BrandPick; name: string; meta: string }[] = [
  { key: "pdf", name: "PDF-гайдлайн", meta: "палитра, шрифты, правила" },
  { key: "json", name: "Токены (JSON)", meta: "цвета, шрифты, отступы" },
  { key: "dir", name: "Папка брендбука", meta: "логотипы и примеры слайдов" },
  { key: "zip", name: "Архив .zip", meta: "та же папка одним файлом" },
  { key: "figma", name: "Figma — файл или ссылка", meta: "стили и компоненты" },
];

/** Пределы брендбука — как у сервера (app.py `max_brandbook_bytes` 50 МБ, `_MAX_BRAND_FOLDER_FILES` 300): больше —
 *  не отправляется, причина — словами сервера (а не «Сеть недоступна» от его раннего 413). */
export const MAX_BRAND_BYTES = 50 * 1024 * 1024;
export const MAX_BRAND_FILES = 300;
export function brandSizeProblem(src: { size: number } | { size: number }[]): string | null {
  if (Array.isArray(src)) {
    if (src.length > MAX_BRAND_FILES) return `В папке брендбука больше ${MAX_BRAND_FILES} файлов — оставьте логотипы, токены, гайдлайн и примеры слайдов или загрузите архив .zip`;
    if (src.reduce((n, f) => n + f.size, 0) > MAX_BRAND_BYTES) return "Брендбук больше 50 МБ — сожмите картинки в PDF или загрузите токены JSON и логотипы архивом";
    return null;
  }
  return src.size > MAX_BRAND_BYTES ? "Брендбук больше 50 МБ — сожмите картинки в PDF или загрузите токены JSON и логотипы архивом" : null;
}
/** Пример — PDF-гайдлайн (examples/brandbook-vk-cloud); число страниц и имя файла — из разобранного брендбука. */
export const BRAND_SAMPLE = { name: "Пример: Брендбук VK Cloud", meta: "PDF-гайдлайн · палитра, шрифты, логотипы" };

/** Откуда брендбук по выбранному: файл .json — токены, .zip или папка — архив, ссылка — Figma, иначе PDF. */
export function brandSourceOf(src: File | File[] | { figmaUrl: string }): BrandSource {
  if (Array.isArray(src)) return "dir";
  if ("figmaUrl" in src) return "figma";
  const e = extOf(src.name);
  return e === ".json" ? "json" : e === ".zip" ? "dir" : e === ".fig" ? "figma" : "pdf";
}

/** Имя файла брендбука для людей: папка — по первому пути, ссылка Figma — «Figma». */
export function brandFileName(src: File | File[] | { figmaUrl: string }): string {
  if (Array.isArray(src)) return (src[0] as File & { webkitRelativePath?: string })?.webkitRelativePath?.split("/")[0] || "Папка брендбука";
  if ("figmaUrl" in src) return "Файл Figma";
  return src.name;
}

/** Ссылка на файл Figma — по тем же правилам, что у сервера (verstka/brand/figma.py `normalize_url`, `_URL_RE`): кавычки,
 *  «<…>» и отсутствие «https://» не мешают; вид — design, file, proto, board, slides, deck, make; ключ — от 10 знаков. */
export function figmaUrlOk(s: string): boolean {
  let t = s.trim().replace(/^[<>"'«»]+|[<>"'«»]+$/g, "").trim();
  if (/^(?:[\w-]+\.)?figma\.com\//i.test(t)) t = `https://${t}`;
  return /^https?:\/\/(?:[\w-]+\.)?figma\.com\/(?:file|design|proto|board|slides|deck|make)\/[A-Za-z0-9]{10,}/i.test(t);
}

/** Шаги разбора по событиям задачи (§6: палитра · шрифты · логотипы · правила): открыт файл, палитра, шрифты, логотипы,
 *  правила, сверка с шаблоном. Событие с `step` — этот шаг готов, `message` — его итог («6 цветов»); событие без
 *  `step` двигает шаги по доле хода; `brand` — то, что уже прочитано (плитки разбора). */
export const BRAND_STEPS = ["open", "palette", "fonts", "logos", "rules", "compare"] as const;
export type BrandStep = (typeof BRAND_STEPS)[number];
export interface BrandRun { done: number; facts: Partial<Record<BrandStep, string>>; brand: Partial<BrandSpec> | null }
export const BRAND_RUN0: BrandRun = { done: 0, facts: {}, brand: null };
/** Событие задачи разбора брендбука (JobEvent и, сверх него, прочитанное к этому шагу). */
export type BrandEvent = JobEvent & { brand?: Partial<BrandSpec> | null };

/** Другие имена шагов (читатель брендбука зовёт их по-своему: on_step «палитра · шрифты · логотипы · правила»). */
const STEP_ALIAS: Record<string, BrandStep> = {
  file: "open", read: "open", colors: "palette", color: "palette", "палитра": "palette", font: "fonts", typography: "fonts", "шрифты": "fonts",
  logo: "logos", "логотипы": "logos", rule: "rules", "правила": "rules", conflicts: "compare", template: "compare", "сверка": "compare",
};
export const brandStepOf = (step: string | null | undefined): BrandStep | null => {
  const k = (step ?? "").trim().toLowerCase();
  return (BRAND_STEPS as readonly string[]).includes(k) ? (k as BrandStep) : STEP_ALIAS[k] ?? null;
};

export function foldBrandEvent(run: BrandRun, ev: BrandEvent): BrandRun {
  const known = brandStepOf(ev.step);
  const i = known ? BRAND_STEPS.indexOf(known) : -1;
  let done = run.done;
  const facts = { ...run.facts };
  if (i >= 0) {
    done = Math.max(done, i + 1);
    const fact = (ev.message ?? "").trim().replace(/^[^:]*:\s*/, "");
    if (fact) facts[BRAND_STEPS[i]] = fact;
  } else if (typeof ev.progress === "number" && ev.status !== "failed") {
    done = Math.max(done, Math.min(BRAND_STEPS.length - 1, Math.floor(ev.progress * BRAND_STEPS.length)));
  }
  const brand = ev.brand ? { ...(run.brand ?? {}), ...ev.brand } : run.brand;
  return { done, facts, brand };
}

/** Строки шагов (как у разбора шаблона): «палитра: » + «6 цветов». Итог шага ещё неизвестен — только его название. */
export interface StepRow { a: string; b: string; state: "done" | "cur" | "pend" }
const OPEN: Record<BrandSource, [string, string]> = {
  pdf: ["открыт файл", "страницы"],
  json: ["прочитаны токены", "цвета, шрифты, отступы"],
  dir: ["открыт брендбук", "логотипы и примеры слайдов"],
  figma: ["открыт файл Figma", "стили и компоненты"],
};
export function brandRows(run: BrandRun, src: BrandSource, template: string | null): StepRow[] {
  const names = [OPEN[src][0], "палитра", "шрифты", "логотипы", "правила", template ? `сверка с шаблоном ${template}` : "сверка с шаблоном"];
  return BRAND_STEPS.map((k, i) => {
    const state = i < run.done ? "done" : i === run.done ? "cur" : "pend";
    let fact = run.facts[k] ?? "";
    if (!fact && k === "open" && i < run.done) fact = src === "pdf" ? (run.brand?.pages ? plural(run.brand.pages, "страница", "страницы", "страниц") : "") : OPEN[src][1];
    return { a: fact ? `${names[i]}: ` : names[i], b: fact, state };
  });
}

/** Плитки разбора (V2 `bbTiles`): шрифты, палитра, логотипы — заполняются, когда их шаг готов и прочитанное пришло. */
export interface BrandTile { key: "fonts" | "palette" | "logos"; name: string; meta: string; on: boolean }
export function brandTiles(run: BrandRun): BrandTile[] {
  const b = run.brand ?? {};
  const fonts = b.fonts ?? [], colors = b.colors ?? [], logos = b.logos ?? [];
  const at = (k: BrandStep) => run.done > BRAND_STEPS.indexOf(k);
  return [
    { key: "fonts", name: "Шрифты", meta: plural(fonts.length, "шрифт", "шрифта", "шрифтов"), on: at("fonts") && fonts.length > 0 },
    { key: "palette", name: "Палитра", meta: plural(colors.length, "цвет", "цвета", "цветов"), on: at("palette") && colors.length > 0 },
    { key: "logos", name: "Логотипы", meta: plural(logos.length, "логотип", "логотипа", "логотипов"), on: at("logos") && logos.length > 0 },
  ].map((t) => ({ ...t, meta: t.on ? t.meta : "…" })) as BrandTile[];
}

/** Название бренда: из брендбука («VK Cloud»), иначе по файлу без расширения и без слова «Брендбук». */
export function brandName(spec: Pick<BrandSpec, "name"> | null | undefined, file: string): string {
  const own = spec?.name?.trim();
  if (own) return own.replace(/^брендбук\s+/i, "");
  const stem = file.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").trim();
  return stem.replace(/^брендбук\s+/i, "") || "бренда";
}

/** Подпись карточки брендбука (V2 `bbMeta`): «PDF · 24 стр.», «токены JSON», «архив · 4 логотипа», «Figma». */
export function brandMeta(spec: Pick<BrandSpec, "source" | "pages" | "logos">): string {
  switch (spec.source) {
    case "pdf": return spec.pages ? `PDF · ${spec.pages} стр.` : "PDF";
    case "tokens": return "токены JSON";
    case "folder": return spec.logos.length ? `архив · ${plural(spec.logos.length, "логотип", "логотипа", "логотипов")}` : "архив";
    case "figma": return "Figma";
  }
}

/** Подпись слоя (V2 `bbLayMeta`): «Брендбук VK Cloud.pdf · 24 страницы · применяется к шаблону VK Tech». */
export function brandLayerMeta(spec: Pick<BrandSpec, "source" | "pages" | "file">, file: string, template: string | null): string {
  const parts = [spec.file || file];
  if (spec.source === "pdf" && spec.pages) parts.push(plural(spec.pages, "страница", "страницы", "страниц"));
  if (template) parts.push(`применяется к шаблону ${template}`);
  return parts.filter(Boolean).join(" · ");
}

/** Палитра на плитке карточки: первые шесть цветов в порядке брендбука. */
export const brandPalette = (spec: Pick<BrandSpec, "colors"> | null | undefined): string[] => (spec?.colors ?? []).slice(0, 6).map((c) => c.hex);

const ROLE: Record<BrandColorRole, string> = {
  primary: "основной", secondary: "дополнительный", accent: "акцент", text: "текст", background: "фон", surface: "подложка",
  chart: "графики", neutral: "нейтральный", success: "успех", warning: "предупреждение", danger: "ошибка",
};
export const roleLabel = (role: BrandColorRole): string => ROLE[role] ?? role;
export const fontRoleLabel = (role: "heading" | "body"): string => (role === "heading" ? "заголовки" : "основной текст");

/** Расхождение для слоя (V2 `bbConf`): что, шаблон, брендбук, кружки цвета и что в презентации — по тому, что важнее.
 *  `result` сервера — при «брендбук важнее» (по умолчанию); «шаблон важнее» — как в шаблоне. */
export function conflictView(c: BrandConflict): { k: string; a: string; b: string; sw: boolean; res: string } {
  const sw = c.kind === "color" && /^#[0-9A-F]{6}$/i.test(c.template) && /^#[0-9A-F]{6}$/i.test(c.brand);
  // `result` сервера — что получит колода с выбранным приоритетом (GET …?brand_priority=): как есть, без прикидок
  const res = c.result || c.brand;
  return { k: c.what, a: c.template, b: c.brand, sw, res };
}

/** Строка «Оформление» и полосы 01: «брендбук VK Cloud». */
export const brandStrip = (spec: Pick<BrandSpec, "name"> | null | undefined, file: string): string => `брендбук ${brandName(spec, file)}`;

// ── запрос сборки: поля второй ступени (только когда есть что отправить — старый сервер их не ждёт)
export interface DataRequest { dataset_ids?: string[]; brandbook_id?: string | null; brand_priority?: BrandPriority }
export function dataRequest(ids: string[], brandbookId: string | null, priority: BrandPriority): DataRequest {
  const out: DataRequest = {};
  if (ids.length) out.dataset_ids = ids;
  if (brandbookId) {
    out.brandbook_id = brandbookId;
    out.brand_priority = priority;
  }
  return out;
}

// ── пример (GET /api/examples/{name}): текст, файлы и брендбук — ссылками; файлы потом уходят через те же
//    POST /api/datasets и POST /api/brandbooks
export interface ExampleFile { name: string; url: string }
export interface ExampleManifest { name: string; title: string | null; brief: string | null; slides: number | null; files: ExampleFile[]; brandbook: ExampleFile | null }
const fileOf = (x: unknown): ExampleFile | null => {
  const o = x as { name?: unknown; url?: unknown } | null;
  return o && typeof o.name === "string" && typeof o.url === "string" && o.name && o.url ? { name: o.name, url: o.url } : null;
};
export function parseManifest(raw: unknown, name: string): ExampleManifest {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const files = Array.isArray(o.files) ? o.files.map(fileOf).filter((f): f is ExampleFile => !!f) : [];
  if (!files.length && !fileOf(o.brandbook)) throw new Error("В примере нет файлов");
  return {
    name: typeof o.name === "string" ? o.name : name,
    title: typeof o.title === "string" ? o.title : null,
    brief: typeof o.brief === "string" && o.brief.trim() ? o.brief : null,
    slides: typeof o.slides === "number" && o.slides > 0 ? Math.round(o.slides) : null,
    files,
    brandbook: fileOf(o.brandbook),
  };
}
