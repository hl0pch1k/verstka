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
/** В узкой раскладке у варианта только название (самое длинное — 106 px) и поля 16 + 16; уже (окно около 1280) — варианты
 *  встают списком рядом со степпером. */
export const VARIANT_NAME = 138;
/** Колонке названия переключателя в «Все параметры» (узкая раскладка) нужно 96 px — самое длинное слово
 *  «Генерировать»; уже — переключатели встают строками (тесная раскладка). */
export const SWITCH_NAME = 96;
/** Миниатюра варианта в «Все параметры»: 156 (доска), 112 — когда короткий ряд без переключателей (`.pp-short`). */
export const THUMB = 156;
export const THUMB_SHORT = 112;
/** Степпер слайдов в первом ряду «Все параметры» в тесной раскладке — по содержимому (−, число, +, поля 12). */
export const SLIDES_TIGHT = 168;
/** Степпер короткого ряда: 216 в широкой раскладке, 200 в узкой (V2) — он остаётся на плите всегда (решение владельца:
 *  число слайдов видно и меняется прямо на плите). */
export const STEPPER = 216;
export const STEPPER_NARROW = 200;
/** Ряд плиты 03 — 88 px; строки списка вариантов: название с поля 12, галочка 20 у правого края (поле 2). */
const ROW_H = 88;
const LIST_GAP = 8;
const LIST_TEXT = 12;
const LIST_BOX = 2;

const px = (n: number) => `${Math.round(n * 1000) / 1000}px`;
const fr = "minmax(0, 1fr)";
const r3 = (n: number) => Math.round(n * 1000) / 1000;

/** Ширины колоды: закрыт помощник / открыт (0 — обёртка ещё не измерена: как на доске при 1440). */
export function deckWidths(wrap: number): { wide: number; narrow: number } {
  const w = wrap > 0 ? wrap : 1392;
  return { wide: w, narrow: w - HELPER_COL };
}

/** Варианты списком (окно около 1280, узкая колода): карточки ряда перестраиваются в строки-таблетки рядом со степпером.
 *  Ход без наложений: на открытии карточки сначала (240 мс) становятся строками «лесенкой» — высота 88 → 24 и сдвиг вниз,
 *  пока они ещё в ряду, — затем (360 мс через 120) съезжают в столбик и расширяются; на закрытии — наоборот (240, затем
 *  160 через 180). Ширины и места по горизонтали — поля в долях дорожки вариантов (идут за колодой сами), по вертикали — px.
 *  Название и галочка — одни и те же в обеих раскладках, едут transform'ом (галочка — у правого края: путь не пересекает
 *  название); гаснет только описание (в списке его нет). */
export interface VariantListGeo {
  /** Вариантов и колонок списка (1; 2 — когда вариантов больше трёх). */
  n: number;
  cols: number;
  /** Карточка в широкой раскладке (ряд, высота 88) и строка списка в узкой — в покое. */
  card: number;
  pill: number;
  pillH: number;
  /** Название — не шире этого в обеих раскладках (многоточие не меняется на ходу). */
  title: number;
}

/** Где карточка `i` списка в покое широкой и узкой раскладки: место, размер, место названия и галочки внутри. */
export function listCard(g: VariantListGeo, i: number) {
  const col = i % g.cols, row = Math.floor(i / g.cols);
  return {
    col, row,
    wide: { x: r3(i * (g.card + GAP)), y: 0, w: g.card, h: ROW_H, box: { x: r3(g.card - 16 - 20), y: 18 }, text: { x: 16, y: 16 } },
    narrow: {
      x: r3(col * (g.pill + LIST_GAP)), y: r3(row * (g.pillH + LIST_GAP)), w: g.pill, h: g.pillH,
      box: { x: r3(g.pill - LIST_BOX - 20), y: r3((g.pillH - 20) / 2) }, text: { x: LIST_TEXT, y: r3((g.pillH - 24) / 2) },
    },
  };
}

export interface ParamsRow {
  /** Дорожки `#p2-b3` в широкой и узкой раскладке (одинаковое число: степпер, n вариантов — или их список одной
   *  дорожкой, — переключатели). Межколонник — поле справа у каждой клетки (16), лишнее поле последней уходит за край
   *  (`margin-right:-16px`): дорожка с нулём сжимается вместе со своим полем. */
  wide: string;
  narrow: string;
  /** Переключатели в коротком ряду широкой раскладки (иначе их дорожка — 0 в обеих). */
  switches: boolean;
  /** Варианты в узкой раскладке — списком (карточкам с названием рядом со степпером нет места); null — карточками. */
  list: VariantListGeo | null;
  /** На сколько вариант у́же в узкой раскладке: строка описания держит ширину покоя, пока гаснет (`.pp-vdi`). */
  shrink: number;
}

