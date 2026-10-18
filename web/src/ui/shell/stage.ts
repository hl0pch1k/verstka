// Сцена — только компьютер (решение владельца 18.10: стопки и телефонной раскладки нет). Раскладка — холст v105
// постоянной геометрии: шапка 64 + колода 812 + поле 24 = 900 px по высоте, колода не уже 1280 px. Окно ниже 900 или
// уже 1280 — вся страница уменьшается равномерно (CSS `zoom`), как картинка: раскладка та же, только мельче, и видна
// целиком, без прокрутки. Масштаб округляется вниз до шага 1/40 — при каждом размере окна один и тот же, без дробной
// дрожи на ходу.
//
// Почему zoom, а не transform: transform: scale в Safari переводит уменьшенную страницу из документа в слой и обратно,
// как только внутри начинается ход transform (наведение, смена слайда), — при дробном масштабе пиксели округляются
// по-разному, и экран дрожит. zoom перекладывает страницу без слоя. Ширина страницы задаётся в px (а не в %): px zoom
// умножает одинаково в Chrome (стандартный zoom) и Safari (WebKit). Замеры, которые пишут px в стили или прокрутку,
// переводят getBoundingClientRect обратно в px раскладки (`layoutRect`): во сколько раз — замер самой страницы
// (`stageOf`), так что верно в любом движке.
import { useSyncExternalStore } from "react";

/** Высота холста компьютера, px: шапка 64 + колода 812 (geometry.ts `DECK_H`) + поле страницы снизу 24. */
export const STAGE_H = 900;
/** Ширина, уже которой колода не становится, px. */
export const STAGE_W = 1280;
/** Шаг масштаба: вниз до 1/40. */
const STEP = 40;
/** Мельче сцена не становится. */
export const STAGE_MIN = 0.25;

/** Масштаб сцены по окну: не ниже холста и не уже 1280 — 1 (как на доске); иначе — чтобы холст поместился и по высоте, и
 *  по ширине, вниз до шага 1/40, не мельче `STAGE_MIN`. Размер не известен — 1. */
export function stageScale(width: number, height: number): number {
  const kh = height > 0 ? height / STAGE_H : 1;
  const kw = width > 0 ? width / STAGE_W : 1;
  const k = Math.min(1, kh, kw);
  if (k >= 1) return 1;
  return Math.max(STAGE_MIN, Math.floor(k * STEP + 1e-9) / STEP);
}

/** Стили обёртки и страницы при масштабе `k` и ширине окна `width`: обёртка — высотой с уменьшенную сцену (страница
 *  не прокручивается, лишнее — clip; высота — вниз до целого px), страница — `zoom: k`, шириной в px (окно / k) и
 *  высотой с холст. k = 1 — ничего (раскладка как без сцены). */
export function stageStyles(k: number, width: number): { fit?: Record<string, string | number>; root?: Record<string, string | number> } {
  if (!(k > 0) || k >= 1) return {};
  return {
    fit: { height: Math.floor(STAGE_H * k + 0.001), overflow: "clip", background: "#F3F4F1" },
    root: { width: Math.floor((width > 0 ? width : STAGE_W) / k), height: STAGE_H, minHeight: 0, zoom: k },
  };
}

const subscribe = (cb: () => void) => {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("resize", cb);
  return () => window.removeEventListener("resize", cb);
};
const size = () => (typeof window === "undefined" ? "0x0" : `${window.innerWidth}x${window.innerHeight}`);

/** Ширина и высота окна (CSS px); обновляются синхронно с resize — новая сцена встаёт до того, как её замерят
 *  наблюдатели. */
export function useWindowSize(): { width: number; height: number } {
  const [w, h] = useSyncExternalStore(subscribe, size, () => "0x0").split("x").map(Number);
  return { width: w, height: h };
}

/** Атрибут страницы с масштабом сцены: по нему замеры узнают, в каких px их прямоугольники. */
export const STAGE_ATTR = "data-stage";

/** Во сколько раз прямоугольники getBoundingClientRect узла меньше px раскладки (вне сцены и без уменьшения — 1):
 *  замер самой страницы сцены — её прямоугольник к её ширине раскладки (offsetWidth). Так верно и там, где движок
 *  отдаёт прямоугольники уже в px раскладки (отношение — 1). */
export function stageOf(node: Node | null | undefined): number {
  const el: Element | null | undefined = node && "closest" in node ? (node as Element) : node?.parentElement;
  const root = el?.closest?.(`[${STAGE_ATTR}]`) as HTMLElement | null | undefined;
  if (!root) return 1;
  const w = root.offsetWidth;
  const k = w > 0 ? root.getBoundingClientRect().width / w : Number(root.getAttribute(STAGE_ATTR));
  return k > 0 && k < 0.999 ? k : 1;
}

export interface LayoutRect { left: number; top: number; right: number; bottom: number; width: number; height: number }

/** Прямоугольник в px окна → в px раскладки сцены с масштабом `k`. */
export function unscale(r: LayoutRect, k: number): LayoutRect {
  if (k === 1) return r;
  return { left: r.left / k, top: r.top / k, right: r.right / k, bottom: r.bottom / k, width: r.width / k, height: r.height / k };
}

/** getBoundingClientRect в px раскладки: разности и размеры — те же числа, что без уменьшения сцены. */
export function layoutRect(el: Element): LayoutRect {
  return unscale(el.getBoundingClientRect(), stageOf(el));
}

/** Ширина по getBoundingClientRect (с дробной частью и transform'ами внутри) в px раскладки. */
export const layoutWidth = (el: Element): number => layoutRect(el).width;

/** Прямоугольник Range в px раскладки (масштаб — по общему предку его границ). */
export function rangeRect(r: Range): LayoutRect {
  return unscale(r.getBoundingClientRect(), stageOf(r.commonAncestorContainer));
}
