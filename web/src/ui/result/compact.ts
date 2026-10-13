// Компактный вид «Результата» без React (boards/G-helper, G-helper-open; V2 `hp-ncol`): итоги проверки в узкой колонке
// 184 px — качество, сверенные числа (оба открывают «Подробнее» на «Качестве») и откуда текст. Числа — те же, что у карточки «Качество» полного вида
// (qualityCard), чего в данных нет — того пункта нет.
import { templateTitle } from "../../lib/plain";
import type { Generation, Variant } from "../../types";
import { PLATE_PAD, type DeckFit } from "../deck/fit";
import type { SheetTab } from "../deck/geometry";
import type { IconName } from "../kit/icons";
import { qualityCard } from "./resultView";

/** Пункт итогов: значок, жирное начало и остальное; `title` — подсказка целиком; `sheet` — вкладка «Подробнее», которую
 *  пункт открывает (качество и числа — «Качество»; источник текста — ничего). */
export interface CheckItem { icon: IconName; tone: "ok" | "warn" | "error"; lead: string; rest: string; title: string; sheet?: SheetTab }

const pages = (g: Generation) => {
  const w = g.writer;
  const list = (w?.pages ?? []).filter((p) => p?.title);
  return list.length ? list : w?.source?.title ? [w.source] : [];
};

/** Откуда текст (V2 `hpSrc`): агент по статье Википедии, «Улучшить готовую» — исходная презентация, уведомление
 *  результата — его заголовок, иначе свой текст. */
export function sourceText(g: Generation, note: { title: string } | null): string {
  if (g.writer?.status === "written" && g.writer.text) {
    const p = pages(g);
    if (!p.length) return "Текст написал агент по своим знаниям — проверьте даты и цифры";
    const names = p.map((x, i) => `${i === 0 ? "" : i === p.length - 1 ? " и " : ", "}«${x.title}»`).join("");
    return `Текст написал агент — по ${p.length > 1 ? "статьям" : "статье"} ${names} в Википедии`;
  }
  if (g.improved_from?.name) return `Текст из презентации «${templateTitle(g.improved_from.name)}»`;
  return note?.title || "Ваш текст — агент разложил его по слайдам";
}

/** «9 чисел сверены с текстом» → «9 чисел» и « сверены с текстом». */
function splitCount(text: string): { lead: string; rest: string } {
  const m = /^(\d[\d\s ]*\S+)(.*)$/.exec(text);
  return m ? { lead: m[1], rest: m[2] } : { lead: "", rest: text };
}

/** Итоги проверки узкой колонки: качество (ошибки · предупреждения), сверенные числа, источник текста. */
export function compactChecks(g: Generation, v: Variant, note: { title: string } | null): CheckItem[] {
  const out: CheckItem[] = [];
  const q = qualityCard(g, v);
  if (q) {
    out.push({
      icon: q.errors ? "alert" : "check-circle", tone: q.errors ? "error" : "ok",
      lead: q.verdict ?? `Оценка ${q.score}`, rest: q.warnings ? ` · ${q.warnings}` : "", title: q.title, sheet: "quality",
    });
    if (q.figures) out.push({ icon: "numbers", tone: q.figures.tone, ...splitCount(q.figures.text), title: q.figures.title ?? q.figures.text, sheet: "quality" });
  }
  const src = sourceText(g, note);
  out.push({ icon: "book", tone: "ok", lead: "", rest: src, title: src });
  return out;
}

// ── шапка компактного вида: название, значки-действия (40 px через 8) и «Скачать PowerPoint» (285 px, отступ 8 + 8)
const ICON = 40;
const ICON_GAP = 8;
const CTA_FULL = 285;
const HEAD_GAP = 24;
/** Названию в шапке — не меньше 320 px (около 13 букв заголовка 32 px): уже — и оно сжимается до нескольких букв. */
export const TITLE_MIN = 320;

/** «PowerPoint» вместо «Скачать PowerPoint» в шапке компактного вида: рядом с `icons` значками (уведомление «i» +
 *  пять действий) полной подписи и названию не хватает места. Решение — по целевой ширине колоды (раскладка колоды,
 *  `useDeckWidth`), а не по кадру хода: при 1440 полная подпись остаётся с пятью значками (G-helper) и уступает с шестью,
 *  при 1280 — всегда короткая. 0 — ширина ещё не измерена: полная. */
export function ctaShort(deck: number, icons: number): boolean {
  if (!(deck > 0)) return false;
  const right = icons * (ICON + ICON_GAP) + ICON_GAP + CTA_FULL;
  return deck - PLATE_PAD - right - HEAD_GAP < TITLE_MIN;
}

/** Шапка рабочей области в тесной колоде (помощник при 1280) рядом с широкой колонкой (замечания, изображение): 376 px —
 *  подпись «Замечания» у переключателя уходит (остаётся для чтения с экрана), ряд плотнее. Смена — перекрёстным
 *  затуханием шапки (ResultPlate), а не мгновенно. */
export const headTight = (fit: DeckFit, wide: boolean): boolean => fit === "tight" && wide;
