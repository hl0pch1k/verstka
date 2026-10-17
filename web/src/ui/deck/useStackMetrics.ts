// Замеры колоды стопкой (ui/deck/stack.ts): низы шапок и тел шагов «Создать», сборки и результата — по раскладке
// (offsetTop / offsetHeight, без transform: проявление p2-in и сдвиги на ходу их не меняют), от верха своей плиты.
// Меряется в том же кадре после каждой отрисовки колоды и когда меняется размер содержимого (ResizeObserver; что
// наблюдать — пересобирается, когда в колоде появляются и уходят элементы) или окна. На компьютере не меряется.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { LAYER_MS } from "../layers/Layer";
import { deckMin, improveExtra, PHONE_MIN, sameMetrics, STACK_MIN, type StackMetrics } from "./stack";

/** Низ элемента от верха плиты `plate` по раскладке; элемент не внутри плиты (или скрыт) — null. */
function layoutBottom(e: Element | null | undefined, plate: HTMLElement): number | null {
  if (!(e instanceof HTMLElement) || !e.offsetParent) return null;
  let y = e.offsetHeight;
  let n: HTMLElement | null = e;
  while (n && n !== plate) {
    y += n.offsetTop;
    n = n.offsetParent as HTMLElement | null;
  }
  return n === plate ? Math.round(y) : null;
}

/** Нижний край содержимого: наибольший низ из элементов (пустой список — 0). */
const lowest = (els: (Element | null | undefined)[], plate: HTMLElement): number =>
  Math.max(0, ...els.map((e) => layoutBottom(e, plate) ?? 0));

/** Дети элемента в потоке (не absolute и не fixed) — то, что задаёт высоту содержимого плиты. */
function inFlow(el: Element | null | undefined): Element[] {
  if (!el) return [];
  return Array.from(el.children).filter((c) => {
    const p = getComputedStyle(c).position;
    return p !== "absolute" && p !== "fixed";
  });
}

function read(deck: HTMLElement, watch: (e: Element | null | undefined) => void, phone: boolean): StackMetrics | null {
  const plates = Array.from(deck.querySelectorAll<HTMLElement>(":scope > .p2-slot:not(.p2-lay) > .p2-plate"));
  if (plates.length < 4) return null;
  const [p1, p2, p3, p4] = plates;
  const pad = parseFloat(getComputedStyle(p1).paddingTop) || 0;
  const strip = parseFloat(getComputedStyle(deck).getPropertyValue("--ps")) || 48;
  const fx = (p: HTMLElement) => p.querySelector<HTMLElement>(":scope > .p2-fxbox");
  const step = (p: HTMLElement) => {
    const box = fx(p);
    const row = box?.querySelector(":scope > .p2-hrow");
    const kids = box ? Array.from(box.children) : [];
    for (const k of kids) watch(k);
    // открытое меню шага («Из файла», «Брендбук») лежит поверх тела; ниже тела — следующая плита отъезжает, чтобы его
    // не накрыть (на телефоне меню в одну колонку выше поля)
    const menus = box ? Array.from(box.querySelectorAll(".tx-menu.tx-menu-on")) : [];
    return { head: lowest([row, ...menus], p), body: lowest([...kids, ...menus], p) };
  };
  const s1 = step(p1);
  const s2 = step(p2);
  // «Улучшить готовую»: поле уходит под заметку и растёт вниз transform'ом (create.css) — к низу шага прибавляются сдвиг и
  // рост (их ставит TextBody по высоте заметки)
  const imp = p2.querySelector<HTMLElement>(".tx-fw-imp");
  if (imp) {
    const vars = getComputedStyle(imp);
    s2.body += improveExtra(vars.getPropertyValue("--tx-sh"), vars.getPropertyValue("--tx-gr"));
  }
  const box3 = fx(p3);
  const short = p3.querySelector("#p2-b3");
  const all = p3.querySelector("#p2-b3m");
  const build = p3.querySelector(":scope > .bd-two");
  const res = inFlow(p4);
  for (const e of [box3, short, all, build, ...res]) watch(e);
  // плита 03 на «Создать»: шапка, сводка, кнопка, строка ошибки, «Все параметры» и короткий ряд (в стопке шапка и тело
  // шага — одна сетка, create.css), без самого меню «Все параметры»
  const head3 = box3 ? Array.from(box3.querySelectorAll(".p2-head, .p2-hx, #pp-err, .p2-more")) : [];
  for (const e of head3) watch(e);
  const deckTop = deck.getBoundingClientRect().top + window.scrollY;
  const gut = parseFloat(getComputedStyle(deck.closest(".p2-root") ?? deck).paddingBottom) || 0;
  // телефон: плита 03 «Создать» видна на свою сводку, «Параметры» и кнопку с полем снизу (ParamsPlate `PhoneParams`):
  // низ кнопки — последней в столбце (сам столбец во всю видимую часть плиты, по нему мерить нельзя: он её и задаёт)
  const cta = phone ? p3.querySelector<HTMLElement>(".pp-ph > :last-child") : null;
  if (cta) watch(cta.parentElement);
  const q3 = cta && box3 ? (layoutBottom(cta, p3) ?? 0) + Math.round(parseFloat(getComputedStyle(box3).paddingBottom) || 0) : 0;
  return {
    pad, strip,
    h1: s1.head, b1: s1.body, h2: s2.head, b2: s2.body,
    c3: Math.max(lowest([short], p3), lowest(head3, p3)), m3: lowest([all], p3),
    k3: lowest([build], p3),
    r4: lowest(res, p4),
    min: deckMin(window.innerHeight, deckTop, gut, phone ? PHONE_MIN : STACK_MIN),
    q3,
  };
}

