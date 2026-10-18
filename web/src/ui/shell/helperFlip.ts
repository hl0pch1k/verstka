// Помощник на «Результате» — ход без перекладки раскладки посреди движения и без двух видимых раскладок сразу
// (замечание владельца 18.10, кадры настоящего Safari: колода обрезалась мгновенно, полный и компактный вид двоились).
//
// Открытие (520 мс, кривая холста):
//   0 мс    раскладка остаётся широкой; полный вид (колонка справа, таблетка уведомления) гаснет за 160 мс;
//           край колоды едет влево подрезкой плит (clip-path на местах плит, переход CSS), тень края — тень самой
//           колоды (filter на `.p2-deck`, тот же слой); плита помощника выходит из-под колоды (shell.css, helper.css);
//           слайд, лента и строка «Слайд N из M» едут transform'ом к своим местам в узкой раскладке (замерены один раз
//           в момент нажатия);
//   520 мс  узкая раскладка ставится разом — всё уже стоит на её местах; ходы снимаются; компактный вид проявляется.
// Закрытие (340 мс):
//   0 мс    компактный вид гаснет за 120 мс (раскладка ещё узкая);
//   120 мс  широкая раскладка ставится разом, колода подрезана до узкой ширины, слайд и лента стоят на прежних местах
//           (transform), — и край колоды едет вправо, накрывая плиту помощника (она непрозрачна, пока не накрыта),
//           всё возвращается к своим местам, колонка полного вида открывается краем;
//   460 мс  плита помощника убирается (уже под колодой).
// Все ходы начинаются одной сменой стилей в одном кадре: переходы CSS на элементах (не псевдоэлементах).
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { layoutRect, type LayoutRect } from "./stage";

export const FLIP_OPEN_MS = 520;
export const FLIP_CLOSE_MS = 340;
/** Сколько гаснет компактный вид перед закрытием. */
export const CLOSE_FADE_MS = 120;
const EASE = "cubic-bezier(0.2, 0, 0, 1)";
/** Только для проверки кадров (Safari WebDriver): `window.__animSlow = 10` замедляет таймеры фаз вместе с ходами. */
const slow = (ms: number) => ms * (typeof window !== "undefined" && Number((window as unknown as { __animSlow?: number }).__animSlow) > 0 ? Number((window as unknown as { __animSlow?: number }).__animSlow) : 1);
/** Место помощника: плита 400 + зазор 16. */
export const HELPER_CUT = 416;

/** Что едет к своему месту в другой раскладке (ни один не вложен в другой). */
export const FLIP_TARGETS: Array<{ sel: string; scale?: boolean }> = [
  { sel: ".ra-whx > div > p" },
  { sel: ".ra-whx .ra-whr" },
  { sel: ".ra-stage", scale: true },
  { sel: ".p2-film" },
];

/** transform из места `from` в место `to` (сдвиг левого верхнего угла и, для слайда, масштаб по ширине); null — на месте. */
export function flipFrom(from: LayoutRect, to: LayoutRect, scale = false): string | null {
  const dx = from.left - to.left;
  const dy = from.top - to.top;
  const s = scale && to.width > 0 ? from.width / to.width : 1;
  if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(s - 1) < 0.002) return null;
  const r = (v: number) => Math.round(v * 100) / 100;
  return s !== 1 ? `translate(${r(dx)}px, ${r(dy)}px) scale(${Math.round(s * 10000) / 10000})` : `translate(${r(dx)}px, ${r(dy)}px)`;
}

/** Подрезка места плиты шириной `w` и высотой `h` справа на `cut` px: прямой край со скруглёнными на 40 px углами, как у
 *  плиты; сверху и слева — запас под тени плит. Многоугольник в px, без calc(): вершины переходят одна в одну и в
 *  Safari (calc() в многоугольнике он не интерполирует — край прыгал). */
export function plateClip(cut: number, w: number, h: number): string {
  const r = (v: number) => `${Math.round(v * 100) / 100}px`;
  const R = w - cut;
  const pts: string[] = ["-64px -64px", `${r(R - 40)} -64px`, `${r(R - 40)} 0px`];
  const N = 6;
  for (let i = 1; i < N; i++) {
    const t = (i / N) * (Math.PI / 2);
    pts.push(`${r(R - 40 + 40 * Math.sin(t))} ${r(40 - 40 * Math.cos(t))}`);
  }
  pts.push(`${r(R)} 40px`, `${r(R)} ${r(h - 40)}`);
  for (let i = 1; i < N; i++) {
    const t = (i / N) * (Math.PI / 2);
    pts.push(`${r(R - 40 + 40 * Math.cos(t))} ${r(h - 40 + 40 * Math.sin(t))}`);
  }
  pts.push(`${r(R - 40)} ${r(h)}`, `-64px ${r(h)}`);
  return `polygon(${pts.join(", ")})`;
}

