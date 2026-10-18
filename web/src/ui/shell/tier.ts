// Раскладка — только компьютер (решение владельца 18.10): колода «Слоёв» как на холсте v105, плиты с постоянной
// геометрией (812 px), помощник сужает колоду. Окно ниже 900 или уже 1280 — та же раскладка, уменьшенная целиком
// (ui/shell/stage.ts). Стопки и телефонной раскладки нет: ступень всегда «xl». Тип ступени и проверки оставлены, чтобы
// компоненты читались как прежде; ветки не-компьютера не срабатывают.

export type Tier = "xl" | "lg" | "md" | "sm";

/** Ширина, с которой колода — колода компьютера, px (уже — сцена уменьшается). */
export const TIER_XL = 1280;

/** Колода стопкой — никогда. */
export const isStack = (t: Tier): boolean => t !== "xl";

/** Помощник рядом с колодой и сужает её. */
export const helperBeside = (t: Tier): boolean => t === "xl";

/** Ступень раскладки — всегда компьютер. */
export function useTier(): Tier {
  return "xl";
}

/** Колода стопкой — никогда. */
export function useStack(): boolean {
  return false;
}

/** Телефон — никогда. */
export const isPhone = (t: Tier): boolean => t === "sm";
export function usePhone(): boolean {
  return false;
}
