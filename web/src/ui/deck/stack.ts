// Колода стопкой (окно уже 1280 px, ui/shell/tier.ts): те же четыре плиты и те же ходы, что на компьютере (плиты ездят
// translateY 520 мс, свёрнутые лежат полосами под следующей), но места плит — не числа холста, а высоты их содержимого:
// на узком окне содержимое переносится и становится выше. Высоты меряет колода (Deck, `useStackMetrics`), здесь —
// только где из них стоит каждая плита и какой высоты колода. Видимая часть плиты — её содержимое и поле снизу той же
// величины, что сверху (на компьютере: 40 + шапка 64 + 40 = 144).

import type { Geometry, UiState } from "./geometry";

/** Замеры колоды стопкой, px. Низы — от верха плиты (с верхним полем), без нижнего поля. */
export interface StackMetrics {
  /** Поле плиты сверху (оно же — зазор под содержимым до следующей плиты). */
  pad: number;
  /** Высота полосы свёрнутой плиты. */
  strip: number;
  /** Плита 01: низ шапки и низ раскрытого шага (лента шаблонов, разбор). */
  h1: number; b1: number;
  /** Плита 02: низ шапки и низ раскрытого шага (поле, данные, цели). */
  h2: number; b2: number;
  /** Плита 03 на «Создать»: низ шапки и короткого ряда; низ «Всех параметров». */
  c3: number; m3: number;
  /** Плита 03 на «Сборке». */
  k3: number;
  /** Плита 04 «Результат». */
  r4: number;
  /** Колода не ниже этого: до низа окна (короткое содержимое — плита всё равно до края, как на компьютере). */
  min: number;
}

export interface StackGeometry {
  y: Geometry["y"];
  /** Высота колоды. */
  height: number;
}

const r = (n: number) => Math.max(0, Math.round(n));

/** Места плит и высота колоды стопкой — те же состояния, что `deckGeometry` (geometry.ts) на компьютере. */
export function stackGeometry(ui: UiState, m: StackMetrics): StackGeometry {
  const S = m.strip;
  const P = m.pad;
  const create = ui.screen === "create";
  let y: Geometry["y"];
  let end: number;
  if (!create || ui.more) {
    // «Все параметры», сборка, результат: плиты 01/02 (и 03 на результате) — полосами одна под другой
    y = [0, S, 2 * S, 0];
    if (ui.screen === "result") {
      y[3] = 3 * S;
      end = 3 * S + m.r4;
    } else if (ui.screen === "build") {
      y[3] = 2 * S;
      end = 2 * S + m.k3;
    } else end = 2 * S + m.m3;
  } else if (ui.open === "tpl") {
    // раскрыт шаблон: плита 02 — под лентой, от неё видна шапка, плита 03 — под ней
    const y2 = m.b1 + P;
    const y3 = y2 + m.h2 + P;
    y = [0, y2, y3, 0];
    end = y3 + m.c3;
  } else {
    // раскрыт текст: от плиты 01 видна шапка; «Улучшить готовую» и файлы с данными сворачивают её в полосу (как
    // на компьютере: плита 02 на 40)
    const y2 = ui.improve || ui.data ? S : m.h1 + P;
    const y3 = y2 + m.b2 + P;
    y = [0, y2, y3, 0];
    end = y3 + m.c3;
  }
  const height = r(Math.max(end + P, m.min));
  // плита 04 вне результата: на «Создать» ждёт под нижним краем колоды, на сборке — на месте плиты 03 (как на компьютере)
  if (create) y[3] = height;
  return { y: [r(y[0]), r(y[1]), r(y[2]), r(y[3])], height };
}

/** Высота колоды на ходу: колода растёт сразу (плиты едут в уже высокой колоде), а ниже становится, только когда ход
 *  кончился (`settled`) — край колоды не обрезает плиту, которая ещё едет вниз. */
export function heldHeight(next: number, prev: number, settled: boolean): number {
  return settled ? next : Math.max(next, prev);
}

/** Низ содержимого элемента относительно его родителя: верх + высота (всё в целых px). */
export const bottomOf = (top: number, height: number): number => Math.round(top + height);

/** Замеры не изменились (до пикселя) — колоду не перерисовывать. */
export function sameMetrics(a: StackMetrics | null, b: StackMetrics | null): boolean {
  if (!a || !b) return a === b;
  return (Object.keys(a) as (keyof StackMetrics)[]).every((k) => a[k] === b[k]);
}
