// Модель состояния второй ступени без React (dataState.ts — её хук): карточки файлов и их очередь, разбор ответа сервера
// (книга XLSX — по карточке на лист), брендбук и его черновик, «использованные» наборы, свежесть расхождений. Чистые
// функции — тесты в dataModel.test.ts.
import { isDocFile } from "./kbRules";
import type { BrandConflict, BrandPriority, BrandSpec, DatasetSummary } from "../../types";
import { BRAND_RUN0, BRAND_STEPS, cardName, dataKind, sizeProblem, type BrandRun, type BrandSource, type DataCard } from "./dataRules";

/** Разбор брендбука: нет; идёт (`run`); все шаги готовы и держатся 560 мс (`done`); гаснет 240 мс (`out`); брендбук
 *  приложен (`on`); не получилось (`fail` — причина в коробке разбора). */
export type BrandPhase = "none" | "run" | "done" | "out" | "on" | "fail";
export interface BrandState {
  phase: BrandPhase;
  source: BrandSource;
  /** Имя файла (папки, «Файл Figma»). */
  file: string;
  /** id на сервере (POST /api/brandbooks), когда он принял файл. */
  id: string | null;
  run: BrandRun;
  spec: BrandSpec | null;
  conflicts: BrandConflict[];
  /** С каким шаблоном сверены расхождения (другой шаблон — расхождения перечитываются); null — ни с каким. */
  tplFor: string | null;
  /** При каком приоритете сервер посчитал «что в презентации» у расхождений (другой — перечитываются). */
  prioFor: BrandPriority | null;
  /** Что не встало при сверке с шаблоном (ответ GET /api/brandbooks/{id}: брендированная копия), по-русски. */
  applyWarnings: string[];
  error: string | null;
  /** Неудачу можно повторить с тем же файлом (не повторить — пример не скачался). */
  canRetry: boolean;
}
export const BRAND0: BrandState = {
  phase: "none", source: "pdf", file: "", id: null, run: BRAND_RUN0, spec: null, conflicts: [], tplFor: null, prioFor: null, applyWarnings: [], error: null, canRetry: false,
};

/** Откуда брендбук по прочитанному (`BrandSpec.source`): токены — «json», папка — «dir». */
export const sourceOfSpec = (s: BrandSpec["source"]): BrandSource => (s === "tokens" ? "json" : s === "folder" ? "dir" : s);

/** Приложенный брендбук по ответу сервера (GET /api/brandbooks/{id}: что прочитано и расхождения с `tplFor`). */
export const brandOn = (id: string, brand: BrandSpec, conflicts: BrandConflict[], tplFor: string | null, prioFor: BrandPriority | null = "brand"): BrandState => ({
  ...BRAND0, phase: "on", id, source: sourceOfSpec(brand.source), file: brand.file ?? "", spec: brand, conflicts, tplFor, prioFor,
  run: { done: BRAND_STEPS.length, facts: {}, brand },
});

/** Расхождения сверены не с выбранным шаблоном (шаблон сменили, пока брендбук разбирался, или его тогда не было) или
 *  посчитаны для другого приоритета («шаблон важнее» / «брендбук важнее»). */
export const conflictsStale = (b: Pick<BrandState, "phase" | "id" | "tplFor" | "prioFor">, templateId: string | null, priority: BrandPriority = "brand"): boolean =>
  b.phase === "on" && !!b.id && !!templateId && (b.tplFor !== templateId || b.prioFor !== priority);

// ── файлы и очередь
/** Только поля карточки: `GET /api/datasets/{id}` несёт ещё профиль и план — в черновик они не идут. */
export function toSummary(raw: DatasetSummary, id?: string): DatasetSummary {
  return {
    id: id ?? raw.id, file: raw.file, kind: raw.kind, rows: raw.rows ?? 0, cols: raw.cols ?? 0, nature: raw.nature,
    nature_label: raw.nature_label ?? "", line: raw.line ?? "", issues: Array.isArray(raw.issues) ? raw.issues.filter((x) => typeof x === "string") : [],
    sheet: raw.sheet ?? null,
  };
}

/** Причина, по которой файл не отправляется вовсе (тип, пустой, размер); null — отправляется. */
export function fileProblem(f: { name: string; size: number }): string | null {
  if (!dataKind(f.name) && !isDocFile(f.name)) return "Такой файл не прочитать — нужен CSV, XLSX, JSON или текст с таблицей";
  if (f.size === 0) return "Файл пустой";
  return sizeProblem(f.name, f.size);
}

/** Новые карточки: в очередь (`wait`) или сразу с причиной (`fail`). */
export const newCards = (files: { name: string; size: number }[], keyOf: () => string): DataCard[] =>
  files.map((f) => {
    const problem = fileProblem(f);
    // документ DOCX / PDF: его таблицы с цифрами — данные (сервер: verstka/ingest/documents.py `document_tables`)
    return { key: keyOf(), file: f.name, kind: dataKind(f.name) ?? (isDocFile(f.name) ? "text" : null), status: problem ? "fail" : "wait", summary: null, error: problem };
  });