/** Короткий ряд плиты 03 (`#p2-b3`) при `n` вариантах. Степпер остаётся в обеих раскладках (216 → 200). */
export function paramsRow(wrap: number, n: number): ParamsRow {
  const { wide, narrow } = deckWidths(wrap);
  const k = Math.max(1, n);
  const row = (deck: number) => deck - PLATE_PAD - BODY_LEFT + GAP; // клетки с полями 16
  const cell = (deck: number, stepper: number, sw: number) => (row(deck) - stepper - sw) / k - GAP; // вариант без поля
  const switches = cell(wide, STEPPER + GAP, 264 + GAP) >= VARIANT_FULL;
  const sw = switches ? 264 + GAP : 0;
  const st = STEPPER_NARROW + GAP;
  const cards = cell(narrow, st, 0) >= VARIANT_NAME;
  if (cards) {
    const vars = (s: number, w: number) => [px(s), ...Array.from({ length: k }, () => fr), px(w)].join(" ");
    return {
      wide: vars(STEPPER + GAP, sw), narrow: vars(st, 0), switches, list: null,
      shrink: Math.max(0, r3(cell(wide, STEPPER + GAP, sw) - cell(narrow, st, 0))),
    };
  }
  // список: варианты — одна дорожка (степпер · варианты · переключатели в обеих раскладках)
  const block = (deck: number, s: number, w: number) => row(deck) - s - w - GAP;
  const bw = block(wide, STEPPER + GAP, sw), bn = block(narrow, st, 0);
  const cols = k > 3 ? 2 : 1;
  const rows = Math.ceil(k / cols);
  const card = r3((bw - (k - 1) * GAP) / k);
  const pill = r3((bn - (cols - 1) * LIST_GAP) / cols);
  const pillH = r3((ROW_H - (rows - 1) * LIST_GAP) / rows);
  return {
    wide: [px(STEPPER + GAP), fr, px(sw)].join(" "), narrow: [px(st), fr, "0px"].join(" "), switches,
    list: { n: k, cols, card, pill, pillH, title: r3(Math.min(card - 16 - 8 - 20 - 16, pill - LIST_TEXT - 8 - 20 - LIST_BOX)) },
    shrink: 0,
  };
}

/** Коробка переключателя в «Все параметры» (три колонки, `#p2-b3m`: слева 240, справа 48) в широкой и узкой раскладке. */
export function moreThird(wrap: number): { wide: number; narrow: number } {
  const { wide, narrow } = deckWidths(wrap);
  const third = (w: number) => r3((w - MORE_PAD - 2 * GAP) / 3);
  return { wide: third(wide), narrow: third(narrow) };
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

/** Карточки вариантов «Все параметры» (`#p2-b3m`) в широкой и узкой раскладке: карточка и колонка её подсказки (в
 *  широкой — справа от миниатюры, в узкой — миниатюры нет; в тесной поля по бокам 16 → 12). */
export function moreCards(wrap: number, n: number, short: boolean): Record<"wide" | "narrow", { card: number; hint: number }> {
  const c = moreCardsRaw(wrap, n, short);
  return { wide: { card: r3(c.wide.card), hint: r3(c.wide.hint) }, narrow: { card: r3(c.narrow.card), hint: r3(c.narrow.hint) } };
}

function moreCardsRaw(wrap: number, n: number, short: boolean) {
  const { wide, narrow } = deckWidths(wrap);
  const k = Math.max(1, n);
  const card = (w: number) => (w - MORE_PAD - (k - 1) * GAP) / k;
  const thumb = short ? THUMB_SHORT : THUMB;
  return {
    wide: { card: card(wide), hint: card(wide) - 32 - thumb - GAP },
    narrow: { card: card(narrow), hint: card(narrow) - (moreTight(wrap) ? 24 : 32) },
  };
}

/** Тесная раскладка «Все параметры» (окно около 1280): в узкой колоде колонке названия переключателя меньше 96 px. */
const moreTight = (wrap: number): boolean => {
  const N = deckWidths(wrap).narrow - MORE_PAD;
  return (N - 2 * GAP) / 3 - 48 - 44 - GAP < SWITCH_NAME;
};

/** «Все параметры» (`#p2-b3m`) при `n` вариантах; `short` — короткий ряд без переключателей (миниатюры меньше). */
export function moreGrid(wrap: number, n: number, short: boolean): MoreGrid {
  const { wide, narrow } = deckWidths(wrap);
  const W = wide - MORE_PAD, N = narrow - MORE_PAD;
  const third = (w: number) => (w - 2 * GAP) / 3;
  const tight = moreTight(wrap);
  const r1Wide = [px(third(W)), px(third(W)), px(third(W))].join(" ");
  const rest = (N - 2 * GAP - SLIDES_TIGHT) / 2;
  const r1Narrow = tight ? [px(rest), px(rest), px(SLIDES_TIGHT)].join(" ") : [px(third(N)), px(third(N)), px(third(N))].join(" ");
  const c = moreCardsRaw(wrap, n, short);
  return { tight, r1Wide, r1Narrow, thumb: short ? THUMB_SHORT : THUMB, vhint: r3(c.wide.hint - c.narrow.hint) };
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
