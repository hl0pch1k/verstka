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
// Когда: после монтирования — когда слой доехал (не в кадрах его въезда); новый текст, клетка сменила ширину в покое
// (ResizeObserver), окно перестало меняться, догрузились шрифты, сменилось своё --hpd — заново по клетке в ближайшем кадре.
// Только в покое: от смены раскладки колоды (помощник) до конца её хода (MOVE_MS) ни замер, ни снятие замера не идут —
// они меняли бы геометрию посреди хода; отложенное — в первом кадре после хода, тогда же сверка всех клеток.
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
/** Ширина клетки в покое в широкой и узкой раскладке (замер в одной, вторая — на --hpd у́же или шире). */
const rest = new WeakMap<HTMLElement, { wide: number; narrow: number }>();
let frame = 0;
let later = 0;
let resized = 0;
let ro: ResizeObserver | null = null;
/** Раскладка колоды сейчас (узкая — помощник открыт): с ней сверяется ширина клетки в покое. */
let narrowNow = false;
/** Первый замер после монтирования — не раньше, чем слой доехал (его въезд 520 мс и лесенка). */
export const MEASURE_LATER = 700;
/** Окно перестало меняться — замер заново. */
const RESIZE_SETTLE = 150;
/** Ход колоды при смене раскладки (520 мс, create.css / layers.css) и запас. */
export const MOVE_MS = 560;
/** Колода идёт к новой раскладке — замеров нет (снимает таймер хода: те же часы, что у переходов страницы). */
let movingNow = false;
let moveEnd = 0;
/** Стопки, чей замер снят посреди хода, — снять в первом кадре после него. */
const pending = new Set<HTMLElement>();
/** Клетки, сменившие ширину на ходу (наблюдатель на ходу молчит), — сверить после него. */
const missed = new Set<HTMLElement>();

function moving(): boolean {
  return movingNow;
}

/** Раскладка колоды сменилась: замеры — после хода. */
function startMove() {
  movingNow = true;
  window.clearTimeout(moveEnd);
  moveEnd = window.setTimeout(() => {
    moveEnd = 0;
    movingNow = false;
    requestAnimationFrame(afterMove);
  }, MOVE_MS);
}

/** Ход кончился: отложенные снятия замера, сверка клеток, сменивших ширину на ходу, отложенный замер. */
function afterMove() {
  if (moving()) return;
  pending.forEach((el) => {
    if (!el.isConnected) return;
    el.classList.remove("hp-txm");
    dirty.add(el);
  });
  pending.clear();
  missed.forEach((el) => el.isConnected && checkCell(el, el.getBoundingClientRect().width));
  missed.clear();
  if (dirty.size && !frame) frame = requestAnimationFrame(flush);
}

/** Высоты стопки по копиям: широкая — во весь рост и в узкой раскладке (там она только невидима), узкая — её содержимое
 *  (и тогда, когда её высота 0); `margin` — вертикальные поля копий (клетка = копия + поля). Стопка: `hw` в широкой,
 *  на `hdd` выше в узкой (не ниже широкой — та остаётся во весь рост); узкая копия — от 0 до `hn`. */
export function stackHeights(wide: number, narrow: number, margin = 0): { hw: number; hdd: number; hn: number } {
  return { hw: wide + margin, hdd: Math.max(0, narrow - wide), hn: narrow };
}