/** Следующая в очереди. */
export const nextWaiting = (cards: DataCard[]): DataCard | null => cards.find((c) => c.status === "wait") ?? null;

export const withStatus = (cards: DataCard[], key: string, status: DataCard["status"], error: string | null = null): DataCard[] =>
  cards.map((c) => (c.key === key ? { ...c, status, error } : c));

/** Ответ сервера на файл карточки `key`: таблиц нет или ошибка — карточка с причиной; одна таблица — карточка
 *  разобрана; книга с листами — по карточке на лист («Регионы.xlsx · Лист1»), первая — на месте исходной. */
export function expandCard(cards: DataCard[], key: string, out: DatasetSummary[] | null, error: string | null): DataCard[] {
  return cards.flatMap((c) => {
    if (c.key !== key) return [c];
    if (error || !out?.length) return [{ ...c, status: "fail" as const, error: error ?? "Не нашёл таблицу в файле" }];
    const many = out.length > 1;
    return out.map((s, i) => ({ key: i ? `${c.key}#${i}` : c.key, file: cardName(s, many), kind: s.kind, status: "done" as const, summary: toSummary(s), error: null }));
  });
}

/** Те же наборы в том же порядке. */
export const sameIds = (a: string[], b: string[]): boolean => a.length === b.length && a.every((x, i) => x === b[i]);

/** Использованные наборы и брендбуки (на сервере их не удаляем): последние 200, без повторов. */
export const USED_MAX = 200;
export function usedAfter(used: string[], ids: string[]): string[] {
  const next = used.filter((x) => !ids.includes(x)).concat(ids.filter((x, i) => x && ids.indexOf(x) === i));
  return next.slice(-USED_MAX);
}

// ── черновик (`verstka.brief_draft`, поле `data`)
export interface DataDraft { cards: DataCard[]; brand: BrandState; priority: BrandPriority; used: string[] }
const isCard = (c: unknown): c is DataCard => {
  const o = c as Partial<DataCard> | null;
  return !!o && typeof o.key === "string" && typeof o.file === "string" && (o.status === "done" || o.status === "fail")
    && (o.status === "fail" || (!!o.summary && typeof o.summary.id === "string"));
};
/** Черновик как прочитался (испорченное — по умолчанию): разобранные и неудачные карточки (идущие не переживают
 *  перезагрузку), приложенный брендбук, что важнее, использованные. */
export function parseDataDraft(raw: unknown): DataDraft {
  const d = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const cards = Array.isArray(d.cards) ? d.cards.filter(isCard).map((c) => ({ ...c, summary: c.summary ? toSummary(c.summary) : null })) : [];
  const b = d.brand as Partial<BrandState> | null | undefined;
  const brand = b && typeof b.id === "string" && b.spec && typeof b.spec === "object"
    ? { ...brandOn(b.id, b.spec as BrandSpec, Array.isArray(b.conflicts) ? b.conflicts : [], typeof b.tplFor === "string" ? b.tplFor : null,
      b.prioFor === "template" || b.prioFor === "brand" ? b.prioFor : null), file: typeof b.file === "string" ? b.file : (b.spec as BrandSpec).file ?? "" }
    : BRAND0;
  return {
    cards, brand, priority: d.priority === "template" ? "template" : "brand",
    used: Array.isArray(d.used) ? d.used.filter((x): x is string => typeof x === "string").slice(-USED_MAX) : [],
  };
}
/** Что пишется в черновик: только разобранные и неудачные карточки (поля карточки), приложенный брендбук. */
export function draftOf(cards: DataCard[], brand: BrandState, priority: BrandPriority, used: string[]): Record<string, unknown> {
  const keep = cards.filter((c) => c.status === "done" || c.status === "fail").map((c) => ({ ...c, summary: c.summary ? toSummary(c.summary) : null }));
  const b = brand.phase === "on" && brand.id
    ? { source: brand.source, file: brand.file, id: brand.id, spec: brand.spec, conflicts: brand.conflicts, tplFor: brand.tplFor, prioFor: brand.prioFor }
    : null;
  return { cards: keep, brand: b, priority, used: used.slice(-USED_MAX) };
}

/** Куда встаёт фокус, когда карточку `key` убрали: ✕ следующей (не гаснущей) карточки, иначе предыдущей; null — карточек
 *  не осталось. */
export function focusAfter(keys: string[], key: string, out: string[]): string | null {
  const i = keys.indexOf(key);
  if (i < 0) return null;
  const live = (k: string) => k !== key && !out.includes(k);
  return keys.slice(i + 1).find(live) ?? keys.slice(0, i).reverse().find(live) ?? null;
}
