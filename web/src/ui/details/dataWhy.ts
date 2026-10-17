// «Почему так» слайда с данными (вторая ступень; V2 v105 `dlWD`, модуль ds) без React: профиль файла («Данные»:
// файл, колонки с типом и ролью, ось времени, метрики, измерения, пропуски, выбросы, как подготовлены данные), задача
// («Задача»: какая, цель из текста, почему, все задачи с выбранной), ранжированные варианты визуализации с мини-графиками
// и доводами (выбранный — «Выбран», невыбранный — почему не он) и откуда заголовок-вывод (ключевое число, как оно
// посчитано, каким был бы заголовок-описание). Всё — из `OutlineSlide.data` (SlideData) и содержимого слайда: интерпретация
// данных — детерминированный код сервера, здесь только слова. Чистые функции, без React.
import { plural } from "../../lib/utils";
import { VIZ_TITLES } from "../../lib/vizNames";
import type {
  ColumnProfile, ColumnRole, ColumnType, HeadlineFact, OutlineSlide, SlideData, SourceKind, TaskKind, TimeFreq, Variant, VizKind, VizOption,
} from "../../types";
import { cardsOf, miniChart, miniSource, pagesOf, type MiniLayers, type MiniSource } from "./miniChart";

/** Названия задач — как у сервера (verstka/schemas/data.py `TASK_TITLES`), в порядке ТЗ. */
export const TASK_TITLES: Record<TaskKind, string> = {
  dynamics: "Динамика",
  comparison: "Сравнение категорий",
  shares: "Структура долей",
  distribution: "Распределение",
  relationship: "Взаимосвязь",
  reference: "Справочные значения",
  kpi: "Ключевые значения",
};
/** Задачи в «Задаче» (V2: шесть задач ТЗ, выбранная выделена); «Ключевые значения» — только когда это задача слайда. */
const TASK_ORDER: TaskKind[] = ["dynamics", "comparison", "shares", "distribution", "relationship", "reference", "kpi"];
const TASK_SHOWN = (k: TaskKind, task: TaskKind | null) => k !== "kpi" || task === "kpi";

/** Форма слайда в навигации «Почему так» («Слайд 4 / 9 · Полосы») — одно название на вид (lib/vizNames, как на сервере). */
export const VIZ_FORM: Record<VizKind, string> = VIZ_TITLES;

/** Тип колонки — подпись и тег, четыре вида, как на холсте (V2 `dsType`: дата — синий, число — светлый, категория —
 *  серый, текст — с обводкой); единица (₽, %) — в имени колонки, роль — рядом. */
const TYPE: Record<ColumnType, { t: string; cls: string }> = {
  number: { t: "число", cls: "dx-t-n" },
  percent: { t: "число", cls: "dx-t-n" },
  money: { t: "число", cls: "dx-t-n" },
  date: { t: "дата", cls: "dx-t-d" },
  period: { t: "дата", cls: "dx-t-d" },
  category: { t: "категория", cls: "dx-t-c" },
  boolean: { t: "категория", cls: "dx-t-c" },
  text: { t: "текст", cls: "dx-t-t" },
  id: { t: "текст", cls: "dx-t-t" },
};
const ROLE: Record<ColumnRole, string> = {
  time: "ось времени", dimension: "измерение", metric: "метрика", id: "идентификатор", text: "подпись", attribute: "атрибут",
};
const KIND_LABEL: Record<SourceKind, string> = { csv: "CSV", tsv: "TSV", xlsx: "XLSX", json: "JSON", text: "TXT" };

/** Колонок в списке — не больше; остальные — строкой «и ещё N». */
export const MAX_COLS = 8;

export interface DxCol { name: string; type: string; tcls: string; role: string }
/** Строка профиля: `warn` — пропуски и выбросы (жёлтым, со значком), `info` — что важно для вёрстки (синим). */
export interface DxFact { k: string; v: string; tone: "warn" | "info" | null }
export interface DxVar {
  /** Номер варианта в `options` (для «Пересобрать слайд так»). */
  k: number;
  /** Место в ранжировании (лучший по данным — первым). */
  n: number;
  name: string;
  /** Довод: выбранного — почему он; невыбранного — почему не он. */
  why: string;
  /** Пометка под доводом: выбранный по просьбе, хотя анализ ставил его ниже. */
  note: string | null;
  on: boolean;
  label: string;
  mini: MiniLayers;
}
export interface DataWhyView {
  /** Форма выбранного варианта — в навигации. */
  form: string;
  file: string;
  /** Формат файла (значок — dsKit `fileIcon`); не узнать — null. */
  kind: SourceKind | null;
  /** «XLSX · 8 строк × 3 колонки · сравнение». */
  meta: string;
  cols: DxCol[];
  /** Колонок не показано (их больше MAX_COLS). */
  more: number;
  facts: DxFact[];
  task: string;
  goal: string | null;
  taskWhy: string;
  kinds: { t: string; on: boolean }[];
  vars: DxVar[];
  /** Ключевое число заголовка («41 %», «+23 %»), как оно посчитано и тема, которой заголовок не стал. */
  key: string | null;
  from: string | null;
  plain: string | null;
  /** Последнее изменение варианта — пересборка этого слайда: у выбранного варианта «Вернуть как было». */
  undoable: boolean;
  /** Слайд, который выбрать после «Вернуть как было» (первый слайд пересборки). */
  first: number;
}

