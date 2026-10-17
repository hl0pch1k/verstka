// Колода стопкой (окно уже 1280 px, ui/shell/tier.ts): те же четыре плиты и те же ходы, что на компьютере (плиты ездят
// translateY 520 мс, свёрнутые лежат полосами под следующей), но места плит — не числа холста, а высоты их содержимого:
// на узком окне содержимое переносится и становится выше. Высоты меряет колода (Deck, `useStackMetrics`), здесь —
// только где из них стоит каждая плита и какой высоты колода. Видимая часть плиты — её содержимое и поле снизу той же
// величины, что сверху (на компьютере: 40 + шапка 64 + 40 = 144).

import { IMPROVE_GROW, IMPROVE_SHIFT } from "../create/textRules";
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
  /** Колода не ниже этого: до низа окна (короткое содержимое — плита всё равно до края, как на компьютере). На телефоне —
   *  высота колоды: от шапки до низа окна, не ниже `PHONE_MIN`. */
  min: number;
  /** Телефон: видимая часть плиты 03 на «Создать» — сводка, «Параметры», кнопка и поле снизу (M-create: 234 с полосой
   *  жестов). Не телефон — 0. */
  q3: number;
}

export interface StackGeometry {
  y: Geometry["y"];
  /** Высота колоды. */
  height: number;
  /** Телефон: видимая высота каждой плиты (до следующей или до низа колоды) — её содержимое прокручивается внутри
   *  (`--vis`, stack.css). Не телефон — нет. */
  vis?: [number, number, number, number];
}

/** Колода стопкой не ниже этого, px (короткое окно — страница прокручивается, плиты не сжимаются в щель). */
export const STACK_MIN = 480;
/** Телефон (доски M-create, M-build, M-result): полоса свёрнутой плиты, ряд плиты 01 на шаге «Текст» (обложка,
 *  название, «Сменить») и колода не ниже этого (как стопкой; ниже — телефон лёжа: страница прокручивается). */
export const PHONE_STRIP = 48;
export const PHONE_ROW = 56;
export const PHONE_MIN = STACK_MIN;

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

/** Телефон: колода во весь экран под шапкой (`m.min`), плиты — на местах досок; что не помещается в видимую часть
 *  плиты, прокручивается внутри неё.
 *    «Создать», текст: 01 — ряд 56 (файлы с данными, «Улучшить готовую» — полоса 48), 02 под ним, 03 прижата к низу
 *      (видна сводка, «Параметры» и кнопка — `m.q3`);
 *    «Создать», шаблон: 01 раскрыта, 02 — полоса над прижатой 03;
 *    «Все параметры» и сборка: 01, 02 — полосы, 03 — до низа; результат: 01–03 — полосы, 04 — до низа. */
export function phoneGeometry(ui: UiState, m: StackMetrics): StackGeometry {
  const S = PHONE_STRIP;
  const H = Math.round(m.min);
  const create = ui.screen === "create";
  let y: Geometry["y"];
  if (!create || ui.more) {
    y = [0, S, 2 * S, ui.screen === "result" ? 3 * S : ui.screen === "build" ? 2 * S : H];
  } else {
    const y3 = r(H - m.q3);
    const y2 = ui.open === "tpl" ? y3 - S : ui.improve || ui.data ? S : PHONE_ROW;
    y = [0, y2, y3, H];
  }
  // видимая часть: до следующей плиты, если та ниже; иначе (верхняя, или следующая ждёт на её месте) — до низа колоды
  const vis = (i: 0 | 1 | 2 | 3) => r((i < 3 && y[i + 1] > y[i] ? y[i + 1] : H) - y[i]);
  return { y: [r(y[0]), r(y[1]), r(y[2]), r(y[3])], height: H, vis: [vis(0), vis(1), vis(2), vis(3)] };
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

/** Колода не ниже окна: от её верха до низа окна без нижнего поля страницы; не ниже `floor` (`STACK_MIN`, `PHONE_MIN`). */
export function deckMin(innerHeight: number, deckTop: number, gut: number, floor: number): number {
  return Math.max(floor, Math.round(innerHeight - deckTop - gut));
}

/** «Улучшить готовую»: поле уходит под заметку и растёт вниз transform'ом — к низу шага «Текст» прибавляются сдвиг и
 *  рост (переменные `--tx-sh`, `--tx-gr` поля; не заданы — числа доски C-improve). */
export function improveExtra(sh: string, gr: string): number {
  const px = (v: string, none: number) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : none;
  };
  return Math.round(px(sh, IMPROVE_SHIFT) + px(gr, IMPROVE_GROW));
}