export type HelperPhase = "closed" | "opening" | "open" | "fading" | "closing";

/** Классы обёртки колоды по фазе: `hp-open` — плита помощника видна, `hp-nar` — узкая раскладка, `hp-go` — открытие
 *  (полный вид гаснет), `hp-out` — компактный вид гаснет. */
export function phaseClasses(p: HelperPhase): string {
  switch (p) {
    case "closed": return "hp-closed";
    case "opening": return "hp-open hp-go";
    case "open": return "hp-open hp-nar";
    case "fading": return "hp-open hp-nar hp-out";
    case "closing": return "hp-open hp-back";
  }
}

const slotsOf = (wrap: HTMLElement) => Array.from(wrap.querySelectorAll<HTMLElement>(".p2-deck > .p2-slot"));
const deckOf = (wrap: HTMLElement) => wrap.querySelector<HTMLElement>(".p2-deck");

/** Плита с тяжёлым содержимым («Результат»: слайд, лента — свои слои): подрезка clip-path в Safari не обновляется
 *  на её слоях посреди хода (край стоял на месте, кадры настоящего Safari). Её край — встречный сдвиг: место плиты
 *  с обрезкой по своему краю (overflow, скругление 40) едет влево на `cut`, а сама плита — на столько же вправо;
 *  обрезку по краю Safari ведёт на слоях верно. Тень этой плиты падает на тёмную плиту 03 — её на время хода не видно. */
const heavy = (el: HTMLElement) => !!el.querySelector(".ra-two");
function setClip(slots: HTMLElement[], cut: number, ms: number) {
  const tr = ms ? `${ms}ms ${EASE}` : "";
  for (const el of slots) {
    if (heavy(el)) {
      const inner = el.firstElementChild as HTMLElement | null;
      el.style.overflow = "hidden";
      el.style.borderRadius = "40px";
      el.style.transition = ms ? `translate ${tr}` : "none";
      el.style.translate = `${-cut}px 0px`;
      if (inner) {
        inner.style.transition = ms ? `translate ${tr}` : "none";
        inner.style.translate = `${cut}px 0px`;
      }
      continue;
    }
    el.style.transition = ms ? `clip-path ${tr}, -webkit-clip-path ${tr}` : "none";
    const c = plateClip(cut, el.offsetWidth, el.offsetHeight);
    el.style.clipPath = c;
    el.style.setProperty("-webkit-clip-path", c);
  }
}
function clearClip(slots: HTMLElement[]) {
  const all: HTMLElement[] = [];
  for (const el of slots) {
    const inner = el.firstElementChild as HTMLElement | null;
    for (const x of inner ? [el, inner] : [el]) {
      x.style.transition = "none";
      x.style.translate = "";
      all.push(x);
    }
    el.style.overflow = "";
    el.style.borderRadius = "";
    el.style.clipPath = "";
    el.style.removeProperty("-webkit-clip-path");
  }
  requestAnimationFrame(() => requestAnimationFrame(() => all.forEach((el) => { el.style.transition = ""; })));
}
type Moved = Array<{ el: HTMLElement; t: string }>;
function place(moved: Moved, ms: number, to: "t" | "none") {
  for (const { el, t } of moved) {
    el.style.transformOrigin = "0 0";
    el.style.transition = ms ? `transform ${ms}ms ${EASE}` : "none";
    el.style.transform = to === "t" ? t : "";
  }
}
function unplace(moved: Moved) {
  // снятие хода — без перехода (иначе переход стилей элемента повёл бы его обратно), переход возвращается через кадр
  for (const { el } of moved) {
    el.style.transition = "none";
    el.style.transform = "";
    el.style.transformOrigin = "";
  }
  const els = moved.map(({ el }) => el);
  requestAnimationFrame(() => requestAnimationFrame(() => els.forEach((el) => { el.style.transition = ""; })));
}
const visible = (wrap: HTMLElement) => FLIP_TARGETS.flatMap((t) =>
  Array.from(wrap.querySelectorAll<HTMLElement>(t.sel)).filter((el) => el.getClientRects().length > 0).map((el) => ({ el, scale: !!t.scale })));

