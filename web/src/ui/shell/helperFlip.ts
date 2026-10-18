// Помощник на «Результате» — без хода раскладки по кадрам (замечание владельца 18.10: «супер плавно, как на холсте»).
// Раскладка колоды и рабочей области меняется один раз — в том же кадре, что класс обёртки (`hp-flip`, shell.css и
// helper.css: переходы сеток выключены); край колоды едет фоном и тенью плит (clip-path, shell.css), а всё, что
// стоит в обеих раскладках, — transform'ом от прежнего места к новому (FLIP): прежнее место меряется возвратом класса
// обёртки на тот же кадр, до первой отрисовки. Полный и компактный вид сменяются своей прозрачностью (helper.css).
import { useLayoutEffect, useRef, type RefObject } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { layoutRect, type LayoutRect } from "./stage";

/** Открытие — 520 мс, закрытие — 2/3 (340), как ход колоды на холсте. */
export const FLIP_OPEN_MS = 520;
export const FLIP_CLOSE_MS = 340;
const EASE = "cubic-bezier(0.2, 0, 0, 1)";

/** Что переезжает. Подпись и кнопки шапки «Слайд N из M», слайд (с масштабом), лента миниатюр — в обе стороны. Видимое только в одной раскладке едет, пока гаснет: открытие — колонки полного вида; закрытие — шапка и
 *  колонки компактного. Название презентации перекладывается из одного вида в другой: при открытии название компактного
 *  вида выходит из места большого (и его кегля), при закрытии — большое из места компактного (`from`, `font`). Ни один
 *  элемент не вложен в другой, что едет в ту же сторону, — сдвиги не складываются. */
export interface FlipTarget {
  sel: string; scale?: boolean;
  /** Прежнее место — не своё, а этого элемента (название из большого в компактное). */
  from?: string;
  /** Ход не на своё новое место, а на новое место этого элемента (гаснущее название — к большому). */
  to?: string;
  /** Масштаб — отношение кеглей. */
  font?: boolean;
  when?: "open" | "close";
}
export const FLIP_TARGETS: FlipTarget[] = [
  { sel: ".ra-whx > div > p" },
  { sel: ".ra-whx .ra-whr" },
  { sel: ".ra-stage", scale: true },
  { sel: ".p2-film" },
  { sel: ".ra-two > aside", when: "open" },
  { sel: ".hp-top h1", from: ".ra-two > aside .ra-h1", font: true, when: "open" },
  { sel: ".hp-top h1", to: ".ra-two > aside .ra-h1", font: true, when: "close" },
  { sel: ".hp-top .gh-top > div:first-child > div", when: "close" },
  { sel: ".hp-acts", when: "close" },
  { sel: ".hp-ncol", when: "close" },
  { sel: ".hp-pcol", when: "close" },
];

/** transform, который ставит элемент из нового места `last` на прежнее `first` (сдвиг левого верхнего угла и, для
 *  слайда, масштаб по ширине); null — не сдвинулся (меньше 0,5 px и масштаб тот же). */
export function flipFrom(first: LayoutRect, last: LayoutRect, scale: boolean | number = false): string | null {
  const dx = first.left - last.left;
  const dy = first.top - last.top;
  const s = typeof scale === "number" ? scale : scale && last.width > 0 ? first.width / last.width : 1;
  if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(s - 1) < 0.002) return null;
  const r = (v: number) => Math.round(v * 100) / 100;
  return s !== 1 ? `translate(${r(dx)}px, ${r(dy)}px) scale(${Math.round(s * 10000) / 10000})` : `translate(${r(dx)}px, ${r(dy)}px)`;
}

/** Идущие ходы: новый снимает прежний у того же элемента. */
const running = new WeakMap<HTMLElement, Animation>();

/** Ход FLIP для обёртки `ref` при смене `open` (помощник открыт), только когда `active` (экран «Результат»). */
export function useHelperFlip(ref: RefObject<HTMLElement>, open: boolean, active: boolean): void {
  const was = useRef({ open, cls: "" });
  useLayoutEffect(() => {
    const wrap = ref.current;
    const prev = was.current;
    const cls = wrap?.className ?? "";
    was.current = { open, cls };
    if (!wrap || prev.open === open || !active || !prev.cls || prefersReducedMotion()) return;
    const dir = open ? "open" : "close";
    const one = (sel: string) => Array.from(wrap.querySelectorAll<HTMLElement>(sel)).find((el) => el.getClientRects().length > 0) ?? null;
    const els = FLIP_TARGETS.filter((t) => !t.when || t.when === dir).flatMap((t) =>
      Array.from(wrap.querySelectorAll<HTMLElement>(t.sel)).filter((el) => el.getClientRects().length > 0).map((el) => ({ el, t, src: t.from ? one(t.from) : el })))
      .filter((x): x is { el: HTMLElement; t: FlipTarget; src: HTMLElement } => !!x.src);
    // прерванный прежний ход снимается, иначе его transform попал бы в замер
    for (const { el } of els) running.get(el)?.cancel();
    const last = els.map(({ el }) => layoutRect(el));
    const font = (el: HTMLElement) => parseFloat(getComputedStyle(el).fontSize) || 1;
    const lastFont = els.map(({ el, t }) => (t.font ? font(el) : 1));
    // для хода «к чужому месту» (`to`) нужен кегль элемента и в новой раскладке — он тот же
    wrap.className = prev.cls; // прежняя раскладка на этот же кадр — только замер
    const first = els.map(({ src }) => layoutRect(src));
    const firstFont = els.map(({ src, t }) => (t.font ? font(src) : 1));
    wrap.className = cls;
    const ms = open ? FLIP_OPEN_MS : FLIP_CLOSE_MS;
    // ход — анимацией элемента (Web Animations), а не его переходами: прозрачность и прочие переходы CSS остаются свои
    els.forEach(({ el, t: target }, i) => {
      const toEl = target.to ? one(target.to) : null;
      const t = flipFrom(first[i], last[i], target.font && !target.to ? firstFont[i] / lastFont[i] : !!target.scale) ?? "none";
      const end = toEl ? flipFrom(layoutRect(toEl), last[i], font(toEl) / lastFont[i]) ?? "none" : "none";
      if (t === "none" && end === "none") return;
      const a = el.animate([{ transform: t, transformOrigin: "0 0" }, { transform: end, transformOrigin: "0 0" }], { duration: ms, easing: EASE });
      running.set(el, a);
      a.onfinish = a.oncancel = () => {
        if (running.get(el) === a) running.delete(el);
      };
    });
  }, [ref, open, active]);
}
