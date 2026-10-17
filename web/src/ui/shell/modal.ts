// Плиты поверх колоды стопкой (окно уже 1280: слои, лист «Подробнее», помощник) — фокус, клавиатура и прокрутка
// страницы под ними. Чистые правила — здесь же, рядом с хуками (modal.test.ts).
//  - Фокус возвращается одним путём (`useFocusReturn`, его зовёт слой): что открыло плиту, запоминается в кадре открытия —
//    раньше, чем колода сделает всё под плитой inert (inert снимает фокус); плита закрылась, а фокус остался в ней, на
//    затемнении или ни на чём — он возвращается туда.
//  - Пока плита сверху, страница под ней не прокручивается (`useScrollLock`: overflow hidden на <html>; классическая
//    полоса прокрутки окна держит своё место — ширина не прыгает), а место страницы возвращается, когда плита закрылась.
//  - Смена экрана или шага стопкой: плита, которую надо видеть, выше окна — страница едет к её верху (`scrollFor`).
import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import type { UiState } from "../deck/geometry";

/** То, что умеет `Element` для решения о фокусе (в тестах — заглушка). */
interface FocusNode { closest?(sel: string): unknown }

/** Фокус потерян — вернуть его тому, что открыло плиту: он ни на чём (`body`), в закрывшейся плите или на затемнении
 *  (щелчок по затемнению). Фокус, который человек сам увёл в другое место, не трогается. */
export function focusLost<T extends FocusNode>(now: T | null, body: T | null, inside: (e: T) => boolean): boolean {
  if (!now || now === body) return true;
  return inside(now) || !!now.closest?.(".p2-dim");
}

/** Возврат фокуса для плиты `box`, пока `open`: запомнить в кадре открытия (layout-эффект — раньше inert колоды), вернуть
 *  после закрытия (обычный эффект — когда колода уже сняла inert в своём layout-эффекте). */
export function useFocusReturn(open: boolean, box: RefObject<HTMLElement>): void {
  const back = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const a = document.activeElement;
    if (a instanceof HTMLElement && a !== document.body && !box.current?.contains(a)) back.current = a;
  }, [open, box]);
  useEffect(() => {
    if (open || !back.current) return;
    const b = back.current;
    back.current = null;
    const inside = (e: Element) => !!box.current?.contains(e);
    if (b.isConnected && !b.closest("[inert]") && focusLost<Element>(document.activeElement, document.body, inside)) b.focus({ preventScroll: true });
  }, [open, box]);
}

/** Классы <html>, пока страница под плитой заперта: полоса прокрутки окна (`bar`, px) была — её место остаётся. */
export function lockClasses(bar: number): string[] {
  return bar > 0 ? ["p2-lock", "p2-lock-bar"] : ["p2-lock"];
}

/** Страница не прокручивается, пока `on`; закрылось — прокрутка там же, где была. */
export function useScrollLock(on: boolean): void {
  useLayoutEffect(() => {
    if (!on) return;
    const root = document.documentElement;
    const y = window.scrollY;
    const cls = lockClasses(window.innerWidth - root.clientWidth);
    root.classList.add(...cls);
    return () => {
      root.classList.remove(...cls);
      if (Math.abs(window.scrollY - y) >= 1) window.scrollTo(0, y);
    };
  }, [on]);
}

/** Плита колоды, которую человек должен видеть на этом экране и шаге: 0 — шаблон, 1 — текст, 2 — параметры и сборка,
 *  3 — результат. */
export function stackTarget(ui: Pick<UiState, "screen" | "open" | "more">): 0 | 1 | 2 | 3 {
  if (ui.screen === "result") return 3;
  if (ui.screen === "build" || ui.more) return 2;
  return ui.open === "tpl" ? 0 : 1;
}

/** Зазор над верхом плиты, когда страница едет к ней, px. */
export const SCROLL_GAP = 8;

/** Куда прокрутить страницу, чтобы верх плиты (`top` — от начала страницы) был виден; null — он и так не выше окна. */
export function scrollFor(top: number, scrollY: number): number | null {
  return top < scrollY ? Math.max(0, Math.round(top - SCROLL_GAP)) : null;
}
