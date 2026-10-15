// «Создать» перестраивается вместе с колодой (V2 версии 100, блок «Колода, суженная помощником»): содержимое плит идёт
// за шириной колоды каждый кадр, всё, что в узкой раскладке другое, выражено тем, что интерполируется на кривой хода, —
// дорожками сеток с тем же числом дорожек (лишняя сжимается до нуля), прозрачностью на месте (hp-wo / hp-no) и
// стопками из двух копий текста (hp-tx). Здесь — то, что зависит от ширины окна: обе раскладки считаются сразу, по
// ширине обёртки колоды (`hp-wrap` не анимируется: закрыт помощник — колода во всю обёртку, открыт — на 416 у́же), и
// ставятся переменными CSS; правила create.css переключают их классом `hp-nar`. Решения по порогам (переключатели в
// коротком ряду, степпер в узком, тесная раскладка «Все параметры») не меняются посреди хода — меняется только окно.

/** Место помощника в обёртке колоды: плита 400 + зазор 16. */
export const HELPER_COL = 416;
/** Поля плиты (48 + 48). */
const PLATE_PAD = 96;
/** Тела шагов (`#p2-b1`, `#p2-b2`, `#p2-b3`) — от 192 px слева. */
const BODY_LEFT = 192;
/** «Все параметры» (`#p2-b3m`): слева 240, справа 48. */
const MORE_PAD = 288;
/** Межколонник. */
const GAP = 16;

/** Варианту в коротком ряду со строкой описания и галочкой справа нужно 173 px — уже, и переключатели уходят в «Все
 *  параметры» (окно около 1280). */
export const VARIANT_FULL = 173;
/** В узкой раскладке у варианта только название (самое длинное — 106 px) и поля 16 + 16. */
export const VARIANT_NAME = 138;
/** Колонке названия переключателя в «Все параметры» (узкая раскладка) нужно 96 px — самое длинное слово
 *  «Генерировать»; уже — переключатели встают строками (тесная раскладка). */
export const SWITCH_NAME = 96;
/** Миниатюра варианта в «Все параметры»: 156 (доска), 112 — когда короткий ряд без переключателей (`.pp-short`). */
export const THUMB = 156;
export const THUMB_SHORT = 112;
/** Степпер слайдов в первом ряду «Все параметры» в тесной раскладке — по содержимому (−, число, +, поля 12). */
export const SLIDES_TIGHT = 168;

const px = (n: number) => `${Math.round(n * 1000) / 1000}px`;
const fr = "minmax(0, 1fr)";

/** Ширины колоды: закрыт помощник / открыт (0 — обёртка ещё не измерена: как на доске при 1440). */
export function deckWidths(wrap: number): { wide: number; narrow: number } {
  const w = wrap > 0 ? wrap : 1392;
  return { wide: w, narrow: w - HELPER_COL };
}

export interface ParamsRow {
  /** Дорожки `#p2-b3` в широкой и узкой раскладке (одинаковое число: степпер, n вариантов, переключатели). Межколонник —
   *  поле справа у каждой клетки (16), лишнее поле последней уходит за край (`margin-right:-16px`): дорожка с нулём
   *  сжимается вместе со своим полем. */
  wide: string;
  narrow: string;
  /** Переключатели в коротком ряду широкой раскладки (иначе их дорожка — 0 в обеих). */
  switches: boolean;
  /** Степпер в узкой раскладке (иначе его дорожка сжимается до нуля, и он гаснет на месте). */
  stepper: boolean;
  /** На сколько вариант у́же в узкой раскладке: строка описания держит ширину покоя, пока гаснет (`.pp-vdi`). */
  shrink: number;
}

/** Короткий ряд плиты 03 (`#p2-b3`) при `n` вариантах. */
export function paramsRow(wrap: number, n: number): ParamsRow {
  const { wide, narrow } = deckWidths(wrap);
  const k = Math.max(1, n);
  const row = (deck: number) => deck - PLATE_PAD - BODY_LEFT + GAP; // клетки с полями 16
  const cell = (deck: number, stepper: number, sw: number) => (row(deck) - stepper - sw) / k - GAP; // вариант без поля
  const switches = cell(wide, 216 + GAP, 264 + GAP) >= VARIANT_FULL;
  const stepper = cell(narrow, 200 + GAP, 0) >= VARIANT_NAME;
  const sw = switches ? 264 + GAP : 0;
  const st = stepper ? 200 + GAP : 0;
  const vars = (s: number, w: number) => [px(s), ...Array.from({ length: k }, () => fr), px(w)].join(" ");
  return {
    wide: vars(216 + GAP, sw),
    narrow: vars(st, 0),
    switches,
    stepper,
    shrink: Math.max(0, Math.round((cell(wide, 216 + GAP, sw) - cell(narrow, st, 0)) * 1000) / 1000),
  };
}

export interface MoreGrid {
  /** Тесная раскладка «Все параметры» (помощник при окне около 1280): переключатели — строками. */
  tight: boolean;
  /** Первый ряд (тип · аудитория · слайдов) в широкой и узкой раскладке: в тесной степпер — по содержимому. */
  r1Wide: string;
  r1Narrow: string;
  /** Миниатюра варианта в широкой раскладке. */
  thumb: number;
  /** На сколько клетка подсказки варианта у́же в узкой раскладке (стопка `c-vhint`; отрицательное — шире: миниатюра уходит;
   *  в тесной поля варианта по бокам 16 → 12). */
  vhint: number;
}

