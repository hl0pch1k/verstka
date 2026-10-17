// Раскладка по ширине окна. Компьютер (от 1280 px) — колода «Слоёв» как на холсте v105: плиты с постоянной геометрией
// (812 px), помощник сужает колоду. Уже — та же колода «стопкой»: плиты по высоте своего содержимого (ui/deck/stack.ts),
// помощник и слои — плитами снизу поверх колоды. Ступени стопки:
//   lg 1024–1279 — небольшой ноутбук, планшет лёжа: поля и колонка номера плотнее, номер рядом с названием;
//   md 768–1023 — планшет: номер шага над названием, всё, что справа от названия, — строкой под ним;
//   sm до 768 — телефон: одна колонка, разделы шапки — за кнопкой меню, касания не меньше 44 px, текст не мельче 16 px.
// Компьютеру нужна и высота: холст 900 px (шапка 64 + колода 812 + поле 24) в низком окне сцена уменьшается целиком
// (ui/shell/stage.ts), но не мельче `STAGE_MIN`; окно ниже `TIER_XL_H` (= 900 × STAGE_MIN) — та же стопка, что lg, со
// своей прокруткой страницы. CSS повторяет те же границы в синтаксисе диапазонов: `(width < 1280px), (height < 675px)` —
// стопка, `(width < 1024px)` — md и уже, `(width < 768px)` — телефон, `(width >= 1280px) and (height >= 675px)` —
// компьютер (без щели между границами при нецелой ширине окна).
import { useSyncExternalStore } from "react";

export type Tier = "xl" | "lg" | "md" | "sm";

/** Нижние границы ступеней, px. */
export const TIER_XL = 1280;
/** Компьютер — и не ниже этого по высоте окна, px: холст 900 × наименьший масштаб сцены 0.75 (ui/shell/stage.ts). */
export const TIER_XL_H = 675;
export const TIER_LG = 1024;
export const TIER_MD = 768;

/** Ступень по ширине и высоте окна; ширина не известна (0, NaN) — компьютер, как до замера; высота не известна —
 *  только по ширине. Широкое, но низкое окно (ниже `TIER_XL_H`) — стопка lg. */
export function tierOf(width: number, height = Infinity): Tier {
  if (!(width > 0) || width >= TIER_XL) return height >= TIER_XL_H || !(height > 0) ? "xl" : "lg";
  if (width >= TIER_LG) return "lg";
  if (width >= TIER_MD) return "md";
  return "sm";
}

/** Колода стопкой (всё, что уже компьютера). */
export const isStack = (t: Tier): boolean => t !== "xl";

/** Помощник рядом с колодой и сужает её — только на компьютере; уже — плита снизу поверх колоды. */
export const helperBeside = (t: Tier): boolean => t === "xl";

/** Запросы ступеней — те же, что в CSS. */
export const TIER_QUERY = {
  xl: `(width >= ${TIER_XL}px) and (height >= ${TIER_XL_H}px)`,
  lg: `(width >= ${TIER_LG}px)`,
  md: `(width >= ${TIER_MD}px)`,
} as const;

/** Ступень по ответам запросов (ширина окна — та же, что видят правила CSS). */
export function tierOfQueries(q: { xl: boolean; lg: boolean; md: boolean }): Tier {
  return q.xl ? "xl" : q.lg ? "lg" : q.md ? "md" : "sm";
}

const lists = () =>
  typeof window === "undefined" || !window.matchMedia
    ? null
    : { xl: window.matchMedia(TIER_QUERY.xl), lg: window.matchMedia(TIER_QUERY.lg), md: window.matchMedia(TIER_QUERY.md) };

function snapshot(): Tier {
  const l = lists();
  return l ? tierOfQueries({ xl: l.xl.matches, lg: l.lg.matches, md: l.md.matches }) : "xl";
}

function subscribe(cb: () => void): () => void {
  const l = lists();
  if (!l) return () => {};
  const all = [l.xl, l.lg, l.md];
  for (const m of all) m.addEventListener?.("change", cb);
  return () => {
    for (const m of all) m.removeEventListener?.("change", cb);
  };
}

/** Ступень раскладки; меняется только на границе ступеней (а не на каждом пикселе ширины и высоты окна). */
export function useTier(): Tier {
  return useSyncExternalStore(subscribe, snapshot, () => "xl" as Tier);
}

/** Колода стопкой. */
export function useStack(): boolean {
  return isStack(useTier());
}

/** Телефон (уже 768): разделы — за кнопкой меню, раскладки по доскам M-create, M-build, M-result. */
export const isPhone = (t: Tier): boolean => t === "sm";
export function usePhone(): boolean {
  return isPhone(useTier());
}
