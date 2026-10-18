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
/** Место помощника: плита 400 + зазор 16 — на столько слои плит продлены вправо в узкой раскладке (shell.css). */
const HELPER_CUT = 416;

/** Что переезжает — то, что на холсте (V2, «Play: весь путь») едет вместе с сеткой колоды и результата: подпись и
 *  кнопки строки «Слайд N из M», таблетка уведомления, слайд (с масштабом), лента миниатюр, колонка полного вида,
 *  действия и узкая колонка компактного, тень края колоды. Видимое только в одной раскладке едет, пока гаснет или
 *  проявляется (как на холсте: перекрёстное затухание идёт поверх хода сетки). Ни один элемент не вложен в другой —
 *  сдвиги не складываются. */
export interface FlipTarget { sel: string; scale?: boolean }
export const FLIP_TARGETS: FlipTarget[] = [
  { sel: ".ra-whx > div > p" },
  { sel: ".ra-whx .ra-whr" },
  { sel: ".ra-whx .ra-note-h" },
  { sel: ".ra-stage", scale: true },
  { sel: ".p2-film" },
  { sel: ".ra-two > aside" },
  { sel: ".hp-acts" },
  { sel: ".hp-ncol" },
  { sel: ".hp-pcol" },
  { sel: ".hp-shade" },
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
function track(el: HTMLElement, a: Animation) {
  running.set(el, a);
  a.onfinish = a.oncancel = () => {
    if (running.get(el) === a) running.delete(el);
  };
}

/** Ход FLIP для обёртки `ref` при смене `open` (помощник открыт), только когда `active` (экран «Результат»). */
export function useHelperFlip(ref: RefObject<HTMLElement>, open: boolean, active: boolean): void {
  const was = useRef({ open, cls: "" });
  useLayoutEffect(() => {
    const wrap = ref.current;
    const prev = was.current;
    const cls = wrap?.className ?? "";
    was.current = { open, cls };
    if (!wrap || prev.open === open || !active || !prev.cls || prefersReducedMotion()) return;
    const els = FLIP_TARGETS.flatMap((t) => Array.from(wrap.querySelectorAll<HTMLElement>(t.sel)).map((el) => ({ el, t })))
      .filter(({ el }) => el.getClientRects().length > 0);
    // фон и тень плит (их ::before / ::after) — край колоды: подрезка от прежней к новой
    const plates = Array.from(wrap.querySelectorAll<HTMLElement>(".p2-pbg"));
    // прерванный прежний ход снимается, иначе его transform попал бы в замер
    for (const { el } of els) running.get(el)?.cancel();
    for (const el of plates) running.get(el)?.cancel();
    const last = els.map(({ el }) => layoutRect(el));
    wrap.className = prev.cls; // прежняя раскладка на этот же кадр — только замер
    const first = els.map(({ el }) => layoutRect(el));
    wrap.className = cls;
    const ms = open ? FLIP_OPEN_MS : FLIP_CLOSE_MS;
    const opts = { duration: ms, easing: EASE };
    // все ходы — Web Animations, созданные в одном кадре: у них одно время начала, край колоды (подрезка фона) и всё,
    // что едет вместе с ним, идут кадр в кадр (в Safari переходы CSS и анимации JS начинались в разных кадрах)
    els.forEach(({ el, t: target }, i) => {
      const t = flipFrom(first[i], last[i], !!target.scale);
      if (!t) return;
      const a = el.animate([{ transform: t, transformOrigin: "0 0" }, { transform: "none", transformOrigin: "0 0" }], opts);
      track(el, a);
    });
    const bg = (cut: number) => `inset(0px ${cut}px 0px 0px round 40px)`;
    const sh = (cut: number) => `inset(-64px ${cut}px -64px -64px)`;
    const [c0, c1] = open ? [0, HELPER_CUT] : [HELPER_CUT, 0];
    for (const el of plates) {
      track(el, el.animate({ clipPath: [bg(c0), bg(c1)] }, { ...opts, pseudoElement: "::before" }));
      el.animate({ clipPath: [sh(c0), sh(c1)] }, { ...opts, pseudoElement: "::after" });
    }
  }, [ref, open, active]);
}
