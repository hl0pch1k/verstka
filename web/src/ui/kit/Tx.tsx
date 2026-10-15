// Стопка из двух копий многострочного текста (hp-tx, create.css; V2 версии 100, «Многострочный текст не переносится
// заново посреди хода»): широкая копия (hp-txw) и узкая (hp-txn) в одной клетке, каждая постоянной ширины на всём ходу
// помощника (`--hpd` — на сколько клетка у́же в узкой раскладке, по `data-tx` в CSS или своим `hpd`). Активная копия —
// по раскладке колоды (TxNarrow: помощник открыт и окно шире 900 px), вторая — aria-hidden.
// Сайт (слои и лист «Подробнее», `hp-txl`, layers.css): высота стопки на ходу идёт линейно — от высоты широкой копии
// (`--hw`) до высоты в узкой раскладке (`--hw + --hdd`), узкая копия растёт линейно от нуля (`--hn`): так стопки и то,
// что на ходу сжимается рядом (миниатюры с пропорцией), складываются в один ход — то, что ниже, не идёт вверх, а потом
// вниз. Замер здесь, одним проходом для всех стопок (сначала все чтения, потом записи, и только изменившиеся): высоты
// копий и их ширины в покое — после замера (`hp-txm`) ширина каждой копии — эти px (`--tw`, `--tn`), а не клетка ± --hpd·p:
// та постоянна только до 1/64 px, и строка, вставшая впритык, могла бы перенестись посреди хода. До замера — ход V2.
// Когда: после монтирования — когда слой доехал (не в кадрах его въезда); новый текст — в ближайшем кадре; окно
// перестало меняться, догрузились шрифты, сменилось своё --hpd — заново по клетке.
// Для листа «Подробнее» и слоёв; «Создать» и «Сборка» держат свои стопки (create/, build/Roles).
import { createContext, useContext, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { cls } from "./cls";

/** Колода сужена помощником — активна узкая копия. Ставит тот, кто держит стопки (лист, слой): одно значение на всех. */
export const TxNarrow = createContext(false);

type Tag = "p" | "span" | "div" | "dd" | "h2" | "h3";

// ── замер копий: один проход для всех стопок
const all = new Set<HTMLElement>();
const dirty = new Set<HTMLElement>();
const last = new WeakMap<HTMLElement, string>();
const texts = new WeakMap<HTMLElement, string>();
let frame = 0;
let later = 0;
let resized = 0;
/** Первый замер после монтирования — не раньше, чем слой доехал (его въезд 520 мс и лесенка). */
export const MEASURE_LATER = 700;
/** Окно перестало меняться — замер заново. */
const RESIZE_SETTLE = 150;

/** Высоты стопки по копиям: широкая — во весь рост и в узкой раскладке (там она только невидима), узкая — её содержимое
 *  (и тогда, когда её высота 0); `margin` — вертикальные поля копий (клетка = копия + поля). Стопка: `hw` в широкой,
 *  на `hdd` выше в узкой (не ниже широкой — та остаётся во весь рост); узкая копия — от 0 до `hn`. */
export function stackHeights(wide: number, narrow: number, margin = 0): { hw: number; hdd: number; hn: number } {
  return { hw: wide + margin, hdd: Math.max(0, narrow - wide), hn: narrow };
}

function flush() {
  frame = 0;
  later = 0;
  const items = [...dirty].filter((el) => el.isConnected);
  dirty.clear();
  // сначала все чтения: ширины копий (в покое каждая — своя постоянная ширина: клетка ± --hpd) и высоты; узкая копия на
  // время замера — во весь свой рост (`hp-txq`: в широкой раскладке её высота 0, а scrollHeight не знает обрезки по
  // числу строк — line-clamp), одна раскладка на все стопки
  items.forEach((el) => el.classList.add("hp-txq"));
  const read = items.map((el) => {
    const [w, n] = el.children as unknown as HTMLElement[];
    if (!w || !n) return null;
    const cs = getComputedStyle(w);
    const h = stackHeights(w.offsetHeight, n.offsetHeight, (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0));
    return { ...h, tw: w.getBoundingClientRect().width, tn: n.getBoundingClientRect().width };
  });
  // обратно — тоже без переходов (иначе узкая копия ехала бы к своей высоте 0 ↔ auto 340 мс): сначала только «без
  // переходов», стиль досчитан, потом и эта метка снята — значения уже прежние, ход не начинается
  items.forEach((el) => el.classList.replace("hp-txq", "hp-txz"));
  if (items.length) void getComputedStyle(items[0].children[1] ?? items[0]).height;
  items.forEach((el) => el.classList.remove("hp-txz"));
  // потом записи — только изменившиеся
  items.forEach((el, i) => {
    const h = read[i];
    if (!h) return;
    const key = `${h.hw}|${h.hdd}|${h.hn}|${h.tw}|${h.tn}`;
    if (last.get(el) === key && el.classList.contains("hp-txm")) return;
    last.set(el, key);
    el.style.setProperty("--hw", `${h.hw}px`);
    el.style.setProperty("--hdd", `${h.hdd}px`);
    el.style.setProperty("--hn", `${h.hn}px`);
    el.style.setProperty("--tw", `${h.tw}px`);
    el.style.setProperty("--tn", `${h.tn}px`);
    el.classList.add("hp-txm");
  });
}

/** Замер в ближайшем кадре (новый текст: ширины копий те же, высоты — новые). */
function mark(el: HTMLElement) {
  dirty.add(el);
  if (later) {
    window.clearTimeout(later);
    later = 0;
  }
  if (!frame && typeof requestAnimationFrame === "function") frame = requestAnimationFrame(flush);
}

/** Ширины копий снова по клетке (окно, шрифты, своё --hpd) — и замер в ближайшем кадре. */
function remeasure(el: HTMLElement) {
  el.classList.remove("hp-txm");
  mark(el);
}

/** Замер, когда слой доехал (новые стопки смонтированы при открытии слоя или вкладки). */
function markLater(el: HTMLElement) {
  dirty.add(el);
  if (!frame && !later) later = window.setTimeout(flush, MEASURE_LATER);
}

function onResize() {
  window.clearTimeout(resized);
  resized = window.setTimeout(() => all.forEach(remeasure), RESIZE_SETTLE);
}

function track(el: HTMLElement): () => void {
  texts.set(el, el.firstElementChild?.textContent ?? "");
  if (all.size === 0) window.addEventListener("resize", onResize);
  all.add(el);
  markLater(el);
  void document.fonts?.ready.then(() => (last.has(el) ? remeasure(el) : markLater(el)));
  return () => {
    all.delete(el);
    dirty.delete(el);
    if (all.size === 0) window.removeEventListener("resize", onResize);
  };
}

export function Tx({ tx, as = "p", wrap = "div", className, style, f, hpd, title, children }: {
  /** Имя стопки — по нему CSS ставит `--hpd` (details.css, layers.css). */
  tx: string;
  /** Тег копий. */
  as?: Tag;
  /** Тег клетки: `span` — внутри строчного места (кнопки, подписи). */
  wrap?: "div" | "span";
  className?: string;
  style?: CSSProperties;
  /** Клетка тянется во flex-ряду (hp-txf). */
  f?: boolean;
  /** `--hpd` своим числом (px), когда оно зависит от ширины окна или от соседей (сводка «Качества», паспорт «Файлов»). */
  hpd?: number;
  /** Подсказка — у активной копии. */
  title?: string;
  children: ReactNode;
}) {
  const narrow = useContext(TxNarrow);
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    return el ? track(el) : undefined;
  }, []);
  // своё --hpd сменилось (замер кнопок сводки, ширина окна) — ширины копий снова по клетке
  const seenHpd = useRef(hpd);
  useLayoutEffect(() => {
    if (seenHpd.current === hpd) return;
    seenHpd.current = hpd;
    if (ref.current) remeasure(ref.current);
  }, [hpd]);
  // перерисовка с новым текстом — замер в ближайшем кадре (неизменившиеся высоты ничего не пишут)
  useLayoutEffect(() => {
    const el = ref.current;
    const t = el?.firstElementChild?.textContent ?? "";
    if (!el || texts.get(el) === t) return;
    texts.set(el, t);
    mark(el);
  });
  const W = wrap;
  const T = as;
  return (
    <W ref={ref as never} className={cls("hp-tx hp-txl", f && "hp-txf")} data-tx={tx} style={hpd === undefined ? undefined : ({ "--hpd": `${hpd}px` } as CSSProperties)}>
      <T className={cls("hp-txw", className)} style={style} title={narrow ? undefined : title} aria-hidden={narrow || undefined}>{children}</T>
      <T className={cls("hp-txn", className)} style={style} title={narrow ? title : undefined} aria-hidden={!narrow || undefined}>{children}</T>
    </W>
  );
}