function flush() {
  frame = 0;
  later = 0;
  if (moving()) return; // после хода — afterMove
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
    const cell = el.getBoundingClientRect().width;
    const hpd = parseFloat(getComputedStyle(el).getPropertyValue("--hpd")) || 0;
    const cells = narrowNow ? { wide: cell + hpd, narrow: cell } : { wide: cell, narrow: cell - hpd };
    return { ...h, tw: w.getBoundingClientRect().width, tn: n.getBoundingClientRect().width, cells };
  });
  // обратно — тоже без переходов (иначе узкая копия ехала бы к своей высоте 0 ↔ auto 340 мс): сначала только «без
  // переходов», стиль досчитан, потом и эта метка снята — значения уже прежние, ход не начинается
  items.forEach((el) => el.classList.replace("hp-txq", "hp-txz"));
  if (items.length) void getComputedStyle(items[0].children[1] ?? items[0]).height;
  items.forEach((el) => el.classList.remove("hp-txz"));
  // потом записи — только изменившиеся; метка замера ставится без переходов (`hp-txz`): ход стопки --hpp в узкой
  // раскладке иначе начался бы с нуля — высота стопки поехала бы в покое от широкой к узкой
  const fresh: HTMLElement[] = [];
  items.forEach((el, i) => {
    const h = read[i];
    if (!h) return;
    rest.set(el, h.cells);
    const key = `${h.hw}|${h.hdd}|${h.hn}|${h.tw}|${h.tn}`;
    if (last.get(el) === key && el.classList.contains("hp-txm")) return;
    last.set(el, key);
    if (!el.classList.contains("hp-txm")) {
      el.classList.add("hp-txz");
      fresh.push(el);
    }
    el.style.setProperty("--hw", `${h.hw}px`);
    el.style.setProperty("--hdd", `${h.hdd}px`);
    el.style.setProperty("--hn", `${h.hn}px`);
    el.style.setProperty("--tw", `${h.tw}px`);
    el.style.setProperty("--tn", `${h.tn}px`);
    // высота стопки в узкой раскладке — и соседям (ряд плана: до неё сжимается тело ряда)
    if (el.dataset.share) el.parentElement?.style.setProperty(`--${el.dataset.share}`, `${h.hw + h.hdd}px`);
    el.classList.add("hp-txm");
  });
  if (!fresh.length) return;
  void getComputedStyle(fresh[0]).getPropertyValue("--hpp");
  fresh.forEach((el) => el.classList.remove("hp-txz"));
}

/** Клетка стопки сменила ширину в покое (бейдж рядом, подпись кнопки, полоса прокрутки) — замер заново; доли пикселя
 *  (дрожь раскладки) — не повод. */
function checkCell(el: HTMLElement, width: number) {
  const r = rest.get(el);
  if (!r || !el.isConnected) return;
  if (Math.abs(width - (narrowNow ? r.narrow : r.wide)) >= 0.5) remeasure(el);
}

function onCells(entries: ResizeObserverEntry[]) {
  // на ходу колоды клетки меняют ширину сами — не повод; после хода их сверяет afterMove
  if (moving()) return void entries.forEach((e) => missed.add(e.target as HTMLElement));
  for (const e of entries) checkCell(e.target as HTMLElement, e.contentRect.width);
}

/** Замер в ближайшем кадре. */
function mark(el: HTMLElement) {
  dirty.add(el);
  if (later) {
    window.clearTimeout(later);
    later = 0;
  }
  if (!frame && typeof requestAnimationFrame === "function") frame = requestAnimationFrame(flush);
}

/** Ширины копий снова по клетке (окно, шрифты, своё --hpd) — и замер в ближайшем кадре; на ходу — после него. */
function remeasure(el: HTMLElement) {
  if (moving()) return void pending.add(el);
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
  if (typeof ResizeObserver !== "undefined") {
    ro ??= new ResizeObserver(onCells);
    ro.observe(el);
  }
  return () => {
    all.delete(el);
    dirty.delete(el);
    pending.delete(el);
    missed.delete(el);
    ro?.unobserve(el);
    if (all.size === 0) window.removeEventListener("resize", onResize);
  };
}

export function Tx({ tx, as = "p", wrap = "div", className, style, f, hpd, title, share, children }: {
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
  /** Высоту стопки в узкой раскладке — родителю, CSS-переменной с этим именем. */
  share?: string;
  children: ReactNode;
}) {
  const narrow = useContext(TxNarrow);
  narrowNow = narrow;
  const ref = useRef<HTMLElement>(null);
  // раскладка колоды сменилась (помощник) — колода пошла к новой: замеры после хода (первым из эффектов — до замеров ниже)
  const seenNarrow = useRef(narrow);
  useLayoutEffect(() => {
    if (seenNarrow.current === narrow) return;
    seenNarrow.current = narrow;
    startMove();
  }, [narrow]);
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
    remeasure(el);
  });
  const W = wrap;
  const T = as;
  return (
    <W ref={ref as never} className={cls("hp-tx hp-txl", f && "hp-txf")} data-tx={tx} data-share={share} style={hpd === undefined ? undefined : ({ "--hpd": `${hpd}px` } as CSSProperties)}>
      <T className={cls("hp-txw", className)} style={style} title={narrow ? undefined : title} aria-hidden={narrow || undefined}>{children}</T>
      <T className={cls("hp-txn", className)} style={style} title={narrow ? title : undefined} aria-hidden={!narrow || undefined}>{children}</T>
    </W>
  );
}