const nf = (max = 2) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: max });
/** Число по-русски: «1 433», «1,24». */
export const fmtNum = (v: number): string => nf(Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 10 ? 1 : 2).format(v).replace(/\u202f/g, "\u00a0");

const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const ROMAN = ["I", "II", "III", "IV"];

/** Период оси времени по-русски: «2025-01» → «январь 2025», «2026-Q3» → «III кв. 2026», «2025-W05» → «5-я неделя 2025», «2025-01-31» → «31 января
 *  2025»; непонятное — как есть. */
export function periodText(iso: string): string {
  const s = iso.trim();
  let m = s.match(/^(\d{4})-Q([1-4])$/i);
  if (m) return `${ROMAN[Number(m[2]) - 1]}\u00a0кв. ${m[1]}`;
  // ISO-неделя: «2025-W05» → «5-я неделя 2025»
  m = s.match(/^(\d{4})-W(\d{1,2})$/i);
  if (m && Number(m[2]) >= 1 && Number(m[2]) <= 53) return `${Number(m[2])}-я неделя ${m[1]}`;
  m = s.match(/^(\d{4})-(\d{2})$/);
  if (m && Number(m[2]) >= 1 && Number(m[2]) <= 12) return `${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?/);
  if (m && Number(m[2]) >= 1 && Number(m[2]) <= 12) return `${Number(m[3])}\u00a0${MONTHS_GEN[Number(m[2]) - 1]} ${m[1]}${m[4] ? `, ${m[4]}:${m[5]}` : ""}`;
  return s;
}

const FREQ: Record<TimeFreq, [string, string, string]> = {
  hour: ["час", "часа", "часов"], day: ["день", "дня", "дней"], week: ["неделя", "недели", "недель"],
  month: ["месяц", "месяца", "месяцев"], quarter: ["квартал", "квартала", "кварталов"], year: ["год", "года", "лет"],
  irregular: ["точка", "точки", "точек"],
};

const withUnit = (c: Pick<ColumnProfile, "name" | "unit">) => (c.unit ? `${c.name}, ${c.unit}` : c.name);

/** Строки профиля: ось времени, метрики, измерения, пропуски, выбросы (у набора без оси времени — измерения первыми),
 *  как подготовлены данные слайда, часть разбитого на слайды набора. */
export function dataFacts(d: SlideData): DxFact[] {
  const byName = new Map(d.columns.map((c) => [c.name, c]));
  const t = d.time_axis;
  const metrics = d.metrics.map((m) => withUnit(byName.get(m) ?? { name: m, unit: null }));
  const time: DxFact = {
    k: "Ось времени",
    v: t ? `${periodText(t.start)} — ${periodText(t.end)}, ${plural(t.points, ...FREQ[t.freq])}` : "нет",
    tone: null,
  };
  const met: DxFact = { k: "Метрики", v: metrics.length ? metrics.join(" · ") : "нет", tone: null };
  const dims: DxFact = {
    k: "Измерения",
    v: d.dimensions.length
      ? d.dimensions.map((n) => {
        const c = byName.get(n);
        return c?.distinct ? `${n} — ${plural(c.distinct, "значение", "значения", "значений")}` : n;
      }).join(" · ")
      : t && d.metrics.length === 1 ? "нет — один ряд" : "нет",
    tone: null,
  };
  const gaps = t?.missing_periods ?? [];
  const miss: DxFact = gaps.length
    ? { k: "Пропуски", v: `${gaps.length} из ${t!.points}: ${gaps.map(periodText).join(", ")}`, tone: "warn" }
    : d.missing_total > 0 ? { k: "Пропуски", v: plural(d.missing_total, "пустая ячейка", "пустые ячейки", "пустых ячеек"), tone: "warn" }
      : { k: "Пропуски", v: "нет", tone: null };
  const outs = d.outliers ?? [];
  const out: DxFact = outs.length
    ? { k: "Выбросы", v: `${plural(outs.length, "значение", "значения", "значений")}: ${outs.slice(0, 4).map((o) => fmtNum(o.value)).join(", ")}${outs.length > 4 ? "…" : ""}`, tone: "warn" }
    : { k: "Выбросы", v: "нет", tone: null };
  const rows = t ? [time, met, dims, miss, out] : [dims, met, time, miss, out];
  if (d.aggregation) rows.push({ k: "На слайде", v: d.aggregation, tone: "info" });
  if (d.part && d.part[1] > 1) rows.push({ k: "Часть", v: `слайд ${d.part[0]} из ${d.part[1]}`, tone: "info" });
  return rows;
}

/** Числа заголовка по порядку: значение, стоит ли за ним «%», был ли знак («+23%»). Номер в слове («Топ-10») — не число. */
function headlineNumbers(text: string): { v: number; pct: boolean; signed: boolean }[] {
  const out: { v: number; pct: boolean; signed: boolean }[] = [];
  const t = text.replace(/(\d)[\s\u00a0\u202f](?=\d{3}(?!\d))/g, "$1");
  const re = /(^|[^\p{L}\d-])([+−-]?)(\d+(?:[.,]\d+)?)(\s?%)?/gu;
  for (let m = re.exec(t); m; m = re.exec(t)) {
    out.push({ v: Number(m[3].replace(",", ".")), pct: !!m[4], signed: !!m[2] });
  }
  return out;
}

/** Факт, из которого число заголовка: сначала числа с «%», потом остальные; к «+N%» — изменение. Нет такого — null. */
export function keyFact(headline: string, facts: HeadlineFact[]): HeadlineFact | null {
  const nums = headlineNumbers(headline);
  const order = [...nums.filter((x) => x.pct), ...nums.filter((x) => !x.pct)];
  const near = (a: number, b: number) => Math.abs(a - b) <= Math.max(0.05, Math.abs(b) * 0.005);
  for (const x of order) {
    const hits = facts.filter((fct) => near(Math.abs(fct.value), x.v) && (!x.pct || fct.unit === "%"));
    if (!hits.length) continue;
    return (x.signed ? hits.find((h) => h.kind === "change") : null) ?? hits.find((h) => h.kind !== "count") ?? hits[0];
  }
  return null;
}

/** Ключевое число крупно: «41 %», «+23 %», «1 433 млн ₽», «52». */
export function keyText(fct: HeadlineFact): string {
  const sign = fct.kind === "change" && fct.value > 0 ? "+" : fct.value < 0 ? "−" : "";
  const num = `${sign}${fmtNum(Math.abs(fct.value))}`;
  return fct.unit ? `${num}\u00a0${fct.unit}` : num;
}

/** Последнее изменение варианта — пересборка слайда `n` (её «верни как было» вернёт прежний вариант). */
export function rebuiltLast(v: Pick<Variant, "edits">, n: number): boolean {
  const last = v.edits?.[v.edits.length - 1];
  return !!last && last.kind === "rebuild" && last.slides.includes(n);
}

/** Первый слайд пересборки, которую вернёт «Вернуть как было» (после возврата — его и выбрать: таблица на несколько
 *  слайдов снова одна — номера после неё другие); нет такой — сам слайд. */
export function rebuiltFirst(v: Pick<Variant, "edits">, n: number): number {
  const last = v.edits?.[v.edits.length - 1];
  return last && last.kind === "rebuild" && last.slides.length ? Math.min(...last.slides) : n;
}

/** У заголовка нет числа из данных (тема, а не вывод — данные не дали вывода). */
export const NO_KEY = "В данных не нашлось числа для вывода — заголовок называет тему.";

const sentence = (parts: string[]) => parts.map((p) => p.trim()).filter(Boolean).map((p) => (/[.!?…]$/.test(p) ? p : `${p}.`)).join(" ");

/** Довод варианта: выбранный — почему он; невыбранный — почему не он (а нет такого — почему подходит). */
function optionWhy(o: VizOption, on: boolean): { why: string; note: string | null } {
  if (on) return { why: sentence(o.reasons), note: o.why_not ? `Анализ ставил его ниже: ${o.why_not.replace(/[.\s]+$/, "")}.` : null };
  return { why: o.why_not ? sentence([o.why_not]) : sentence(o.reasons), note: null };
}

/** Сколько значений в тексте эскиза — первые, дальше «…». */
const SAID = 4;

/** Текст эскиза для тех, кто его не видит: числа, которые он рисует («Москва 1 433, Санкт-Петербург 612, Екатеринбург
 *  318, Казань 274… — 8 значений»), или его строение (таблица, карточки, разбиение, разные единицы). */
export function miniText(o: Pick<VizOption, "kind" | "title">, src: MiniSource, task: TaskKind | null): string {
  if (o.kind === "table") {
    const p = pagesOf(o);
    if (p) return `${plural(p, "слайд", "слайда", "слайдов")} по частям таблицы`;
    return src.rows ? `таблица: ${plural(src.rows, "строка", "строки", "строк")} × ${plural(src.cols, "колонка", "колонки", "колонок")}` : "таблица";
  }
  if (o.kind === "kpi_cards") {
    const k = cardsOf(task, src);
    return k ? plural(k, "карточка", "карточки", "карточек") : "чисел для карточек нет";
  }
  if (src.mixed) return `${plural(src.mixed, "значение", "значения", "значений")} в разных единицах — только строение, без сравнения`;
  if (o.kind === "scatter") return src.xy ? plural(src.xy.x.length, "точка", "точки", "точек") : "точек нет";
  const vs = src.series[0] ?? [];
  if (!vs.some((v) => v !== null)) return "чисел нет";
  const one = (v: number | null, i: number) => {
    const t = v === null ? "нет данных" : fmtNum(v);
    const l = (src.labels[i] ?? "").trim();
    return l ? `${l} ${t}` : t;
  };
  const head = vs.slice(0, SAID).map(one).join(", ");
  return vs.length > SAID ? `${head}… — ${plural(vs.length, "значение", "значения", "значений")}` : head;
}

/** Колонки списка «Колонки»: имя с единицей, тип, роль. */
export function dataCols(d: SlideData): { cols: DxCol[]; more: number } {
  const cols = d.columns.slice(0, MAX_COLS).map((c) => ({ name: withUnit(c), type: TYPE[c.type]?.t ?? c.type, tcls: TYPE[c.type]?.cls ?? "dx-t-c", role: ROLE[c.role] ?? c.role }));
  return { cols, more: Math.max(0, d.columns.length - MAX_COLS) };
}

/** «Почему так» слайда `n` варианта `v` с данными `d` (OutlineSlide.data). */
export function dataWhyView(v: Variant, n: number, slide: OutlineSlide, d: SlideData): DataWhyView {
  const chosen = d.options[d.chosen] ?? d.options[0] ?? null;
  const src = miniSource(slide, d, v.outline?.slides);
  const kind: SourceKind | null = (Object.keys(KIND_LABEL) as SourceKind[]).find((k) => d.profile_line.startsWith(KIND_LABEL[k])) ?? null;
  const task = d.task?.task ?? null;
  const fct = keyFact(slide.headline, d.headline_facts);
  const plain = d.plain_headline.trim();
  const { cols, more } = dataCols(d);
  return {
    form: chosen ? VIZ_FORM[chosen.kind] ?? chosen.title : "Данные",
    file: d.file,
    kind: kind ?? (/\.json$/i.test(d.file) ? "json" : /\.(txt|md)$/i.test(d.file) ? "text" : null),
    meta: d.profile_line,
    cols,
    more,
    facts: dataFacts(d),
    task: task ? `${TASK_TITLES[task]}${task === "dynamics" && d.nature === "with_gaps" ? " с пропусками" : ""}` : "Справочные значения",
    goal: d.task?.goal ? `Цель из текста: «${d.task.goal}»` : null,
    taskWhy: sentence(d.task?.reasons ?? []),
    kinds: TASK_ORDER.filter((k) => TASK_SHOWN(k, task)).map((k) => ({ t: TASK_TITLES[k], on: k === task })),
    vars: d.options.map((o, k) => {
      const on = k === d.chosen;
      return { k, n: k + 1, name: o.title, ...optionWhy(o, on), on, label: `Вариант ${k + 1}: ${o.title}. ${miniText(o, src, task)}`, mini: miniChart(o, src, task) };
    }),
    key: fct ? keyText(fct) : null,
    from: fct ? fct.explain || fct.text : NO_KEY,
    plain: plain && plain !== slide.headline.trim() ? plain : null,
    undoable: rebuiltLast(v, n),
    first: rebuiltFirst(v, n),
  };
}

/** Подпись навигации «Почему так» слайда с данными: «Слайд 4 / 9 · Горизонтальные столбцы» — форма выбранного варианта. */
export function dataWhyCap(w: { n: number; total: number }, d: SlideData): string {
  const o = d.options[d.chosen] ?? d.options[0];
  return `Слайд ${w.n} / ${w.total} · ${o ? VIZ_FORM[o.kind] ?? o.title : "Данные"}`;
}