/** «Все параметры» (`#p2-b3m`) при `n` вариантах; `short` — короткий ряд без переключателей (миниатюры меньше). */
export function moreGrid(wrap: number, n: number, short: boolean): MoreGrid {
  const { wide, narrow } = deckWidths(wrap);
  const k = Math.max(1, n);
  const W = wide - MORE_PAD, N = narrow - MORE_PAD;
  const third = (w: number) => (w - 2 * GAP) / 3;
  const tight = third(N) - 48 - 44 - GAP < SWITCH_NAME;
  const thumb = short ? THUMB_SHORT : THUMB;
  const card = (w: number) => (w - (k - 1) * GAP) / k;
  const r1Wide = [px(third(W)), px(third(W)), px(third(W))].join(" ");
  const rest = (N - 2 * GAP - SLIDES_TIGHT) / 2;
  const r1Narrow = tight ? [px(rest), px(rest), px(SLIDES_TIGHT)].join(" ") : [px(third(N)), px(third(N)), px(third(N))].join(" ");
  return {
    tight,
    r1Wide,
    r1Narrow,
    thumb,
    vhint: Math.round(((card(W) - 32 - thumb - GAP) - (card(N) - (tight ? 24 : 32))) * 1000) / 1000,
  };
}

/** Подсказка о готовом тексте в ряду шапки шага 02 в узкой раскладке: «Готовый текст — агент разложит его по слайдам»
 *  (372 px со значком) помещается рядом с «Из файла», пока колода не у́же 960; уже (окно около 1280) — «Это готовый
 *  текст» (целиком — в подсказке). */
export const readyShort = (wrap: number): boolean => deckWidths(wrap).narrow < 960;
/** «Создать презентацию» (312 px) рядом с названием шага в 24 px — пока колода не у́же 940; уже — «Создать»:
 *  «презентацию» сжимается и гаснет на месте. */
export const ctaShort = (wrap: number): boolean => deckWidths(wrap).narrow < 940;
/** «Это тема — агент напишет полный текст» с перечнем («: ключевые факты, даты…») — пока колода шире 1300. */
export const hintTail = (wrap: number): boolean => deckWidths(wrap).wide > 1300;

// ── Лента шага 01: ряды по четыре (V2 `tpRows`)
/** Дорожка ряда: живая или сжатая до нуля. */
const FR = "minmax(0, 1fr)";
const FR0 = "minmax(0, 0fr)";

export interface RibbonSlot<T> {
  /** Обложка шаблона, «Все шаблоны» или «Загрузить свой». */
  kind: "cover" | "all" | "upload";
  item?: T;
  /** Обложка уходит в узкой раскладке: её дорожка сжимается до нуля, она гаснет на месте. */
  cut: boolean;
}

export interface RibbonRow<T> { slots: RibbonSlot<T>[]; /** Дорожки ряда в узкой раскладке. */ narrow: string }

/** Ряды ленты: обложки, затем «Все шаблоны» (если есть скрытые) и «Загрузить свой», по четыре. Помощник сужает колоду:
 *  в ряду из четырёх одна обложка уходит — её дорожка сжимается до нуля (последняя обложка ряда, если она не выбранная,
 *  иначе предыдущая); пустые дорожки сверх трёх тоже сжимаются. Остальные плитки ряда сужаются вместе с плитой —
 *  четыре обложки в три колонки без перескоков между рядами. `gone` — сколько обложек уходит.
 *  Сайт: без «Все шаблоны» (скрытых шаблонов нет, `more` — нет) обложки не уходят — до ушедшей при открытом помощнике было
 *  бы не добраться; ряды остаются по четыре дорожки и в узкой раскладке (колонки рядов совпадают). */
export function ribbonRows<T>(covers: T[], selected: (t: T) => boolean, more: boolean): { rows: RibbonRow<T>[]; gone: number } {
  const slots: RibbonSlot<T>[] = covers.map((item) => ({ kind: "cover", item, cut: false }));
  if (more) slots.push({ kind: "all", cut: false });
  slots.push({ kind: "upload", cut: false });
  const rows: RibbonRow<T>[] = [];
  let gone = 0;
  for (let i = 0; i < slots.length; i += 4) {
    const row = slots.slice(i, i + 4);
    const tr = [FR, FR, FR, FR];
    if (!more) {
      rows.push({ slots: row, narrow: tr.join(" ") });
      continue;
    }
    if (row.length === 4) {
      const cov = row.map((s, k) => (s.kind === "cover" ? k : -1)).filter((k) => k >= 0);
      let k: number | undefined = cov[cov.length - 1];
      if (k !== undefined && selected(row[k].item as T)) k = cov[cov.length - 2];
      if (k !== undefined) {
        row[k] = { ...row[k], cut: true };
        tr[k] = FR0;
        gone++;
      }
    }
    for (let k = 3, open = tr.filter((v) => v === FR).length; k >= row.length && open > 3; k--, open--) tr[k] = FR0;
    rows.push({ slots: row, narrow: tr.join(" ") });
  }
  return { rows, gone };
}
