// Сцена компьютера в низком окне. Раскладка от 1280 px — холст v105 постоянной геометрии: шапка 64 + колода 812 +
// поле 24 = 900 px по высоте. Окно ниже — вся страница уменьшается равномерно (transform: scale от левого верхнего
// угла), как картинка: раскладка та же, пиксель в пиксель, только мельче, и видна целиком, без прокрутки. Ширина
// сцены — ширина окна / масштаб, так что по ширине компьютер остаётся компьютером (колода до 1392, по центру).
// Мельче `STAGE_MIN` текст уже не читается — окно ниже `TIER_XL_H` (tier.ts) получает стопку lg с прокруткой страницы.
//
// Почему transform, а не zoom: zoom меняет раскладку по-разному в Chrome (стандартный, со 128) и Safari (старый
// WebKit), и getBoundingClientRect под ним в них не совпадает; transform одинаков везде, попадания мыши и фокус он
// пересчитывает сам, а раскладку не трогает — ResizeObserver, offset*, scroll* остаются в px раскладки. Отличается
// только getBoundingClientRect (и прямоугольники Range): они в px окна — замеры, которые пишут px в стили или
// прокрутку, переводят их обратно (`layoutRect`, `layoutWidth`).
import { useSyncExternalStore } from "react";

/** Высота холста компьютера, px: шапка 64 + колода 812 (geometry.ts `DECK_H`) + поле страницы снизу 24. */
export const STAGE_H = 900;
/** Мельче сцена не становится (TIER_XL_H = STAGE_H × STAGE_MIN). */
export const STAGE_MIN = 0.75;

/** Масштаб сцены по высоте окна: окно не ниже холста — 1 (как на доске), ниже — во всю высоту окна, не мельче
 *  `STAGE_MIN`. Не компьютер (стопка, телефон) — 1: там страница прокручивается. Высота не известна — 1. */
export function stageScale(height: number, desktop: boolean): number {
  if (!desktop || !(height > 0) || height >= STAGE_H) return 1;
  return Math.max(STAGE_MIN, height / STAGE_H);
}

/** Страница в уменьшенной сцене — всегда свой слой (`translateZ(0)`): иначе Safari делает её слоем только на время
 *  наведения (у кнопки или миниатюры внутри начался ход transform — уменьшенный предок обязан стать слоем) и снова
 *  рисует её в документ по окончании; при дробном масштабе пиксели при этом округляются по-разному, и вся страница
 *  на миг сдвигается — слайд «подпрыгивает», правая колонка съезжает (замечание владельца 18.10, скрин 20). Слой
 *  растеризуется в своём масштабе (3D-перенос нулевой, will-change не замораживает растр). */
/** Стили обёртки и страницы при масштабе `k`: обёртка — высотой с уменьшенную сцену (страница не прокручивается,
 *  лишнее — clip, без полосы и без прокрутки фокусом; высота — вниз до целого px, иначе дробная доля
 *  пикселя дала бы прокрутку на 1 px), страница — шире окна в 1/k раз и уменьшена от левого верхнего
 *  угла. k = 1 — ничего (раскладка как без сцены). */
export function stageStyles(k: number): { fit?: Record<string, string | number>; root?: Record<string, string | number> } {
  if (!(k > 0) || k >= 1) return {};
  return {
    fit: { height: Math.floor(STAGE_H * k + 0.001), overflow: "clip", background: "#F3F4F1" },
    root: { width: `${100 / k}%`, height: STAGE_H, minHeight: 0, transform: `scale(${k}) translateZ(0)`, transformOrigin: "0 0" },
  };
}

const subscribe = (cb: () => void) => {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("resize", cb);
  return () => window.removeEventListener("resize", cb);
};
const height = () => (typeof window === "undefined" ? 0 : window.innerHeight);

/** Высота окна (CSS px); обновляется синхронно с resize — новая сцена встаёт до того, как её замерят наблюдатели. */
export function useWindowHeight(): number {
  return useSyncExternalStore(subscribe, height, () => 0);
}

/** Атрибут страницы с масштабом сцены: по нему замеры узнают, в каких px их прямоугольники. */
export const STAGE_ATTR = "data-stage";

/** Масштаб сцены, в которой стоит узел (вне сцены и без уменьшения — 1). */
export function stageOf(node: Node | null | undefined): number {
  const el: Element | null | undefined = node && "closest" in node ? (node as Element) : node?.parentElement;
  const v = el?.closest?.(`[${STAGE_ATTR}]`)?.getAttribute(STAGE_ATTR);
  const k = v ? Number(v) : 1;
  return k > 0 && k < 1 ? k : 1;
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