/** Фаза помощника для обёртки `ref`: `want` — помощник открыт; `active` — экран «Результат» (иначе фаза следует
 *  `want` сразу, как раньше). */
export function useHelperMotion(ref: RefObject<HTMLElement>, want: boolean, active: boolean): HelperPhase {
  const [phase, setPhase] = useState<HelperPhase>(want ? "open" : "closed");
  const moved = useRef<Moved>([]);
  const timer = useRef(0);

  // смена желания: вне «Результата» или при «уменьшить движение» — сразу; иначе — первая фаза хода
  useLayoutEffect(() => {
    const done = want ? "open" : "closed";
    if (phase === done || (want && phase === "opening") || (!want && (phase === "fading" || phase === "closing"))) return;
    const wrap = ref.current;
    window.clearTimeout(timer.current);
    if (!active || !wrap || prefersReducedMotion() || (phase !== "open" && phase !== "closed")) {
      // прерванный ход: всё снимается, раскладка — целевая
      const slots = wrap ? slotsOf(wrap) : [];
      clearClip(slots);
      unplace(moved.current);
      moved.current = [];
      if (wrap) deckOf(wrap)?.classList.remove("p2-dkm");
      setPhase(done);
      return;
    }
    if (want) {
      // открытие: замер узкой раскладки (класс на этот же кадр, до отрисовки), ход к ней в широкой
      const els = visible(wrap);
      const from = els.map(({ el }) => layoutRect(el));
      wrap.classList.add("hp-nar");
      const to = els.map(({ el }) => layoutRect(el));
      wrap.classList.remove("hp-nar");
      moved.current = els.flatMap(({ el, scale }, i) => {
        const t = flipFrom(to[i], from[i], scale);
        return t ? [{ el, t }] : [];
      });
      const slots = slotsOf(wrap);
      setClip(slots, 0, 0);
      place(moved.current, 0, "none");
      void wrap.offsetWidth;
      deckOf(wrap)?.classList.add("p2-dkm");
      setClip(slots, HELPER_CUT, FLIP_OPEN_MS);
      place(moved.current, FLIP_OPEN_MS, "t");
      setPhase("opening");
      timer.current = window.setTimeout(() => setPhase("open"), slow(FLIP_OPEN_MS));
    } else {
      setPhase("fading");
      timer.current = window.setTimeout(() => setPhase("closing"), slow(CLOSE_FADE_MS));
    }
  });

  // кадр смены раскладки: открытие доиграло — узкая раскладка стоит, ходы и подрезка снимаются (всё уже на местах);
  // закрытие — широкая раскладка поставлена: подрезка до узкой и прежние места, затем ход к широкой
  const was = useRef(phase);
  useLayoutEffect(() => {
    const prev = was.current;
    was.current = phase;
    const wrap = ref.current;
    if (!wrap || prev === phase) return;
    const slots = slotsOf(wrap);
    if (prev === "opening" && phase === "open") {
      clearClip(slots);
      unplace(moved.current);
      moved.current = [];
      deckOf(wrap)?.classList.remove("p2-dkm");
    }
    if (prev === "fading" && phase === "closing") {
      // прежние места (узкая раскладка) — возвратом класса на этот же кадр
      const els = visible(wrap);
      const now = els.map(({ el }) => layoutRect(el));
      wrap.classList.add("hp-nar");
      const before = els.map(({ el }) => layoutRect(el));
      wrap.classList.remove("hp-nar");
      moved.current = els.flatMap(({ el, scale }, i) => {
        const t = flipFrom(before[i], now[i], scale);
        return t ? [{ el, t }] : [];
      });
      setClip(slots, HELPER_CUT, 0);
      place(moved.current, 0, "t");
      void wrap.offsetWidth;
      deckOf(wrap)?.classList.add("p2-dkm");
      setClip(slots, 0, FLIP_CLOSE_MS);
      place(moved.current, FLIP_CLOSE_MS, "none");
      timer.current = window.setTimeout(() => setPhase("closed"), slow(FLIP_CLOSE_MS));
    }
    if (prev === "closing" && phase === "closed") {
      clearClip(slots);
      unplace(moved.current);
      moved.current = [];
      deckOf(wrap)?.classList.remove("p2-dkm");
    }
  }, [phase, ref]);

  useEffect(() => () => window.clearTimeout(timer.current), []);
  return active ? phase : want ? "open" : "closed";
}