/** Замеры колоды `deck` стопкой; `on` — колода стопкой (иначе null и ничего не меряется), `phone` — телефон (колода во
 *  весь экран, плита 03 «Создать» прижата к низу). */
export function useStackMetrics(deck: RefObject<HTMLElement>, on: boolean, phone = false): StackMetrics | null {
  const [m, setM] = useState<StackMetrics | null>(null);
  const measure = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    const el = deck.current;
    if (!on || !el) {
      measure.current = () => {};
      setM(null);
      return;
    }
    let raf = 0;
    const seen = new Set<Element>();
    const ro = new ResizeObserver(() => schedule());
    const watch = (e: Element | null | undefined) => {
      if (e && !seen.has(e)) {
        seen.add(e);
        ro.observe(e);
      }
    };
    const run = () => {
      const next = read(el, watch, phone);
      setM((prev) => (sameMetrics(prev, next) ? prev : next));
    };
    const schedule = () => {
      if (!raf) raf = window.requestAnimationFrame(() => {
        raf = 0;
        run();
      });
    };
    measure.current = run;
    const mo = new MutationObserver(schedule);
    // и появление элементов, и смена классов (открылось меню шага, сменилось состояние) — повод перемерить
    mo.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", schedule);
    run();
    return () => {
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("resize", schedule);
      window.cancelAnimationFrame(raf);
      measure.current = () => {};
    };
  }, [deck, on, phone]);
  // после каждой отрисовки колоды (другой экран, шаг, вариант) — замер в том же кадре, до отрисовки страницы
  useLayoutEffect(() => {
    measure.current();
  });
  return m;
}

/** Колода ниже становится, когда плиты доехали: ход плиты и кадр запаса. */
export const HOLD_MS = LAYER_MS + 40;

/** Высота колоды на ходу: растёт сразу, ниже становится через `ms` (плита, которая уезжает вниз, не обрезается краем). */
export function useHeldHeight(h: number, ms = HOLD_MS): number {
  const [held, setHeld] = useState(h);
  useEffect(() => {
    if (h >= held) {
      if (h !== held) setHeld(h);
      return;
    }
    const t = window.setTimeout(() => setHeld(h), ms);
    return () => window.clearTimeout(t);
  }, [h, held, ms]);
  return Math.max(h, held);
}
